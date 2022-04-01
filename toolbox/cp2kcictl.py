#!/usr/bin/python3

# author: Ole Schuett

import sys
import json
import google.auth
import google.cloud.pubsub

project = google.auth.default()[1]
publish_client = google.cloud.pubsub.PublisherClient()
pubsub_topic = "projects/" + project + "/topics/cp2kci-topic"

# ======================================================================================
def main():
    if len(sys.argv) < 2:
        print_usage()

    rpc = sys.argv[1]
    if rpc == "submit_all_dashboard_tests":
        message_backend(rpc=rpc)

    elif rpc == "submit_dashboard_test":
        target = sys.argv[2]
        message_backend(rpc=rpc, target=target)

    elif rpc == "submit_dashboard_test_force":
        target = sys.argv[2]
        message_backend(rpc=rpc, target=target)

    elif rpc == "process_pull_request":
        repo = sys.argv[2]
        pr_number = int(sys.argv[3])
        message_backend(rpc=rpc, repo=repo, pr_number=pr_number)

    elif rpc == "submit_check_run":
        repo = sys.argv[2]
        pr_number = int(sys.argv[3])
        target = sys.argv[4]
        message_backend(rpc=rpc, repo=repo, pr_number=pr_number, target=target)

    else:
        print("Unknown command: {}\n".format(rpc))
        print_usage()


# ======================================================================================
def print_usage():
    print("Usage: cp2kcictl.py [ submit_check_run <repo> <pr_number> <target> |")
    print("                      process_pull_request <repo> <pr_number> |")
    print("                      submit_dashboard_test <target> |")
    print("                      submit_dashboard_test_force <target> |")
    print("                      submit_all_dashboard_tests ]")
    sys.exit(1)


# ======================================================================================
def message_backend(**args):
    data = json.dumps(args).encode("utf8")
    future = publish_client.publish(pubsub_topic, data)
    message_id = future.result()
    print("Sent message {} to topic {}.".format(message_id, pubsub_topic))


# ======================================================================================
if __name__ == "__main__":
    main()

# EOF
