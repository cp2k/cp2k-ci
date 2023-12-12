#!/usr/bin/python3

# author: Ole Schuett

import os
import json
import hmac
import hashlib
import logging
from flask import Flask, request, abort, Response
import urllib.parse
import mimetypes
import os
import fsspec  # type: ignore
from zipfile import ZipFile
from typing import Any

import google.auth  # type: ignore
import google.cloud.pubsub  # type: ignore

# For debugging fsspec:
# import logging
# logging.basicConfig(level=logging.DEBUG)

publish_client = google.cloud.pubsub.PublisherClient()

app = Flask(__name__)
app.config["GITHUB_WEBHOOK_SECRET"] = os.environ["GITHUB_WEBHOOK_SECRET"]
app.logger.setLevel(logging.INFO)

project = google.auth.default()[1]
pubsub_topic = "projects/" + project + "/topics/cp2kci-topic"

app.logger.info("CP2K-CI frontend is up and running :-)")


# ======================================================================================
@app.route("/robots.txt")
def robots() -> Response:
    return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


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
@app.route("/artifacts/<archive>/")
@app.route("/artifacts/<archive>/<path:path>")
def artifacts(archive: str, path: str = "") -> Response:
    fs = fsspec.filesystem("https")
    archive_quoted = urllib.parse.quote(archive)
    url = f"https://storage.googleapis.com/cp2k-ci/{archive_quoted}_artifacts.zip"
    try:
        with fs.open(url, block_size=512 * 1024) as remote_file:
            # Pre-fetch last 512 KiB as this contains the zip archive's directory.
            pre_fetch = min(512 * 1024, remote_file.size)
            remote_file.seek(-pre_fetch, os.SEEK_END)
            remote_file.read()
            remote_file.seek(0)
            with ZipFile(remote_file) as zip_file:
                return browse_zipfile(zip_file, path)
    except FileNotFoundError:
        return Response("Artifact not found.", status=404)


# ======================================================================================
def browse_zipfile(zip_file: ZipFile, path: str) -> Response:
    filenames = {i.filename for i in zip_file.infolist() if not i.is_dir()}

    if path in filenames:
        mt = mimetypes.guess_type(path, strict=True)[0]
        with zip_file.open(path) as f:
            return Response(f.read(), mimetype=mt)

    if path and not path.endswith("/"):
        return Response("File not found.", status=404)

    candidates = {fn[len(path) :] for fn in filenames if fn.startswith(path)}
    if not candidates:
        return Response("Directory not found", status=404)

    # List directory.
    sub_dirs = {fn.split("/", 1)[0] for fn in candidates if "/" in fn}
    files = {fn for fn in candidates if "/" not in fn}
    title = f"Content of /{path}"
    output = ["<html>"]
    output += [f"<head><title>{title}</title></head>"]
    output += [f"<body><h1>{title}</h1>"]
    output += [f"<ul style='list-style-type:none;padding:10px;'>"]
    if path:
        output += [f"<li><a href='../'>📁 ..<a></li>"]
    for name in sub_dirs:
        output += [f"<li><a href='./{name}/'>📁 {name}/<a></li>"]
    for name in files:
        output += [f"<li><a href='./{name}'>📄 {name}<a></li>"]
    output += [f"</ul>"]
    output += ["</body></html>"]
    return Response("\n".join(output))


# ======================================================================================
if __name__ == "__main__":
    app.run()

# EOF
