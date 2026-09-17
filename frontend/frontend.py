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
from typing import Any, AsyncGenerator

import jinja2
import psycopg
from psycopg.rows import dict_row
import psycopg_pool

import aiohttp
from aiohttp import web
from aiohttp.typedefs import Handler

import google.auth
import google.cloud.pubsub  # type: ignore

# For debugging fsspec:
# import logging
# logging.basicConfig(level=logging.DEBUG)

publish_client = google.cloud.pubsub.PublisherClient()
project: str = google.auth.default()[1] or ""
pubsub_topic = "projects/" + project + "/topics/cp2kci-topic"

GITHUB_WEBHOOK_SECRET = web.AppKey("github_webhook_secret", str)
CP2KCI_WORKER_SECRET = web.AppKey("cp2kci_worker_secret", str)
DB_CONNECTION_POOL = web.AppKey("db_connection_pool", psycopg_pool.AsyncConnectionPool)


# ======================================================================================
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8888)
    args = parser.parse_args()

    app = web.Application(middlewares=[auth_middleware])
    app[GITHUB_WEBHOOK_SECRET] = os.environ["GITHUB_WEBHOOK_SECRET"]
    app[CP2KCI_WORKER_SECRET] = os.environ["CP2KCI_WORKER_SECRET"]
    app.cleanup_ctx.append(postgres_ctx)

    # Setup public routes.
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/robots.txt", handle_robots_txt)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/jobs", handle_jobs_dashboard)
    app.router.add_post("/github_app_webhook", handle_github_app_webhook)
    app.router.add_get("/artifacts/{archive:([^/]+)}/{path:(.*)}", handle_artifacts)

    # Setup API routes.
    app.router.add_post("/api/jobs", handle_api_post_job)
    app.router.add_get("/api/jobs/{name:(.*)}", handle_api_get_job)
    app.router.add_patch("/api/jobs/{name:(.*)}", handle_api_patch_job)

    # Start listening for requests.
    print("CP2K-CI frontend is up and running :-)")
    web.run_app(app, port=args.port)


# ======================================================================================
async def postgres_ctx(app: web.Application) -> AsyncGenerator[None, None]:
    print("Opening postgresql connection...")
    async with psycopg_pool.AsyncConnectionPool(min_size=1) as pool:  # uses env vars
        await pool.wait()
        app[DB_CONNECTION_POOL] = pool
        yield


# ======================================================================================
@web.middleware
async def auth_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    # Non-api paths can be accessed without authentication.
    if not request.path.startswith("/api"):
        return await handler(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header == f"Bearer {request.app[CP2KCI_WORKER_SECRET]}":
        request["worker_name"] = request.headers["X-Worker-Name"]
        return await handler(request)

    # Api key missing or invalid.
    print(f"Access denied: {request.method} {request.path_qs}")
    return web.Response(status=403)  # Forbidden


# ======================================================================================
async def handle_favicon(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(path="./favicon.svg")


# ======================================================================================
async def handle_robots_txt(request: web.Request) -> web.Response:
    return web.Response(text="User-agent: *\nDisallow: /\n")


# ======================================================================================
async def handle_health(request: web.Request) -> web.Response:
    # TODO: find a way to return queue size or some other end-to-end health metric.
    message_backend(rpc="update_healthz_beacon")
    return web.Response(text="I feel good :-)")


# ======================================================================================
async def handle_jobs_dashboard(request: web.Request) -> web.Response:
    with open("templates/jobs.html.jinja") as f:
        tmpl = jinja2.Template(f.read())

    async with request.app[DB_CONNECTION_POOL].connection() as db:
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute("""SELECT * FROM jobs
                WHERE finished IS null OR age(now(), created) < INTERVAL '24 hours'
                ORDER BY finished DESC, created DESC""")
            jobs = await cur.fetchall()

    html = tmpl.render(jobs=jobs)
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
async def handle_api_post_job(request: web.Request) -> web.Response:
    body = await request.json()

    # https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS
    async with request.app[DB_CONNECTION_POOL].connection() as db:
        async with db.cursor() as cur:
            for nodepool in body["idle_nodepools"]:
                async with db.transaction():
                    await cur.execute(
                        """SELECT name, spec FROM jobs
                        WHERE state='NEW' AND offloadable AND nodepool=%s
                        ORDER BY priority DESC, jobid LIMIT 1 FOR UPDATE""",
                        (nodepool,),
                    )
                    row = await cur.fetchone()
                    if row:
                        job_name, job_spec = row
                        await cur.execute(
                            "UPDATE jobs SET state='QUEUING', worker=%s WHERE name=%s",
                            (request["worker_name"], job_name),
                        )
                        return web.json_response({"name": job_name, "spec": job_spec})

    return web.Response(status=204)  # No Content


# ======================================================================================
async def handle_api_get_job(request: web.Request) -> web.Response:
    job_name = request.match_info["name"]
    async with request.app[DB_CONNECTION_POOL].connection() as db:
        async with db.cursor() as cur:
            await cur.execute("SELECT state FROM jobs WHERE name=%s", (job_name,))
            row = await cur.fetchone()
            if row is None:
                return web.Response(status=404)  # No Found
            return web.json_response({"name": job_name, "state": row[0]})


# ======================================================================================
async def handle_api_patch_job(request: web.Request) -> web.Response:
    job_name = request.match_info["name"]
    body = await request.json()
    async with request.app[DB_CONNECTION_POOL].connection() as db:
        async with db.cursor() as cur:
            await cur.execute(
                "SELECT state, started, finished FROM jobs WHERE name=%s AND worker=%s",
                (job_name, request["worker_name"]),
            )
            row = await cur.fetchone()
            if row is None:
                return web.Response(status=404)  # No Found
            state, started, finished = row

            if finished is None:  # only modify jobs that haven't finished yet
                await cur.execute(
                    "UPDATE jobs SET updated=now() WHERE name=%s", (job_name,)
                )
                if "state" in body:
                    await cur.execute(
                        "UPDATE jobs SET state=%s WHERE name=%s",
                        (body["state"], job_name),
                    )
                    if body["state"] == "RUNNING" and started is None:
                        await cur.execute(
                            "UPDATE jobs SET started=now() WHERE name=%s", (job_name,)
                        )
                    if body["state"] not in ("NEW", "QUEUING", "RUNNING", "CANCELING"):
                        await cur.execute(
                            "UPDATE jobs SET finished=now() WHERE name=%s", (job_name,)
                        )

            return web.Response(status=204)  # No Content


# ======================================================================================
if __name__ == "__main__":
    main()

# EOF
