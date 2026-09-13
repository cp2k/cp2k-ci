#!/usr/bin/env python3

# author: Ole Schuett

import os
import socket
import argparse
import subprocess
from time import sleep
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, TypedDict, IO, List, Literal, Optional

import requests

WORKER_NAME = f"{socket.getfqdn()}:{os.getpid()}"
WORKER_SECRET = os.environ["CP2KCI_WORKER_SECRET"]

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
        "nodepools": List[str],
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
    parser.add_argument("workdir", type=Path, help="Path to cp2k git repository")
    args = parser.parse_args()
    assert (args.workdir / "make_cp2k.sh").exists()

    print(f"Worker {WORKER_NAME} started in {args.workdir}...")

    while True:
        r = api_request("POST", "/api/jobs")  # ask for new job
        if r.status_code == 200:
            payload = r.json()
            job = Job(name=payload["name"], spec=payload["spec"], workdir=args.workdir)
            process(job)
        sleep(5)


# ======================================================================================
class Job:
    def __init__(self, name: str, spec: JobSpec, workdir: Path):
        self.name = name
        self.spec = spec
        self.workdir = workdir
        self.report_path = self.workdir / "ci_report.log"  # ignored by precommit
        self.report_fh = open(self.report_path, "wb")  # truncates

    def upload_report(self) -> None:
        content_type = "text/plain;charset=utf-8"
        upload_file(self.report_path, self.spec["report_upload_url"], content_type)

    def log(self, text: str) -> None:
        self.report_fh.write(text.encode("utf8"))
        self.report_fh.flush()

    def run(self, args: List[str], log: bool = False) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            args,
            cwd=self.workdir,
            stdout=self.report_fh if log else None,
            stderr=subprocess.STDOUT if log else None,
        )

    def get_state(self) -> JobState:
        r = api_request("GET", f"/api/jobs/{self.name}")
        state: JobState = r.json()["state"]
        return state

    def set_state(self, state: JobState) -> None:
        print(f"Setting state of {self.name} to {state}.")
        api_request("PATCH", f"/api/jobs/{self.name}", json={"state": state})


# ======================================================================================
def process(job: Job) -> None:
    print(f"Writing report to: {job.report_path}")

    job.set_state("RUNNING")
    job.log(f"StartDate: {now()}\n\n")
    end_state = inner(job)
    job.log(f"\nEndDate: {now()}\n")
    job.upload_report()
    # TODO upload artifacts

    job.set_state(end_state)


# ======================================================================================
def inner(job: Job) -> JobState:
    print(f"Writing report to: {job.report_path}")

    # TODO write worker id
    # TODO write CPU id, e.g. platform.machine()
    # https://github.com/cp2k/cp2k-ci/commit/05442adfddb0939a7f14292208da2c6ead3df457#commitcomment-200212912

    # Remove old containers and images.
    job.run(["buildah", "rm", "--all"]).wait()
    job.run(["podman", "container", "prune", "-f", "--filter=until=12h"]).wait()
    job.run(["podman", "image", "prune", "-a", "-f", "--filter=until=12h"]).wait()

    p = job.run(["git", "fetch", "origin", job.spec["git_branch"]])
    if p.wait() != 0:
        return "FAILED"

    p = job.run(["git", "checkout", job.spec["git_ref"]])
    if p.wait() != 0:
        return "FAILED"

    git_log_format = "--pretty=%nCommitSHA: %H%nCommitTime: %ci%nCommitAuthor: %an%nCommitSubject: %s%n"
    p = job.run(["git", "--no-pager", "log", "-1", git_log_format], log=True)
    if p.wait() != 0:
        return "FAILED"

    build_command = [
        "podman",
        "build",
        "--tag=" + job.name,
        # --memory=${MEMORY_LIMIT_MB}m" \
        "--file=." + job.spec["dockerfile"],
        "--shm-size=1g",
    ]
    for arg in job.spec["build_args"].strip().split():
        build_command.append(f"--build-arg={arg}")
    if not job.spec["use_cache"]:
        build_command.append("--no-cache")
    build_command.append("." + job.spec["build_path"])

    p = job.run(build_command, log=True)
    while p.poll() is None:
        if job.get_state() == "CANCELING":
            try:
                print("Send SIGTERM to podman.")
                p.terminate()
                p.wait(timeout=3)  # give buildah chance to release working containers
            except subprocess.TimeoutExpired:
                print("Podman did not exit in time, sending SIGKILL.")
                p.kill()
                p.wait()
            return "CANCELED"
        else:
            job.upload_report()
            print("Waiting for child process")
            sleep(30)

    if p.returncode == 137:
        return "OUT_OF_MEMORY"
    elif p.returncode != 0:
        return "FAILED"

    # docker run --init --cap-add=SYS_PTRACE --shm-size=1g \
    #    --memory "${MEMORY_LIMIT_MB}m" \
    #    --env "GIT_BRANCH=${GIT_BRANCH}" \
    #    --env "GIT_REF=${GIT_REF}" \
    #    --name "my_container" \

    p = job.run(["podman", "run", job.name], log=True)
    if p.wait() != 0:
        return "FAILED"

    return "SUCCEEDED"


# ======================================================================================
def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat(sep=" ")


# ======================================================================================
def upload_file(local_file: Path, url: str, content_type: str) -> None:
    headers = {"cache-control": "no-cache", "content-type": content_type}
    requests.put(url, data=local_file.read_bytes(), headers=headers)


# ======================================================================================
def api_request(
    method: Literal["GET", "POST", "PATCH"],
    path: str,
    json: Optional[Dict[str, str]] = None,
) -> requests.Response:

    headers = {
        "Authorization": f"Bearer {WORKER_SECRET}",
        "X-Worker-Name": WORKER_NAME,
    }
    while True:
        r = requests.request(
            method=method, url="https://ci.cp2k.org" + path, headers=headers, json=json
        )
        if r.status_code < 500:
            return r

        print(f"Got status {r.status_code} for {method} {path}")
        sleep(10)  # retry


# ======================================================================================
if __name__ == "__main__":
    main()

# EOF
