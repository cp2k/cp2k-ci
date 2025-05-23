#!/usr/bin/env python3

# author: Ole Schuett

import re
import sys
import json
import traceback
from time import sleep
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List, Literal, Union, TypedDict

from target import Target, TargetName
from repository_config import REPOSITORY_CONFIGS, get_repository_config_by_name
from kubernetes_util import KubernetesUtil
from github_util import (
    GithubUtil,
    Commit,
    PullRequest,
    CheckRun,
    CheckRunAction,
    CheckRunExternalId,
    PullRequestNumber,
    GithubEvent,
)

from kubernetes.client.models.v1_job_list import V1JobList
from kubernetes.client.models.v1_job import V1Job

import google.auth  # type: ignore
import google.cloud.pubsub  # type: ignore
import google.cloud.storage  # type: ignore


gcp_project = google.auth.default()[1]
storage_client = google.cloud.storage.Client(project=gcp_project)
subscriber_client = google.cloud.pubsub.SubscriberClient()
output_bucket = storage_client.get_bucket("cp2k-ci")

kubeutil = KubernetesUtil(
    output_bucket=output_bucket,
    image_base=f"us-central1-docker.pkg.dev/{gcp_project}/cp2kci",
)


# TODO Share with frontend.py and cp2kcictl.py
# ======================================================================================
class EchoRequest(TypedDict):
    rpc: Literal["echo"]


class UpdateHealthzBeaconRequest(TypedDict):
    rpc: Literal["update_healthz_beacon"]


class SubmitAllDashboardTestsRequest(TypedDict):
    rpc: Literal["submit_all_dashboard_tests"]


class SubmitTaggedDashboardTestsRequest(TypedDict):
    rpc: Literal["submit_tagged_dashboard_tests"]
    tag: str


class SubmitDashboardTestRequest(TypedDict):
    rpc: Literal["submit_dashboard_test"]
    target: TargetName


class SubmitDashboardTestForceRequest(TypedDict):
    rpc: Literal["submit_dashboard_test_force"]
    target: TargetName


class SubmitCheckRunRequest(TypedDict):
    rpc: Literal["submit_check_run"]
    repo: str
    pr_number: PullRequestNumber
    target: TargetName


class SubmitCheckRunNocacheRequest(TypedDict):
    rpc: Literal["submit_check_run_nocache"]
    repo: str
    pr_number: PullRequestNumber
    target: TargetName


class ProcessPullRequestRequest(TypedDict):
    rpc: Literal["process_pull_request"]
    repo: str
    pr_number: PullRequestNumber


class GithubEventRequest(TypedDict):
    rpc: Literal["github_event"]
    event: str
    body: GithubEvent


RpcRequest = Union[
    EchoRequest,
    UpdateHealthzBeaconRequest,
    SubmitAllDashboardTestsRequest,
    SubmitTaggedDashboardTestsRequest,
    SubmitDashboardTestRequest,
    SubmitDashboardTestForceRequest,
    SubmitCheckRunRequest,
    SubmitCheckRunNocacheRequest,
    ProcessPullRequestRequest,
    GithubEventRequest,
]


# ======================================================================================
@dataclass
class Report:
    summary: str
    status: str
    git_sha: Optional[str]


# ======================================================================================
def main() -> None:
    print("starting")

    # subscribe to pubsub
    sub_name = "projects/" + gcp_project + "/subscriptions/cp2kci-subscription"
    subscriber_client.subscribe(sub_name, process_pubsub_message)

    print("starting main loop")
    for i in range(sys.maxsize):
        try:
            tick(i)
        except:
            print(traceback.format_exc())
        sleep(5)


# ======================================================================================
def tick(cycle: int) -> None:
    run_job_list = kubeutil.list_jobs("cp2kci=run")
    if cycle % 30 == 0:  # every 2.5 minutes
        poll_pull_requests(run_job_list)
    for job in run_job_list.items:
        job_annotations = job.metadata.annotations
        if "cp2kci-dashboard" in job_annotations:
            publish_job_to_dashboard(job)
        if "cp2kci-check-run-url" in job_annotations:
            publish_job_to_github(job)
        if job.status.completion_time and "cp2kci-force" not in job_annotations:
            kubeutil.delete_job(job.metadata.name)


# ======================================================================================
def process_pubsub_message(message: Any) -> None:
    try:
        rpc = json.loads(message.data)
        process_rpc(rpc)
        message.ack()  # ack late in case we get preempted in the middle
    except:
        print(traceback.format_exc())
        message.ack()  # prevent crash looping


# ======================================================================================
def process_rpc(request: RpcRequest) -> None:
    if request["rpc"] == "echo":
        print("Got request: ", request)

    elif request["rpc"] == "update_healthz_beacon":
        blob = output_bucket.blob("healthz_beacon.txt")
        blob.cache_control = "no-cache"
        blob.upload_from_string(datetime.utcnow().isoformat())
        print("Updated healthz_beacon.txt")

    elif request["rpc"] == "github_event":
        process_github_event(request["event"], request["body"])

    elif request["rpc"] == "submit_all_dashboard_tests":
        gh = GithubUtil("cp2k")
        head_sha = gh.get_master_head_sha()
        for target in gh.get_targets():
            submit_dashboard_test(target, head_sha)

    elif request["rpc"] == "submit_tagged_dashboard_tests":
        gh = GithubUtil("cp2k")
        head_sha = gh.get_master_head_sha()
        for target in gh.get_targets():
            if request["tag"] in target.tags:
                submit_dashboard_test(target, head_sha)

    elif request["rpc"] == "submit_dashboard_test":
        gh = GithubUtil("cp2k")
        target = gh.get_target_by_name(request["target"])
        submit_dashboard_test(target, gh.get_master_head_sha())

    elif request["rpc"] == "submit_dashboard_test_force":
        gh = GithubUtil("cp2k")
        target = gh.get_target_by_name(request["target"])
        submit_dashboard_test(target, gh.get_master_head_sha(), force=True)

    elif request["rpc"] == "submit_check_run":
        gh = GithubUtil(request["repo"])
        pr = gh.get_pull_request(request["pr_number"])
        target = gh.get_target_by_name(request["target"], pr)
        submit_check_run(target, gh, pr, sender="_somebody_")

    elif request["rpc"] == "submit_check_run_nocache":
        gh = GithubUtil(request["repo"])
        pr = gh.get_pull_request(request["pr_number"])
        target = gh.get_target_by_name(request["target"], pr)
        submit_check_run(target, gh, pr, sender="_somebody_", use_cache=False)

    elif request["rpc"] == "process_pull_request":
        gh = GithubUtil(request["repo"])
        process_pull_request(gh, request["pr_number"], sender="_somebody_")

    else:
        print("Unknown RPC: " + request["rpc"])


# ======================================================================================
def process_github_event(event: str, body: GithubEvent) -> None:
    action = body.get("action", "")
    print(f"Got github even: {event} action: {action}")

    if event == "pull_request" and action in ("opened", "reopened", "synchronize"):
        gh = GithubUtil(body["repository"]["name"])
        pr_number = body["number"]
        sender = body["sender"]["login"]
        process_pull_request(gh, pr_number, sender)

    elif event == "check_suite" and action == "rerequested":
        # snatch pr_number from existing check_runs
        gh = GithubUtil(body["repository"]["name"])
        prev_check_runs = gh.iterate_check_runs(body["check_suite"]["check_runs_url"])
        ext_id = next(prev_check_runs)["external_id"]
        pr_number, _ = parse_external_id(ext_id)
        sender = body["sender"]["login"]
        process_pull_request(gh, pr_number, sender)

    elif event == "check_run" and action == "rerequested":
        ext_id = body["check_run"]["external_id"]
        pr_number, target_name = parse_external_id(ext_id)
        gh = GithubUtil(body["repository"]["name"])
        pr = gh.get_pull_request(pr_number)
        target = gh.get_target_by_name(target_name, pr)
        sender = body["sender"]["login"]
        submit_check_run(target, gh, pr, sender)

    elif event == "check_run" and action == "requested_action":
        ext_id = body["check_run"]["external_id"]
        pr_number, target_name = parse_external_id(ext_id)
        requested_action = body["requested_action"]["identifier"]
        sender = body["sender"]["login"]
        gh = GithubUtil(body["repository"]["name"])
        pr = gh.get_pull_request(pr_number)
        target = gh.get_target_by_name(target_name, pr)
        if requested_action == "run":
            submit_check_run(target, gh, pr, sender)
        elif requested_action == "run_nocache":
            submit_check_run(target, gh, pr, sender, use_cache=False)
        elif requested_action == "cancel":
            cancel_check_runs(target.name, gh, pr, sender)
        else:
            print(f"Unknown requested action: {requested_action}")
    else:
        pass  # Unhandled github even - there are many of these.


# ======================================================================================
def await_mergeability(
    gh: GithubUtil,
    pr: PullRequest,
    check_run_name: str,
    check_run_external_id: CheckRunExternalId,
) -> PullRequest:
    # https://developer.github.com/v3/git/#checking-mergeability-of-pull-requests

    check_run: CheckRun

    for i in range(10):
        if pr["mergeable"] is not None and not pr["mergeable"]:
            return pr  # not mergeable
        elif pr["mergeable"] is not None and pr["mergeable"]:
            # Check freshness of merge branch.
            merge_commit = gh.get_commit(pr["merge_commit_sha"])
            if any(p["sha"] == pr["head"]["sha"] for p in merge_commit["parents"]):
                return pr  # mergeable

        # This might take a while, tell the user and disable resubmit buttons.
        if i == 0:
            check_run = {
                "name": check_run_name,
                "external_id": check_run_external_id,
                "head_sha": pr["head"]["sha"],
                "started_at": gh.now(),
                "output": {"title": "Waiting for mergeability check", "summary": ""},
            }
            gh.post_check_run(check_run)

        # Reload pull request.
        pr_number = pr["number"]
        print(f"Waiting for mergeability check of PR {pr_number}")
        sleep(5)
        pr = gh.get_pull_request(pr_number)

    # timeout
    check_run["completed_at"] = gh.now()
    check_run["conclusion"] = "failure"
    check_run["output"] = {"title": "Mergeability check timeout.", "summary": ""}
    gh.post_check_run(check_run)
    raise Exception(f"Mergeability check timeout on PR {pr_number}")


# ======================================================================================
def process_pull_request(
    gh: GithubUtil, pr_number: PullRequestNumber, sender: str
) -> None:
    pr: PullRequest = gh.get_pull_request(pr_number)

    # check branch
    if pr["base"]["ref"] != "master":
        print("Ignoring PR for non-master branch: " + pr["base"]["ref"])
        return

    commits = list(gh.iterate_commits(pr["commits_url"]))

    # Find previous check run conclusions, before we call cancel on them.
    prev_check_runs: List[CheckRun] = []
    for commit in reversed(commits):
        prev_check_runs = list(gh.iterate_check_runs(commit["url"] + "/check-runs"))
        if prev_check_runs:
            break
    prev_conclusions: Dict[TargetName, str] = {}
    for prev_check_run in prev_check_runs:
        try:
            _, target_name = parse_external_id(prev_check_run["external_id"])
            prev_conclusions[target_name] = prev_check_run["conclusion"]
        except:
            print(f"Found unparsable external id: " + prev_check_run["external_id"])

    # cancel old jobs
    cancel_check_runs(target_pattern="*", gh=gh, pr=pr, sender=sender)

    # check for merge commits
    if not check_git_history(gh, pr, commits):
        print("Git history test failed - not processing PR further.")
        return

    # submit check runs
    for target in gh.get_targets(pr):
        if target.name in prev_conclusions:
            optional = prev_conclusions[target.name] in ("neutral", "cancelled")
        else:
            optional = not (target.is_required_check or should_trigger(target, gh, pr))
        submit_check_run(target, gh, pr, sender, optional=optional)


# ======================================================================================
def should_trigger(target: Target, gh: GithubUtil, pr: PullRequest) -> bool:
    if target.trigger_path:
        trigger_path_re = re.compile(target.trigger_path)
        for modified_file in gh.iterate_pr_files(pr):
            if trigger_path_re.search(modified_file["filename"]):
                return True
    return False


# ======================================================================================
def check_git_history(gh: GithubUtil, pr: PullRequest, commits: List[Commit]) -> bool:
    check_run: CheckRun = {
        "name": "Git History",
        "external_id": format_external_id(pr["number"], "git-history"),
        "head_sha": pr["head"]["sha"],
        "started_at": gh.now(),
        "completed_at": gh.now(),
    }

    pr = await_mergeability(gh, pr, check_run["name"], check_run["external_id"])

    if not pr["mergeable"]:
        check_run["conclusion"] = "failure"
        check_run["output"] = {"title": "Branch not mergeable.", "summary": ""}
    elif any([len(c["parents"]) != 1 for c in commits]):
        check_run["conclusion"] = "failure"
        help_url = "https://github.com/cp2k/cp2k/wiki/CP2K-CI#git-history-contains-merge-commits"
        check_run["output"] = {
            "title": "Git history contains merge commits.",
            "summary": f"[How to fix this?]({help_url})",
        }
    else:
        check_run["conclusion"] = "success"
        check_run["output"] = {"title": "Git history is fine.", "summary": ""}

    gh.post_check_run(check_run)
    return check_run["conclusion"] == "success"


# ======================================================================================
def format_external_id(
    pr_number: PullRequestNumber, target_name: TargetName | Literal["git-history"]
) -> CheckRunExternalId:
    return CheckRunExternalId(f"{pr_number};{target_name}")


# ======================================================================================
def parse_external_id(
    ext_id: CheckRunExternalId,
) -> Tuple[PullRequestNumber, TargetName]:
    pr_number = PullRequestNumber(ext_id.split(";")[0])
    target_name = TargetName(ext_id.split(";")[1])
    return pr_number, target_name


# ======================================================================================
def submit_check_run(
    target: Target,
    gh: GithubUtil,
    pr: PullRequest,
    sender: str,
    use_cache: bool = True,
    optional: bool = False,
) -> None:
    check_run: CheckRun = {
        "name": target.display_name,
        "external_id": format_external_id(pr["number"], target.name),
        "head_sha": pr["head"]["sha"],
        "started_at": gh.now(),
    }

    if optional:
        check_run["output"] = {"title": "Trigger manually on demand.", "summary": ""}
        check_run["completed_at"] = gh.now()
        check_run["conclusion"] = "neutral"
        check_run["actions"] = [
            {
                "label": "Start",
                "identifier": "run",
                "description": "Trigger test run.",
            }
        ]
        gh.post_check_run(check_run)
        return

    # Let's submit the job.
    pr = await_mergeability(gh, pr, check_run["name"], check_run["external_id"])
    check_run = gh.post_check_run(check_run)
    job_annotations = {
        "cp2kci-sender": sender,
        "cp2kci-pull-request-number": str(pr["number"]),
        "cp2kci-pull-request-html-url": pr["html_url"],
        "cp2kci-check-run-url": check_run["url"],
        "cp2kci-check-run-html-url": check_run["html_url"],
        "cp2kci-check-run-status": "queued",
    }
    git_branch = "pull/{}/merge".format(pr["number"])
    kubeutil.submit_run(
        target,
        git_branch,
        pr["merge_commit_sha"],
        job_annotations,
        use_cache=use_cache,
        # priority="high-priority",
    )


# ======================================================================================
def cancel_check_runs(
    target_pattern: TargetName | Literal["*"],
    gh: GithubUtil,
    pr: PullRequest,
    sender: str,
) -> None:
    run_job_list = kubeutil.list_jobs("cp2kci=run")
    for job in run_job_list.items:
        job_annotations = job.metadata.annotations
        if "cp2kci-pull-request-number" not in job_annotations:
            continue
        if int(job_annotations["cp2kci-pull-request-number"]) != pr["number"]:
            continue
        if job_annotations["cp2kci-check-run-status"] != "in_progress":
            continue
        if target_pattern not in ("*", job_annotations["cp2kci-target"]):
            continue

        # Ok found a matching job to cancel.
        print(f"Canceling job {job.metadata.name}.")
        summary = "[Partial Report]({})".format(job_annotations["cp2kci-report-url"])
        summary += f"\n\nCancelled by @{sender}."
        check_run: CheckRun = {
            "url": job_annotations["cp2kci-check-run-url"],
            "status": "completed",
            "conclusion": "cancelled",
            "completed_at": gh.now(),
            "output": {"title": "Cancelled", "summary": summary},
            "actions": build_restart_actions(),
        }
        gh.patch_check_run(check_run)
        kubeutil.delete_job(job.metadata.name)


# ======================================================================================
def submit_dashboard_test(target: Target, head_sha: str, force: bool = False) -> None:
    assert target.repository == "cp2k"

    if not force:
        # Check if a dashboard job for given target is already underway.
        run_job_list = kubeutil.list_jobs("cp2kci=run")
        for job in run_job_list.items:
            if (
                job.metadata.annotations["cp2kci-target"] == target.name
                and "cp2kci-dashboard" in job.metadata.annotations
                and (job.status.active or job.status.completion_time)
            ):
                print(f"Found already underway dashboard job for: {target.name}.")
                return  # Do not submit another job.

        if get_dashboard_report_age(target.name) < timedelta(minutes=10):
            # https://github.com/cp2k/cp2k/blob/c7c47bf/tools/docker/generate_dockerfiles.py#L349
            print(f"Found too recent dashboard report for: {target.name}.")
            return  # Hold off to avoid confusing the report cache.

        if get_dashboard_report_sha(target.name) == head_sha:
            print(f"Found up-to-date dashboard report for: {target.name}.")
            return  # No need to submit another job.

        if target.cache_from:
            if get_dashboard_report_sha(target.cache_from) != head_sha:
                print(f"Found stale cache_from dashboard report for: {target.name}.")
                return  # Won't submit a job without up-to-date cache_from image.

    # Finally submit a new job.
    job_annotations = {"cp2kci-dashboard": "yes"}
    if force:
        job_annotations["cp2kci-force"] = "yes"
    kubeutil.submit_run(target, "master", head_sha, job_annotations)


# ======================================================================================
def get_dashboard_report_age(target_name: TargetName) -> datetime:
    assert target_name.startswith("cp2k-")
    test_name = target_name[5:]
    blob = output_bucket.get_blob("dashboard_" + test_name + "_report.txt")
    if blob:
        return datetime.now(timezone.utc) - blob.updated
    return timedelta.max  # Blob not found.


# ======================================================================================
def get_dashboard_report_sha(target_name: TargetName) -> Optional[str]:
    assert target_name.startswith("cp2k-")
    test_name = target_name[5:]

    # Downloading first 1kb of report should be enough to read CommitSHA.
    blob = output_bucket.get_blob("dashboard_" + test_name + "_report.txt")
    if blob:
        # We only download the first 1024 bytes which might break a unicode character.
        report = blob.download_as_string(end=1024).decode("utf8", errors="replace")
        m = re.search("(^|\n)CommitSHA: (\w{40})\n", report)
        if m:
            return str(m.group(2))

    return None  # Blob or CommitSHA not found.


# ======================================================================================
def poll_pull_requests(job_list: V1JobList) -> None:
    """A save guard in case we're missing a callback or loosing BatchJob"""

    active_check_runs_urls = []
    for job in job_list.items:
        annotations = job.metadata.annotations
        if job.status.active and "cp2kci-check-run-url" in annotations:
            active_check_runs_urls.append(annotations["cp2kci-check-run-url"])

    for repo_config in REPOSITORY_CONFIGS:
        gh = GithubUtil(repo_config.name)
        for pr in gh.iterate_pull_requests():
            if pr["base"]["ref"] != "master":
                continue  # ignore non-master PR
            head_sha = pr["head"]["sha"]

            check_runs = list(gh.iterate_check_runs(f"/commits/{head_sha}/check-runs"))
            for check_run in check_runs:
                if check_run["status"] == "completed":
                    continue  # Good, check_run is completed.
                if check_run["url"] in active_check_runs_urls:
                    continue  # Good, there is still an active BatchJob.
                if gh.age(check_run["started_at"]) < timedelta(minutes=3):
                    continue  # It's still young - wait a bit.

                print("Found forgotten check_run: {}".format(check_run["url"]))
                title = "Something in the CI system went wrong :-("
                summary = "Common reasons are:\n"
                summary += " - Busy cloud: many preemptions\n"
                summary += " - Busy CI: long queuing\n"
                summary += " - Download problems\n"
                match = re.search(
                    r"\[.*report.*\]\((.*?)\)",
                    str(check_run["output"]["summary"]),
                    re.I,
                )
                if match:
                    summary += "\n\n[Partial Report]({})".format(match.group(1))
                check_run["conclusion"] = "failure"
                check_run["completed_at"] = gh.now()
                check_run["output"] = {"title": title, "summary": summary}
                check_run["actions"] = [
                    {
                        "label": "Restart",
                        "identifier": "run",
                        "description": "Trigger test run.",
                    }
                ]
                gh.patch_check_run(check_run)

            # Check for forgotten pull requests.
            pr_is_old = gh.age(pr["created_at"]) > timedelta(minutes=3)
            if pr_is_old and not check_runs:
                print("Found forgotten PR: {}".format(pr["number"]))
                process_pull_request(gh, pr["number"], pr["user"]["login"])


# ======================================================================================
def publish_job_to_dashboard(job: V1Job) -> None:
    job_annotations = job.metadata.annotations
    if job.status.completion_time is None:
        return

    if "cp2kci-dashboard-published" in job_annotations:
        return

    target_name = job_annotations["cp2kci-target"]
    print(f"Publishing {target_name} to dashboard.")

    assert target_name.startswith("cp2k-")
    test_name = target_name[5:]

    src_blob = output_bucket.blob(job_annotations["cp2kci-report-path"])
    if src_blob.exists():
        dest_blob = output_bucket.blob("dashboard_" + test_name + "_report.txt")
        dest_blob.rewrite(src_blob)

    src_blob = output_bucket.blob(job_annotations["cp2kci-artifacts-path"])
    if src_blob.exists():
        dest_blob = output_bucket.blob("dashboard_" + test_name + "_artifacts.zip")
        dest_blob.rewrite(src_blob)

    # update job_annotations
    job_annotations["cp2kci-dashboard-published"] = "yes"
    kubeutil.patch_job_annotations(job.metadata.name, job_annotations)


# ======================================================================================
def build_restart_actions() -> List[CheckRunAction]:
    return [
        {
            "label": "Restart",
            "identifier": "run",
            "description": "Trigger test run.",
        },
        {
            "label": "Restart w/o Cache",
            "identifier": "run_nocache",
            "description": "Trigger test run without build cache.",
        },
    ]


# ======================================================================================
def publish_job_to_github(job: V1Job) -> None:
    status = "queued"
    if job.status.active:
        status = "in_progress"
    elif job.status.completion_time:
        status = "completed"

    # failed jobs are handled by poll_pull_requests()

    job_annotations = job.metadata.annotations
    if job_annotations["cp2kci-check-run-status"] == status:
        return  # Nothing to do - check_run already uptodate.

    target_name = job_annotations["cp2kci-target"]
    print(f"Publishing {target_name} to Github.")

    gh = GithubUtil(job_annotations["cp2kci-repository"])
    report_blob = output_bucket.blob(job_annotations["cp2kci-report-path"])
    check_run: CheckRun = {"status": status, "output": {}}
    if status == "completed":
        report = parse_report(report_blob)
        check_run["conclusion"] = "success" if report.status == "OK" else "failure"
        check_run["completed_at"] = gh.now()
        check_run["actions"] = build_restart_actions()
        check_run["output"]["title"] = report.summary
        summary = f"[Detailed Report]({report_blob.public_url})"
        # Did the run upload artifacts?
        artifacts_path = job_annotations["cp2kci-artifacts-path"]
        artifacts_blob = output_bucket.get_blob(artifacts_path)
        if artifacts_blob:
            size_mib = artifacts_blob.size / 1024 / 1024
            download_url = artifacts_blob.public_url
            browse_url = f"https://ci.cp2k.org/artifacts/{artifacts_path[:-14]}/"
            summary += f"\n\n[Browse Artifacts]({browse_url})"
            summary += f"\n\n[Download Artifacts ({size_mib:.1f} MiB)]({download_url})"
    else:
        check_run["output"]["title"] = "In Progress..."
        summary = f"[Live Report]({report_blob.public_url}) (updates every 30s)"
        check_run["actions"] = [
            {
                "label": "Cancel",
                "identifier": "cancel",
                "description": "Abort this test run",
            }
        ]

    sender = job_annotations["cp2kci-sender"]
    summary += f"\n\nTriggered by @{sender}."
    check_run["output"]["summary"] = summary

    # update check_run
    check_run["url"] = job_annotations["cp2kci-check-run-url"]
    gh.patch_check_run(check_run)

    # update job_annotations
    job_annotations["cp2kci-check-run-status"] = status
    kubeutil.patch_job_annotations(job.metadata.name, job_annotations)


# ======================================================================================
def parse_report(report_blob: Any) -> Report:
    report = Report(status="UNKNOWN", summary="", git_sha=None)
    try:
        report_txt = report_blob.download_as_string().decode("utf8")
        report.summary = re.findall("(^|\n|\r)Summary: (.+?)[\n\r]", report_txt)[-1][1]
        report.status = re.findall("(^|\n|\r)Status: (.+?)[\n\r]", report_txt)[-1][1]
        report.git_sha = re.findall("(^|\n|\r)CommitSHA: (.+?)[\n\r]", report_txt)[0][1]
        assert report.git_sha and len(report.git_sha) == 40
    except:
        report.summary = "Error while retrieving report."
        print(traceback.format_exc())

    return report


# ======================================================================================
if __name__ == "__main__":
    main()

# EOF
