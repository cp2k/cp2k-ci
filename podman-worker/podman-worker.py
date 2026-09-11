#!/usr/bin/env python3

# author: Ole Schuett

import os
import socket
import atexit
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


# # ======================================================================================
# @atexit.register
# def goodbye() -> None:
#     print("You are now leaving the Python sector.")  # TODO send PREEMPTED


# ======================================================================================
def main() -> None:
    print(f"Worker {WORKER_NAME} started...")

    while True:
        r = api_request("POST", "/api/jobs")  # ask for new job
        if r.status_code == 200:
            payload = r.json()
            job = Job(name=payload["name"], spec=payload["spec"])
            process(job)
        sleep(5)


# ======================================================================================
def process(job: Job) -> None:
    print(f"Writing report to: {job.report_path}")

    job.log(f"StartDate: {now()}\n\n")

    p = job.run(["git", "fetch", "upstream", job.spec["git_branch"]])
    assert p.wait() == 0

    p = job.run(
        ["git", "-c", "advice.detachedHead=false", "checkout", job.spec["git_ref"]]
    )
    assert p.wait() == 0

    git_log_format = "--pretty=%nCommitSHA: %H%nCommitTime: %ci%nCommitAuthor: %an%nCommitSubject: %s%n"
    p = job.run(["git", "--no-pager", "log", "-1", git_log_format])
    assert p.wait() == 0

    podman_build = [
        "podman",
        "build",
        # --memory=${MEMORY_LIMIT_MB}m" \
        "--file=." + job.spec["dockerfile"],
        "--shm-size=1g",
    ]
    for arg in job.spec["build_args"].strip().split():
        podman_build.append(f"--build-arg={arg}")
    if not job.spec["use_cache"]:
        podman_build.append("--no-cache")
    podman_build.append("." + job.spec["build_path"])

    p = job.run(podman_build)
    job.set_state("RUNNING")
    while p.poll() is None:
        if job.get_state() == "CANCELING":
            p.kill()
            p.wait()
        else:
            job.upload_report()
            print("Waiting for child process")
            sleep(30)

    job.log(f"\nEndDate: {now()}\n")
    job.upload_report()

    if job.get_state() == "CANCELING":
        job.set_state("CANCELED")
    elif p.returncode == 0:
        job.set_state("SUCCEEDED")
    elif p.returncode == 137:
        job.set_state("OUT_OF_MEMORY")
    else:
        job.set_state("FAILED")

    # TODO upload artifacts


# ======================================================================================
class Job:
    def __init__(self, name: str, spec: JobSpec):
        self.name = name
        self.spec = spec
        self.workdir = Path("/home/ole/git/cp2k")
        assert self.workdir.exists()
        self.report_path = self.workdir / "ci_report.txt"
        self.report_fh = open(self.report_path, "wb")  # truncates

    def upload_report(self) -> None:
        content_type = "text/plain;charset=utf-8"
        upload_file(self.report_path, self.spec["report_upload_url"], content_type)

    def log(self, text: str) -> None:
        self.report_fh.write(text.encode("utf8"))
        self.report_fh.flush()

    def run(self, args: List[str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            args, cwd=self.workdir, stdout=self.report_fh, stderr=subprocess.STDOUT
        )

    def get_state(self) -> JobState:
        r = api_request("GET", f"/api/jobs/{self.name}")
        state: JobState = r.json()["state"]
        return state

    def set_state(self, state: JobState) -> None:
        api_request("PATCH", f"/api/jobs/{self.name}", json={"state": state})


# ======================================================================================
def now() -> str:
    return datetime.now(timezone.utc).isoformat(sep=" ")[:16]


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
    r = requests.request(
        method=method, url="https://ci.cp2k.org" + path, headers=headers, json=json
    )
    r.raise_for_status()
    return r


# ======================================================================================
if __name__ == "__main__":
    main()

# EOF
