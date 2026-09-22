#!/usr/bin/env python3

# author: Ole Schuett

import os
import sys
import atexit
import socket
import shutil
import tomllib
import argparse
import subprocess
from time import sleep
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, TypedDict, IO, List, Literal, Optional

import requests

# ======================================================================================
JobState = Literal[
    "QUEUING",
    "RUNNING",
    "CANCELING",
    "CANCELED",
    "SUCCEEDED",
    "FAILED",
    "OUT_OF_MEMORY",
    "TIMEOUT",
    "PREEMPTED",
    "CI_ERROR",
]


# ======================================================================================
JobSpec = TypedDict(
    "JobSpec",
    {
        "target_name": str,
        "target_type": str,  # Literal["local", "remote", "cscs"],
        "git_branch": str,
        "git_ref": str,
        "git_repo": str,
        "report_upload_url": str,
        "artifacts_upload_url": str,
        "nodepool": str,
        "arch": str,  # Literal["x86", "arm64"],
        "cpu": float,
        "gpu": int,
        "use_cache": bool,
        "cache_from": str,
        "remote_host": str,
        "remote_cmd": str,
        "cscs_pipeline": str,
        "dockerfile": str,
        "build_path": str,
        "build_args": str,
    },
    total=False,
)


# ======================================================================================
def main() -> None:
    # Parse command line arguments.
    parser = argparse.ArgumentParser(description="CP2K-CI Worker")
    parser.add_argument("config", type=Path)
    args = parser.parse_args()

    # Parse config file.
    with open(args.config, "rb") as f:
        config = tomllib.load(f)
    workers: List[Worker] = []
    for name, worker_config in config["workers"].items():
        workers.append(Worker(name=name, config=worker_config, secret=config["secret"]))

    spack_cache_start()
    prev_num_idle_workers = -1

    # Main loop.
    while True:
        idle_workers = [w for w in workers if w.is_idle()]
        if len(idle_workers) != prev_num_idle_workers:
            print(f"{len(workers) - len(idle_workers)} / {len(workers)} workers busy")
            prev_num_idle_workers = len(idle_workers)

            # Remove old intermediate containers when all workers are idle.
            if len(idle_workers) == len(workers):
                subprocess.run(["buildah", "rm", "--all"])
                for w in workers:
                    shutil.rmtree(w.tmpdir, ignore_errors=True)

        if idle_workers:  # ask for new job
            # Use dict instead of set to preserve the order of nodepools
            # to ensure that jobs for rare nodepools are allocated first.
            idle_nodepools = {np: None for w in idle_workers for np in w.nodepools}
            r = idle_workers[0].api_request(
                "POST", "/api/jobs", json={"idle_nodepools": list(idle_nodepools)}
            )
            if r.status_code == 200:
                payload = r.json()
                job = Job(name=payload["name"], spec=payload["spec"])
                idle_workers[0].run(job)

        sleep(5)


# ======================================================================================
class Job:
    def __init__(self, name: str, spec: JobSpec):
        self.name = name
        self.spec = spec

    # ----------------------------------------------------------------------------------
    def upload_report(self, report_path: Path) -> None:
        content_type = "text/plain;charset=utf-8"
        self.upload_file(report_path, self.spec["report_upload_url"], content_type)

    # ----------------------------------------------------------------------------------
    def upload_artifacts(self, zip_file: Path) -> None:
        self.upload_file(zip_file, self.spec["artifacts_upload_url"], "application/zip")

    # ----------------------------------------------------------------------------------
    def upload_file(self, local_file: Path, url: str, content_type: str) -> None:
        headers = {"cache-control": "no-cache", "content-type": content_type}
        requests.put(url, data=local_file.read_bytes(), headers=headers)


# ======================================================================================
class Worker:
    def __init__(self, name: str, config: Dict[str, Any], secret: str):
        self.name: str = name
        self.secret: str = secret
        self.memory: str = config["memory"]
        self.cpuset: str = config["cpuset"]
        self.num_cpus = cpuset_size(self.cpuset)
        self.nodepools: List[str] = config["nodepools"]
        self.workdir = Path(config["workdir"])
        assert (self.workdir / "cp2k" / "make_cp2k.sh").exists()
        self.tmpdir = self.workdir / "tmp"
        self.pid_path = self.workdir / "worker.pid"
        self.report_path = self.workdir / "report.log"
        self.report_fh: Optional[IO[bytes]] = None

    # ----------------------------------------------------------------------------------
    def is_idle(self) -> bool:
        if not self.pid_path.exists():
            return True
        if check_pid(int(self.pid_path.read_text())):
            return False  # process exists
        print(f"Removing stale pid file: {self.pid_path}")
        self.pid_path.unlink()
        return True

    # ----------------------------------------------------------------------------------
    def run(self, job: Job) -> None:
        # Fork
        sys.stdout.flush()
        sys.stderr.flush()
        if os.fork() > 0:
            return
        os.setsid()
        self.pid_path.write_text(str(os.getpid()))
        atexit.register(lambda: self.pid_path.unlink())

        # Ready environment
        self.tmpdir.mkdir(exist_ok=True)
        os.environ["TMPDIR"] = str(self.tmpdir)
        spack_cache_remove_old_than(days=30)
        subprocess.run(["podman", "container", "prune", "-f", "--filter=until=24h"])
        subprocess.run(["podman", "image", "prune", "-a", "-f", "--filter=until=24h"])

        # Preamble
        self.report_path.unlink(missing_ok=True)
        self.report_fh = open(self.report_path, "wb")
        self.set_job_state(job, "RUNNING")
        self.report(f"StartDate: {now()}\n")
        self.report(f"Worker: {self.name}\n")
        self.report(f"Memory: {self.memory}\n")
        self.report(f"CpuId: {self.num_cpus}x {cpu_id()}\n")
        self.report(f"SpackCache: {"ready" if spack_cache_ready() else "n/a"}\n")

        # Run job
        end_state = self.inner_run(job)

        # Finish
        self.report("\n")
        self.report(f"EndState: {end_state}\n")
        self.report(f"EndDate: {now()}\n")
        self.report_fh.close()
        job.upload_report(self.report_path)
        self.set_job_state(job, end_state)
        sys.exit(0)

    # ----------------------------------------------------------------------------------
    def inner_run(self, job: Job) -> JobState:
        # Fetch git branch.
        p = self.popen(["git", "fetch", "origin", job.spec["git_branch"]], report=False)
        if p.wait() != 0:
            return "CI_ERROR"

        # Checkout git commit.
        p = self.popen(["git", "checkout", job.spec["git_ref"]], report=False)
        if p.wait() != 0:
            return "CI_ERROR"

        # Report git commit metadata.
        git_log_format = "--pretty=%nCommitSHA: %H%nCommitTime: %ci%nCommitAuthor: %an%nCommitSubject: %s%n"
        p = self.popen(["git", "--no-pager", "log", "-1", git_log_format])
        if p.wait() != 0:
            return "CI_ERROR"

        resources = [
            "--shm-size=1g",
            f"--memory={self.memory}",
            f"--cpuset-cpus={self.cpuset}",
            f"--env=PYTHON_CPU_COUNT={self.num_cpus}",
        ]

        build_command = [
            "podman",
            "build",
            "--tag=" + job.name,
            "--file=." + job.spec["dockerfile"],
            *resources,
        ]
        for arg in job.spec["build_args"].strip().split():
            build_command.append(f"--build-arg={arg}")
        if not job.spec["use_cache"]:
            build_command.append("--no-cache")
        build_command.append("." + job.spec["build_path"])

        # Build container.
        p = self.popen(build_command)
        while p.poll() is None:
            self.send_heartbeat(job)
            if self.get_job_state(job) == "CANCELING":
                try:
                    print("Send SIGTERM to podman.")
                    p.terminate()
                    p.wait(timeout=3)  # let buildah release working containers
                except subprocess.TimeoutExpired:
                    print("Podman did not exit in time, sending SIGKILL.")
                    p.kill()
                    p.wait()
                return "CANCELED"
            else:
                job.upload_report(self.report_path)
                # print("Waiting for child process")
                sleep(30)

        if p.returncode == 137:
            return "OUT_OF_MEMORY"
        elif p.returncode != 0:
            return "FAILED"

        # Run container.
        p = self.popen(["podman", "run", *resources, f"--name={job.name}", job.name])
        if p.wait() != 0:
            return "FAILED"

        # Upload artifacts.
        artifacts_path = self.workdir / "artifacts"
        shutil.rmtree(artifacts_path, ignore_errors=True)
        p = self.popen(
            ["podman", "cp", f"{job.name}:/workspace/artifacts", f"{self.workdir}"],
            report=False,
        )
        if p.wait() == 0:
            self.report(f"\nUploading artifacts...\n")
            shutil.make_archive(str(artifacts_path), "zip", artifacts_path)
            job.upload_artifacts(artifacts_path.with_suffix(".zip"))

        return "SUCCEEDED"

    # ----------------------------------------------------------------------------------
    def report(self, text: str) -> None:
        assert self.report_fh
        self.report_fh.write(text.encode("utf8"))
        self.report_fh.flush()

    # ----------------------------------------------------------------------------------
    def popen(self, args: List[str], report: bool = True) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            args,
            cwd=self.workdir / "cp2k",
            stdout=self.report_fh if report else subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

    # ----------------------------------------------------------------------------------
    def send_heartbeat(self, job: Job) -> None:
        self.api_request("PATCH", f"/api/jobs/{job.name}", json={})

    # ----------------------------------------------------------------------------------
    def get_job_state(self, job: Job) -> JobState:
        r = self.api_request("GET", f"/api/jobs/{job.name}")
        state: JobState = r.json()["state"]
        return state

    # ----------------------------------------------------------------------------------
    def set_job_state(self, job: Job, state: JobState) -> None:
        print(f"Setting state of {job.name} to {state}.")
        self.api_request("PATCH", f"/api/jobs/{job.name}", json={"state": state})

    # ----------------------------------------------------------------------------------
    def api_request(
        self,
        method: Literal["GET", "POST", "PATCH"],
        path: str,
        json: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        url = "https://ci.cp2k.org" + path
        headers = {"Authorization": f"Bearer {self.secret}", "X-Worker-Name": self.name}
        while True:
            r = requests.request(method=method, url=url, headers=headers, json=json)
            if r.status_code < 500:
                return r
            print(f"Got status {r.status_code} for {method} {path}")
            sleep(10)  # retry


# ======================================================================================
def cpu_id() -> str:
    output = subprocess.run(["cpuid", "-1"], capture_output=True).stdout.decode("utf8")
    return [line[13:] for line in output.split("\n") if "(synth)" in line][0]


# ======================================================================================
def cpuset_size(cpuset: str) -> int:
    p = subprocess.run(
        [
            "podman",
            "--transient-store",  # quick startup
            "run",
            f"--cpuset-cpus={cpuset}",
            "docker.io/ubuntu:26.04",
            "nproc",
        ],
        check=True,
        capture_output=True,
    )
    return int(p.stdout)


# ======================================================================================
def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat(sep=" ")


# ======================================================================================
def check_pid(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as e:
        return False
    else:
        return True


# ======================================================================================
def spack_cache_ready() -> bool:
    spack_cache_url = "http://host.containers.internal:9000/spack-cache"
    p = subprocess.run(
        [
            "podman",
            "--transient-store",  # quick startup
            "run",
            "docker.io/ubuntu:26.04",
            "/usr/lib/apt/apt-helper",  # curl is not available in ubuntu base image
            "download-file",
            spack_cache_url,
            "/tmp/foo",
        ],
        stdout=subprocess.DEVNULL,
    )
    return p.returncode == 0


# ======================================================================================
def spack_cache_start() -> None:
    if spack_cache_ready():
        print("Found running spack-cache.")
    elif subprocess.run(["podman", "start", "spack-cache"]).returncode == 0:
        print("Re-started existing spack-cache.")
    else:
        print("Creating new spack-cache.")
        subprocess.run(
            [
                "podman",
                "run",
                "--name=spack-cache",
                "--detach",
                "-p",
                "9000:9000",
                "quay.io/minio/minio",
                "server",
                "/data",
            ],
            check=True,
        )
        sleep(3)
        subprocess.run(["podman", "container", "logs", "spack-cache"], check=True)

        # Configure alias for localhost.
        spack_cache_exec(
            [
                "mc",
                "alias",
                "set",
                "local",
                "http://localhost:9000",
                "minioadmin",
                "minioadmin",
            ]
        )

        # Create bucket.
        spack_cache_exec(["mc", "mb", "local/spack-cache"])

        # Make bucket public.
        spack_cache_exec(["mc", "anonymous", "set", "public", "local/spack-cache"])

    # Print bucket size.
    spack_cache_exec(["mc", "du", "local/spack-cache/"])


# ======================================================================================
def spack_cache_remove_old_than(days: int) -> None:
    spack_cache_exec(
        ["mc", "rm", "-r", "--force", f"--older-than={days}d", "local/spack-cache/"]
    )


# ======================================================================================
def spack_cache_exec(args: List[str]) -> None:
    subprocess.run(["podman", "exec", "spack-cache", *args], check=True)


# ======================================================================================
if __name__ == "__main__":
    main()

# EOF
