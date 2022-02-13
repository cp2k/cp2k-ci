# author: Ole Schuett

import os
import jwt
import requests
from time import time, sleep
from pathlib import Path
from datetime import datetime

GITHUB_APP_ID = os.environ["GITHUB_APP_ID"]
GITHUB_APP_KEY = Path(os.environ["GITHUB_APP_KEY"]).read_text()
GITHUB_APP_INSTALL_ID = os.environ["GITHUB_APP_INSTALL_ID"]


class GithubUtil:
    def __init__(self, repo):
        self.repo = repo
        self.repo_url = "https://api.github.com/repos/cp2k/" + repo
        self.token = self.get_installation_token()

    # --------------------------------------------------------------------------
    def get_master_head_sha(self):
        # Get sha of latest git commit.
        return next(self.iterate("/commits"))["sha"]

    # --------------------------------------------------------------------------
    def get_installation_token(self):
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
        r = self.http_request("POST", url.format(GITHUB_APP_INSTALL_ID), headers)
        return r.json()["token"]

    # --------------------------------------------------------------------------
    def now(self):
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    # --------------------------------------------------------------------------
    def age(self, created_at):
        # TODO: Python 3.7 has datetime.fromisoformat().
        creation = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
        return datetime.utcnow() - creation

    # --------------------------------------------------------------------------
    def http_request(self, method, url, headers, body=None):
        if url.startswith("/"):
            url = self.repo_url + url
        r = requests.request(
            method=method, url=url, headers=headers, json=body, timeout=20
        )
        remaining = r.headers.get("X-RateLimit-Remaining", None)
        if remaining and int(remaining) < 100:
            print("X-RateLimit-Remaining: {}".format(remaining))
        if r.status_code >= 400:
            print(r.text)
        r.raise_for_status()
        return r

    # --------------------------------------------------------------------------
    def authenticated_http_request(self, method, url, body=None, retries=0):
        headers = {
            "Authorization": "token " + self.token,
            "Accept": "application/vnd.github.antiope-preview+json",
        }
        # we get occasional 401 errors https://github.com/cp2k/cp2k-ci/issues/45
        for i in range(retries):
            try:
                return self.http_request(method, url, headers, body)
            except:
                print("Sleeping a bit before retrying...")
                sleep(2)
        return self.http_request(method, url, headers, body)  # final attempt

    # --------------------------------------------------------------------------
    def get(self, url):
        r = self.authenticated_http_request("GET", url, retries=5)
        if "next" in r.links:
            print("Warning: Found unexpected next link at: " + url)
        return r.json()

    # --------------------------------------------------------------------------
    def iterate(self, url):
        r = self.authenticated_http_request("GET", url, retries=5)
        yield from r.json()
        while "next" in r.links:
            url = r.links["next"]["url"]
            r = self.authenticated_http_request("GET", url, retries=5)
            yield from r.json()

    # --------------------------------------------------------------------------
    def post(self, url, body):
        return self.authenticated_http_request("POST", url, body).json()

    # ------------------- -------------------------------------------------------
    def patch(self, url, body):
        return self.authenticated_http_request("PATCH", url, body).json()


# EOF
