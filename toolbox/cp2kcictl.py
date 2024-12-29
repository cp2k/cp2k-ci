#!/usr/bin/python3

# author: Ole Schuett

import sys
import json
from typing import Any

import google.auth  # type: ignore
import google.cloud.pubsub  # type: ignore

project = google.auth.default()[1]
publish_client = google.cloud.pubsub.PublisherClient()
pubsub_topic = "projects/" + project + "/topics/cp2kci-topic"


# ======================================================================================
def main() -> None:
    if len(sys.argv) < 2:
        print_usage()

    rpc = sys.argv[1]
    if rpc == "submit_all_dashboard_tests":
        message_backend(rpc=rpc)

    elif rpc == "submit_tagged_dashboard_tests":
        tag = sys.argv[2]
        message_backend(rpc=rpc, tag=tag)

    elif rpc in ("submit_dashboard_test", "submit_dashboard_test_force"):
        target = sys.argv[2]
        message_backend(rpc=rpc, target=target)

    elif rpc == "process_pull_request":
        repo = sys.argv[2]
        pr_number = int(sys.argv[3])
        message_backend(rpc=rpc, repo=repo, pr_number=pr_number)

    elif rpc in ("submit_check_run", "submit_check_run_nocache"):
        repo = sys.argv[2]
        pr_number = int(sys.argv[3])
        target = sys.argv[4]
        message_backend(rpc=rpc, repo=repo, pr_number=pr_number, target=target)

    else:
        print("Unknown command: {}\n".format(rpc))
        print_usage()


# ======================================================================================
def print_usage() -> None:
    print("Usage: cp2kcictl.py [ submit_check_run <repo> <pr> <target> |")
    print("                      submit_check_run_nocache <repo> <pr> <target> |")
    print("                      process_pull_request <repo> <pr> |")
    print("                      submit_dashboard_test <target> |")
    print("                      submit_dashboard_test_force <target> |")
    print("                      submit_tagged_dashboard_tests <tag> |")
    print("                      submit_all_dashboard_tests ]")
    sys.exit(1)


# ======================================================================================
def message_backend(**args: Any) -> None:
    data = json.dumps(args).encode("utf8")
    future = publish_client.publish(pubsub_topic, data)
    message_id = future.result()
    print("Sent message {} to topic {}.".format(message_id, pubsub_topic))


# ======================================================================================
if __name__ == "__main__":
    main()

# EOF
