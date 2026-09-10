#!/usr/bin/env python3

# author: Ole Schuett

import os
import json
import hmac
import hashlib
import argparse
import urllib.parse
import mimetypes
import fsspec  # type: ignore
from zipfile import ZipFile
from typing import Any

import jinja2
import psycopg2
import psycopg2.extras
import aiohttp
from aiohttp import web

import google.auth
import google.cloud.pubsub  # type: ignore

# For debugging fsspec:
# import logging
# logging.basicConfig(level=logging.DEBUG)

publish_client = google.cloud.pubsub.PublisherClient()
project: str = google.auth.default()[1] or ""
pubsub_topic = "projects/" + project + "/topics/cp2kci-topic"

GITHUB_WEBHOOK_SECRET = web.AppKey("github_webhook_secret", str)


# ======================================================================================
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8888)
    args = parser.parse_args()

    app = web.Application()
    app[GITHUB_WEBHOOK_SECRET] = os.environ["GITHUB_WEBHOOK_SECRET"]

    # Setup routes.
    app.router.add_get("/robots.txt", handle_robots_txt)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/jobs", handle_jobs)
    app.router.add_post("/github_app_webhook", handle_github_app_webhook)
    app.router.add_get("/artifacts/{archive:([^/]+)}/{path:(.*)}", handle_artifacts)

    # Start listening for requests.
    print("CP2K-CI frontend is up and running :-)")
    web.run_app(app, port=args.port)


# ======================================================================================
async def handle_robots_txt(request: web.Request) -> web.Response:
    return web.Response(text="User-agent: *\nDisallow: /\n")


# ======================================================================================
async def handle_health(request: web.Request) -> web.Response:
    # TODO: find a way to return queue size or some other end-to-end health metric.
    message_backend(rpc="update_healthz_beacon")
    return web.Response(text="I feel good :-)")


# ======================================================================================
async def handle_jobs(request: web.Request) -> web.Response:
    with open("templates/jobs.html.jinja") as f:
        tmpl = jinja2.Template(f.read())

    db = psycopg2.connect()  # uses psql environment variables
    db.autocommit = True
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT name, state, spec, annotations, created, started, finished
            FROM jobs WHERE age(now(), created) < INTERVAL '24 hours'
            ORDER BY jobid DESC""")
        jobs = cur.fetchall()

    html = tmpl.render(jobs=jobs)
    db.close()

    return web.Response(text=html, content_type="text/html")


# ======================================================================================
async def handle_github_app_webhook(request: web.Request) -> web.Response:
    # check signature
    ext_signature = request.headers["X-Hub-Signature"]
    secret = request.app[GITHUB_WEBHOOK_SECRET].encode("utf8")
    payload = await request.read()
    my_signature = "sha1=" + hmac.new(secret, payload, hashlib.sha1).hexdigest()
    if not hmac.compare_digest(my_signature, ext_signature):
        return web.Response(text="Signature wrong.", status=401)  # access denied

    event = request.headers["X-GitHub-Event"]
    body = json.loads(payload)
    action = body.get("action", "")
    print("Got github even: {} action: {}".format(event, action))

    # Forward everything to the backend.
    message_backend(rpc="github_event", event=event, body=body)
    return web.Response(text="Ok - queued backend task.")


# ======================================================================================
def message_backend(**args: Any) -> None:
    data = json.dumps(args).encode("utf8")
    future = publish_client.publish(pubsub_topic, data)
    future.result()


# ======================================================================================
async def handle_artifacts(request: web.Request) -> web.Response:
    archive = request.match_info["archive"]
    path = request.match_info.get("path", "")
    fs = fsspec.filesystem("https")
    archive_quoted = urllib.parse.quote(archive)
    url = f"https://storage.googleapis.com/cp2k-ci/{archive_quoted}_artifacts.zip"
    try:
        with fs.open(url, block_size=512 * 1024) as remote_file:
            # Pre-fetch last 512 KiB as this contains the zip archive's directory.
            prefetch = min(512 * 1024, remote_file.size)
            remote_file.seek(-prefetch, os.SEEK_END)
            remote_file.read()
            remote_file.seek(0)
            with ZipFile(remote_file) as zip_file:
                return browse_zipfile(zip_file, path)
    except FileNotFoundError:
        return web.Response(text="Artifact not found.", status=404)


# ======================================================================================
def browse_zipfile(zip_file: ZipFile, path: str) -> web.Response:
    filenames = {i.filename for i in zip_file.infolist() if not i.is_dir()}

    if path in filenames:
        for ext in [".log", ".out", ".inp"]:
            mimetypes.add_type("text/plain", ext)
        mt = mimetypes.guess_type(path)[0]
        with zip_file.open(path) as f:
            return web.Response(body=f.read(), content_type=mt)

    if path and not path.endswith("/"):
        return web.Response(text="File not found.", status=404)

    candidates = {fn[len(path) :] for fn in filenames if fn.startswith(path)}
    if not candidates:
        return web.Response(text="Directory not found", status=404)

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
    return web.Response(text="\n".join(output), content_type="text/html")


# ======================================================================================
if __name__ == "__main__":
    main()

# EOF
