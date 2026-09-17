# author: Ole Schuett


import json
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List, TypedDict

from target import Target, TargetName

import psycopg
import google.auth.transport.requests
import google.auth.compute_engine

# ======================================================================================
JobAnnotations = TypedDict(
    "JobAnnotations",
    {
        "cp2kci-repository": str,
        "cp2kci-target": str,
        "cp2kci-sender": str,
        "cp2kci-force": str,
        "cp2kci-dashboard": str,
        "cp2kci-check-run-url": str,
        "cp2kci-started": str,
        "cp2kci-updated": str,
        "cp2kci-submitted": str,
        "cp2kci-report-url": str,
        "cp2kci-report-path": str,
        "cp2kci-artifacts-path": str,
        "cp2kci-check-run-status": str,
        "cp2kci-check-run-html-url": str,
        "cp2kci-pull-request-number": str,
        "cp2kci-pull-request-html-url": str,
        "cp2kci-dashboard-published": str,
    },
    total=False,
)

# ======================================================================================
JobSpec = TypedDict(
    "JobSpec",
    {
        "target_name": str,
        "target_type": str,  # Literal["local", "remote", "cscs"],
        "git_branch": str,
        "git_ref": str,
        "git_repo": str,
        "report_upload_url": str,
        "artifacts_upload_url": str,
        "nodepool": str,
        "arch": str,  # Literal["x86", "arm64"],
        "cpu": float,
        "gpu": int,
        "use_cache": bool,
        "cache_from": str,
        "remote_host": str,
        "remote_cmd": str,
        "cscs_pipeline": str,
        "dockerfile": str,
        "build_path": str,
        "build_args": str,
    },
    total=False,
)


# ======================================================================================
class Job:
    def __init__(self, name: str, state: str, annotations: JobAnnotations):
        self.name = name
        self.state = state
        self.annotations = annotations
        self.is_active = state in ("NEW", "QUEUING", "RUNNING")


# ======================================================================================
class JobsUtil:
    def __init__(self, output_bucket: Any):
        self.output_bucket = output_bucket

        # https://docs.cloud.google.com/sql/docs/postgres/iam-logins#cloud-sql-auth-proxy
        self.db = psycopg.connect(
            host="127.0.0.1",
            user="cp2kci-backend@cp2k-org-project.iam",
            dbname="cp2k-ci",
            autocommit=True,
        )
        print(f"Opened database connection: {self.db }")

    # ----------------------------------------------------------------------------------
    def get_upload_url(
        self, path: str, content_type: str = "text/plain;charset=utf-8"
    ) -> str:
        # Get credentials.
        credentials, _ = google.auth.default()
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)  # type: ignore
        signing_credentials = google.auth.compute_engine.IDTokenCredentials(
            request=auth_request,
            target_audience="",
            service_account_email="cp2kci-backend@cp2k-org-project.iam.gserviceaccount.com",
        )  # type: ignore
        # Sign the URL.
        blob = self.output_bucket.blob(path)
        upload_url = blob.generate_signed_url(
            expiration=datetime.now(timezone.utc) + timedelta(hours=12),
            method="PUT",
            content_type=content_type,
            credentials=signing_credentials,
            version="v4",
        )
        return str(upload_url)

    # ----------------------------------------------------------------------------------
    def list_jobs(self) -> List[Job]:
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT name, state, annotations FROM jobs
                WHERE finished IS null OR (age(now(), finished) < INTERVAL '3 hours')"""
            )
            jobs = [
                Job(name=row[0], state=row[1], annotations=row[2])
                for row in cur.fetchall()
            ]
        return jobs

    # ----------------------------------------------------------------------------------
    def cancel_job(self, job: Job) -> None:
        if job.state in ("NEW", "QUEUING", "RUNNING"):
            with self.db.cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET state='CANCELING' WHERE name=%s", (job.name,)
                )

    # ----------------------------------------------------------------------------------
    def check_all_job_healths(self) -> None:
        with self.db.cursor() as cur:
            cur.execute("""UPDATE jobs SET state='CANCELED', finished=now()
                            WHERE state='CANCELING' AND worker IS null""")
            cur.execute("""UPDATE jobs SET state='CI_ERROR', finished=now()
                            WHERE state != 'NEW' AND finished IS null
                            AND (age(now(), heartbeat) > INTERVAL '5 minutes')""")
            if cur.rowcount > 0:
                print(f"Watchdog found {cur.rowcount} abandoned job.")

    # ----------------------------------------------------------------------------------
    def patch_job_annotations(
        self, job: Job, partial_annotations: JobAnnotations
    ) -> None:
        new_annotations: JobAnnotations = {**job.annotations}  # copy
        new_annotations.update(partial_annotations)
        new_annotations["cp2kci-updated"] = self.now()

        # also update annotations of report_blob
        report_blob = self.output_bucket.blob(new_annotations["cp2kci-report-path"])
        if report_blob.exists():
            report_blob.metadata = new_annotations
            report_blob.patch()

        # update database
        with self.db.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET annotations=%s WHERE name=%s",
                (json.dumps(new_annotations), job.name),
            )

    # ----------------------------------------------------------------------------------
    def now(self) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    # ----------------------------------------------------------------------------------
    def submit_job(
        self,
        target: Target,
        git_branch: str,
        git_ref: str,
        job_annotations: JobAnnotations,
        use_cache: bool = True,
    ) -> None:
        print(f"Submitting run for target: {target.name}.")

        short_uuid = str(uuid4())[:8]
        job_name = f"{target.name}-{short_uuid}"
        report_path = f"{job_name}_report.txt"
        artifacts_path = f"{job_name}_artifacts.zip"
        report_blob = self.output_bucket.blob(report_path)
        assert not report_blob.exists()

        # amend job annotations
        job_annotations["cp2kci-target"] = target.name
        job_annotations["cp2kci-repository"] = target.repository
        job_annotations["cp2kci-report-path"] = report_path
        job_annotations["cp2kci-report-url"] = report_blob.public_url
        job_annotations["cp2kci-artifacts-path"] = artifacts_path
        job_annotations["cp2kci-submitted"] = self.now()

        # upload waiting message
        report_blob.cache_control = "no-cache"
        report_blob.metadata = job_annotations  # publish job annotations
        report_blob.upload_from_string("Report not yet available.")

        # job spec
        job_spec: JobSpec = {
            "target_name": target.name,
            "target_type": target.runner,
            "git_branch": git_branch,
            "git_ref": git_ref,
            "git_repo": target.repository,
            "report_upload_url": self.get_upload_url(report_path),
            "artifacts_upload_url": self.get_upload_url(
                artifacts_path, content_type="application/zip"
            ),
            "nodepool": target.nodepool,
            "arch": target.arch,
            "cpu": target.cpu,
            "gpu": target.gpu,
            "use_cache": use_cache,
            "cache_from": target.cache_from,
        }

        if target.runner == "remote":
            job_spec["remote_host"] = target.remote_host
            job_spec["remote_cmd"] = target.remote_cmd
        elif target.runner == "cscs":
            job_spec["cscs_pipeline"] = target.cscs_pipeline
        elif target.runner == "local":
            job_spec["dockerfile"] = target.dockerfile
            job_spec["build_path"] = target.build_path
            job_spec["build_args"] = target.build_args + f" GIT_COMMIT_SHA={git_ref}"

        priority = "cp2kci-check-run-url" in job_annotations
        offloadable = target.nodepool in ("pool-main", "pool-perf")

        # insert into database
        with self.db.cursor() as cur:
            cur.execute(
                """INSERT INTO jobs (name, spec, annotations, priority, offloadable, nodepool)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    job_name,
                    json.dumps(job_spec),
                    json.dumps(job_annotations),
                    priority,
                    offloadable,
                    target.nodepool,
                ),
            )


# EOF
