# author: Ole Schuett

import os
import jwt
import requests
from time import time, sleep
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Literal, Optional, TypedDict, cast
from base64 import b64decode

from target import Target, TargetName, parse_target_config
from repository_config import RepositoryConfig, get_repository_config_by_name

GITHUB_APP_ID = os.environ["GITHUB_APP_ID"]
GITHUB_APP_KEY = Path(os.environ["GITHUB_APP_KEY"]).read_text()
GITHUB_APP_INSTALL_ID = os.environ["GITHUB_APP_INSTALL_ID"]

HttpMethods = Literal["GET", "POST", "PATCH"]

# ======================================================================================
class PullRequestNumber(int):
    pass


# ======================================================================================
class CommitSha(str):
    pass


# ======================================================================================
class CheckRunOutput(TypedDict, total=False):
    title: str
    summary: str


# ======================================================================================
class CheckRunAction(TypedDict, total=False):
    label: str
    identifier: str
    description: str


# ======================================================================================
class CheckRunExternalId(str):
    pass


# ======================================================================================
class CheckRun(TypedDict, total=False):
    name: str
    external_id: CheckRunExternalId
    head_sha: CommitSha
    started_at: str
    status: str
    completed_at: str
    conclusion: str
    url: str
    html_url: str
    output: CheckRunOutput
    actions: List[CheckRunAction]


# ======================================================================================
class CheckRunList(TypedDict, total=False):
    check_runs: List[CheckRun]
    total_count: int


# ======================================================================================
class Commit(TypedDict, total=False):
    sha: CommitSha
    url: str
    parents: List[Any]  # Recursive types are not yet supported by MyPy.


# ======================================================================================
class Branch(TypedDict, total=False):
    ref: str


# ======================================================================================
class User(TypedDict, total=False):
    login: str


# ======================================================================================
class PullRequest(TypedDict, total=False):
    number: PullRequestNumber
    head: Commit
    base: Branch
    created_at: str
    commits_url: str
    html_url: str
    mergeable: bool
    merge_commit_sha: CommitSha
    user: User


# ======================================================================================
class Repository(TypedDict, total=False):
    name: str


# ======================================================================================
class CheckSuite(TypedDict, total=False):
    check_runs_url: str


# ======================================================================================
# TODO split into seperate events.
class GithubEvent(TypedDict, total=False):
    name: str
    number: PullRequestNumber
    repository: Repository
    sender: User
    check_suite: CheckSuite
    check_run: CheckRun
    requested_action: CheckRunAction


# ======================================================================================
def assert_check_run_limits(check_run: CheckRun) -> None:
    # Checks the length limits on strings in check run actions.
    for a in check_run.get("actions", []):
        assert len(a["label"]) <= 20 and len(a["identifier"]) <= 20
        assert len(a["description"]) <= 40


# ======================================================================================
class GithubUtil:
    def __init__(self, repo_name: str):
        self.repo_conf = get_repository_config_by_name(repo_name)
        self.repo_url = f"https://api.github.com/repos/cp2k/{repo_name}"
        self.token = self.get_installation_token()

    # --------------------------------------------------------------------------
    def get_master_head_sha(self) -> str:
        # Get sha of latest git commit.
        return str(next(self.iterate_commits("/commits"))["sha"])

    # --------------------------------------------------------------------------
    def get_targets(self, pr: Optional[PullRequest] = None) -> List[Target]:
        branch = f"pull/{pr['number']}/merge" if pr else "master"
        resp = self._get(f"/contents/{self.repo_conf.targets_config}?ref={branch}")
        return parse_target_config(self.repo_conf, b64decode(resp["content"]))

    # --------------------------------------------------------------------------
    def get_target_by_name(
        self, target_name: TargetName, pr: Optional[PullRequest] = None
    ) -> Target:
        matches = [t for t in self.get_targets(pr) if t.name == target_name]
        assert len(matches) == 1
        return matches[0]

    # --------------------------------------------------------------------------
    def get_installation_token(self) -> str:
        # Create App JWT token.
        now = int(time())
        payload = {
            "iat": now,
            "exp": now + 540,  # expiration, stay away from 10min limit
            "iss": GITHUB_APP_ID,
        }
        app_token = jwt.encode(payload, GITHUB_APP_KEY, algorithm="RS256")
        # Setup header for app.
        headers = {
            "Authorization": "Bearer " + app_token,
            "Accept": "application/vnd.github.machine-man-preview+json",
        }
        # Obtain installation access token.
        url = "https://api.github.com/app/installations/{}/access_tokens"
        r = self._http_request("POST", url.format(GITHUB_APP_INSTALL_ID), headers)
        return str(r.json()["token"])

    # --------------------------------------------------------------------------
    def now(self) -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    # --------------------------------------------------------------------------
    def age(self, created_at: str) -> timedelta:
        # TODO: Python 3.11 has datetime.fromisoformat() with support for timezones.
        creation = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
        return datetime.utcnow() - creation

    # --------------------------------------------------------------------------
    def _http_request(
        self, method: HttpMethods, url: str, headers: Dict[str, str], body: Any = None
    ) -> requests.Response:
        if url.startswith("/"):
            url = self.repo_url + url
        r = requests.request(
            method=method, url=url, headers=headers, json=body, timeout=20
        )
        remaining = r.headers.get("X-RateLimit-Remaining", None)
        if remaining and int(remaining) < 100:
            print(f"X-RateLimit-Remaining: {remaining}")
        if r.status_code >= 400:
            print(r.text)
        r.raise_for_status()
        return r

    # --------------------------------------------------------------------------
    def _authenticated_http_request(
        self,
        method: HttpMethods,
        url: str,
        body: Any = None,
        retries: int = 0,
    ) -> requests.Response:
        headers = {
            "Authorization": "token " + self.token,
            "Accept": "application/vnd.github.antiope-preview+json",
        }
        # we get occasional 401 errors https://github.com/cp2k/cp2k-ci/issues/45
        for i in range(retries):
            try:
                return self._http_request(method, url, headers, body)
            except:
                print("Sleeping a bit before retrying...")
                sleep(2)
        return self._http_request(method, url, headers, body)  # final attempt

    # --------------------------------------------------------------------------
    def _get(self, url: str) -> Any:
        r = self._authenticated_http_request("GET", url, retries=5)
        if "next" in r.links:
            print("Warning: Found unexpected next link at: " + url)
        return r.json()

    # --------------------------------------------------------------------------
    def _iterate(self, url: str) -> Iterator[Any]:
        r = self._authenticated_http_request("GET", url, retries=5)
        yield from r.json()
        while "next" in r.links:
            url = r.links["next"]["url"]
            r = self._authenticated_http_request("GET", url, retries=5)
            yield from r.json()

    # --------------------------------------------------------------------------
    def _post(self, url: str, body: Any) -> Any:
        return self._authenticated_http_request("POST", url, body).json()

    # ------------------- -------------------------------------------------------
    def _patch(self, url: str, body: Any) -> Any:
        return self._authenticated_http_request("PATCH", url, body).json()

    # --------------------------------------------------------------------------
    def get_pull_request(self, pr_number: PullRequestNumber) -> PullRequest:
        pr = self._get(f"/pulls/{pr_number}")
        return cast(PullRequest, pr)

    # --------------------------------------------------------------------------
    def get_commit(self, sha: CommitSha) -> Commit:
        commit = self._get(f"/commits/{sha}")
        return cast(Commit, commit)

    # --------------------------------------------------------------------------
    def get_check_runs(self, url: str) -> CheckRunList:
        check_run_list = self._get(url)
        return cast(CheckRunList, check_run_list)

    # --------------------------------------------------------------------------
    def post_check_run(self, check_run: CheckRun) -> CheckRun:
        assert_check_run_limits(check_run)
        new_check_run = self._post("/check-runs", check_run)
        return cast(CheckRun, new_check_run)

    # --------------------------------------------------------------------------
    def patch_check_run(self, check_run: CheckRun) -> None:
        assert_check_run_limits(check_run)
        self._patch(check_run["url"], check_run)

    # --------------------------------------------------------------------------
    def iterate_commits(self, url: str) -> Iterator[Commit]:
        commit_iterator = self._iterate(url)
        return cast(Iterator[Commit], commit_iterator)

    # --------------------------------------------------------------------------
    def iterate_pull_requests(self) -> Iterator[PullRequest]:
        pr_iterator = self._iterate("/pulls")
        return cast(Iterator[PullRequest], pr_iterator)


# EOF
