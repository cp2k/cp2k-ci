#!/usr/bin/env python3

# author: Ole Schuett

import os
import re
import sys
import time
import pathlib
import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup

CSCS_USERNAME = pathlib.Path("/var/secrets/cscs-ci/username").read_text()
CSCS_PASSWORD = pathlib.Path("/var/secrets/cscs-ci/password").read_text()


# ======================================================================================
def main():
    # Translate GIT_BRANCH to CSCS-CI's ref.
    git_branch = os.environ["GIT_BRANCH"]
    if git_branch == "master":
        cscs_ref = "master"
    elif git_branch.startswith("pull/"):
        pr_number = int(git_branch.split("/")[1])
        cscs_ref = f"pr:{pr_number}"
    else:
        raise Exception("Can't parse GIT_BRANCH")

    cscs_pipeline = os.environ["CSCS_PIPELINE"]
    spec_yaml = f"ref: {cscs_ref}\npipeline: {cscs_pipeline}\n"

    trigger_url = "https://cicd-ext-mw.cscs.ch/ci/pipeline/trigger"
    auth = HTTPBasicAuth(CSCS_USERNAME, CSCS_PASSWORD)
    r = requests.post(trigger_url, auth=auth, data=spec_yaml.encode("utf8"))
    r.raise_for_status()
    req_id = re.search(r"\?reqId=(\w+)", r.text).group(1)

    while True:
        output = []
        trigger_page = requests.get(f"{trigger_url}?reqId={req_id}")
        trigger_page.raise_for_status()
        trigger_json = trigger_page.json()
        print(trigger_json)

        if trigger_json["status"] != "triggered_successfully":
            print(f"Waiting for status to become 'triggered_successfully'...\n")
            time.sleep(5)
            continue

        pipeline_status = trigger_json["pipeline_status"]
        output += [f"Pipeline Status: {pipeline_status}", ""]

        pipeline_html = get_url(trigger_json["url"].replace("&type=gitlab", ""))
        soup = BeautifulSoup(pipeline_html, "html.parser")
        for link in soup.find_all("a"):
            href = link.get("href")
            if href.startswith("/ci/job/result/"):
                bar = "=" * 25
                output += ["", f" {bar} {link.get_text().center(35)} {bar}", ""]
                job_result_html = get_url(f"https://cicd-ext-mw.cscs.ch{href}")
                soup = BeautifulSoup(job_result_html, "html.parser")
                for pre in soup.find_all("pre"):
                    output.append(pre.get_text())

        upload_report("\n".join(output))
        if pipeline_status not in ("created", "pending", "running"):
            sys.exit(0)

        print("Sleeping 30 sec...\n")
        time.sleep(30)


# ======================================================================================
def get_url(url: str):
    r = requests.get(url)
    r.raise_for_status()
    return r.text


# ======================================================================================
def upload_report(content: str):
    url = os.environ["REPORT_UPLOAD_URL"]
    headers = {
        "content-type": "text/plain;charset=utf-8",
        "cache-control": "no-cache",
    }
    r = requests.put(url, headers=headers, data=content.encode("utf8"))
    r.raise_for_status()


# ======================================================================================
main()

# EOF
