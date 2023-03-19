#!/usr/bin/python3

# author: Ole Schuett

import os
import json
import hmac
import hashlib
import logging
from flask import Flask, request, abort
from typing import Any

import google.auth  # type: ignore
import google.cloud.pubsub  # type: ignore

publish_client = google.cloud.pubsub.PublisherClient()

app = Flask(__name__)
app.config["GITHUB_WEBHOOK_SECRET"] = os.environ["GITHUB_WEBHOOK_SECRET"]
app.logger.setLevel(logging.INFO)

project = google.auth.default()[1]
pubsub_topic = "projects/" + project + "/topics/cp2kci-topic"

app.logger.info("CP2K-CI frontend is up and running :-)")

# ======================================================================================
@app.route("/health")
def healthz() -> str:
    # TODO: find a way to return queue size or some other end-to-end health metric.
    message_backend(rpc="update_healthz_beacon")
    return "I feel good :-)"


# ======================================================================================
@app.route("/github_app_webhook", methods=["POST"])
def github_app_webhook() -> str:
    # check signature
    ext_signature = request.headers["X-Hub-Signature"]
    secret = app.config["GITHUB_WEBHOOK_SECRET"].encode("utf8")
    my_signature = "sha1=" + hmac.new(secret, request.data, hashlib.sha1).hexdigest()
    if not hmac.compare_digest(my_signature, ext_signature):
        return abort(401, "Signature wrong.")  # access denied

    event = request.headers["X-GitHub-Event"]
    body = request.get_json()
    action = body.get("action", "")
    app.logger.info("Got github even: {} action: {}".format(event, action))

    # Forward everything to the backend.
    message_backend(rpc="github_event", event=event, body=body)
    return "Ok - queued backend task."


# ======================================================================================
def message_backend(**args: Any) -> None:
    data = json.dumps(args).encode("utf8")
    future = publish_client.publish(pubsub_topic, data)
    future.result()


# ======================================================================================
if __name__ == "__main__":
    app.run()

# EOF
