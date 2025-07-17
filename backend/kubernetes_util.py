# author: Ole Schuett


from uuid import uuid4
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, cast

from target import Target, TargetName

import kubernetes.config
import kubernetes.client
from kubernetes.client.models.v1_resource_requirements import V1ResourceRequirements
from kubernetes.client.models.v1_affinity import V1Affinity
from kubernetes.client.models.v1_job_list import V1JobList

import google.auth.transport.requests
import google.auth.compute_engine


class KubernetesUtil:
    def __init__(
        self,
        output_bucket: Any,
        image_base: str,
        namespace: str = "default",
    ):
        try:
            kubernetes.config.load_kube_config()
        except Exception:
            kubernetes.config.load_incluster_config()
        self.timeout = 3  # seconds
        self.output_bucket = output_bucket
        self.image_base = image_base
        self.namespace = namespace
        self.api = kubernetes.client
        self.batch_api = kubernetes.client.BatchV1Api()

    # --------------------------------------------------------------------------
    def get_upload_url(
        self, path: str, content_type: str = "text/plain;charset=utf-8"
    ) -> str:
        # Get credentials.
        credentials, _ = google.auth.default()
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)
        signing_credentials = google.auth.compute_engine.IDTokenCredentials(
            request=auth_request,
            target_audience="",
            service_account_email="cp2kci-backend@cp2k-org-project.iam.gserviceaccount.com",
        )
        # Sign the URL.
        blob = self.output_bucket.blob(path)
        upload_url = blob.generate_signed_url(
            expiration=datetime.utcnow() + timedelta(hours=12),
            method="PUT",
            content_type=content_type,
            credentials=signing_credentials,
            version="v4",
        )
        return str(upload_url)

    # --------------------------------------------------------------------------
    def list_jobs(self, selector: str) -> V1JobList:
        job_list = self.batch_api.list_namespaced_job(
            self.namespace, label_selector=selector, _request_timeout=self.timeout
        )  # type: ignore
        return cast(V1JobList, job_list)

    # --------------------------------------------------------------------------
    def delete_job(self, job_name: str) -> None:
        print("deleting job: " + job_name)
        self.batch_api.delete_namespaced_job(
            job_name,
            self.namespace,
            propagation_policy="Background",
            _request_timeout=self.timeout,
        )  # type: ignore

    # --------------------------------------------------------------------------
    def patch_job_annotations(
        self, job_name: str, new_annotations: Dict[str, str]
    ) -> None:
        new_job_metadata = self.api.V1ObjectMeta(annotations=new_annotations)
        new_job = self.api.V1Job(metadata=new_job_metadata)
        self.batch_api.patch_namespaced_job(
            job_name, self.namespace, new_job, _request_timeout=self.timeout
        )  # type: ignore

        # also update annotations of report_blob
        report_blob = self.output_bucket.blob(new_annotations["cp2kci-report-path"])
        if report_blob.exists():
            report_blob.metadata = new_annotations
            report_blob.patch()

    # --------------------------------------------------------------------------
    def resources(self, target: Target) -> V1ResourceRequirements:
        req_cpu = 0.9 * target.cpu  # Request 10% less to leave some for kubernetes.
        return self.api.V1ResourceRequirements(
            requests={"cpu": str(req_cpu)}, limits={"nvidia.com/gpu": str(target.gpu)}
        )

    # --------------------------------------------------------------------------
    def affinity(self, target: Target) -> V1Affinity:
        requirement = self.api.V1NodeSelectorRequirement(
            key="cloud.google.com/gke-nodepool", operator="In", values=target.nodepools
        )
        term = self.api.V1NodeSelectorTerm(match_expressions=[requirement])
        selector = self.api.V1NodeSelector([term])
        node_affinity = self.api.V1NodeAffinity(
            required_during_scheduling_ignored_during_execution=selector
        )
        return self.api.V1Affinity(node_affinity=node_affinity)

    # --------------------------------------------------------------------------
    def submit_run(
        self,
        target: Target,
        git_branch: str,
        git_ref: str,
        job_annotations: Dict[str, str],
        use_cache: bool = True,
        priority: Optional[str] = None,
    ) -> None:
        print(f"Submitting run for target: {target.name}.")

        short_uuid = str(uuid4())[:8]
        job_name = f"run-{target.name}-{short_uuid}"
        report_path = f"{job_name}_report.txt"
        artifacts_path = f"{job_name}_artifacts.zip"

        # upload waiting message
        report_blob = self.output_bucket.blob(report_path)
        assert not report_blob.exists()
        report_blob.cache_control = "no-cache"
        report_blob.upload_from_string("Report not yet available.")

        # amend job annotations
        job_annotations["cp2kci-target"] = target.name
        job_annotations["cp2kci-repository"] = target.repository
        job_annotations["cp2kci-report-path"] = report_path
        job_annotations["cp2kci-report-url"] = report_blob.public_url
        job_annotations["cp2kci-artifacts-path"] = artifacts_path

        # publish job annotations also to report blob
        report_blob.metadata = job_annotations
        report_blob.patch()

        # environment variables
        env_vars: Dict[str, str] = {}
        env_vars["TARGET"] = target.name
        env_vars["GIT_BRANCH"] = git_branch
        env_vars["GIT_REF"] = git_ref
        env_vars["GIT_REPO"] = target.repository
        env_vars["REPORT_UPLOAD_URL"] = self.get_upload_url(report_path)
        env_vars["ARTIFACTS_UPLOAD_URL"] = self.get_upload_url(
            artifacts_path, content_type="application/zip"
        )

        if target.runner == "remote":
            env_vars["REMOTE_HOST"] = target.remote_host
            env_vars["REMOTE_CMD"] = target.remote_cmd
        elif target.runner == "cscs":
            env_vars["CSCS_PIPELINE"] = target.cscs_pipeline
        elif target.runner == "local":
            env_vars["DOCKERFILE"] = target.dockerfile
            env_vars["BUILD_PATH"] = target.build_path
            build_args = f"{target.build_args} GIT_COMMIT_SHA={git_ref} SPACK_CACHE=gs://cp2k-spack-cache"
            env_vars["BUILD_ARGS"] = build_args.strip()
            env_vars["USE_CACHE"] = "yes" if use_cache else "no"
            env_vars["CACHE_FROM"] = target.cache_from
            env_vars["NUM_GPUS_REQUIRED"] = str(target.gpu)

        # volumens
        volumes = []
        volume_mounts = []

        # docker volume (needed for performance)
        if target.runner == "local":
            docker_volname = "volume-docker-" + job_name
            docker_volsrc = self.api.V1EmptyDirVolumeSource()
            volumes.append(
                self.api.V1Volume(name=docker_volname, empty_dir=docker_volsrc)
            )
            volume_mounts.append(
                self.api.V1VolumeMount(
                    name=docker_volname, mount_path="/var/lib/docker"
                )
            )

        # ssh secret volume
        if target.runner == "remote":
            ssh_secret_volname = "ssh-config-volume"
            ssh_secret_volsrc = self.api.V1SecretVolumeSource(
                secret_name="ssh-config", default_mode=0o0600
            )
            volumes.append(
                self.api.V1Volume(name=ssh_secret_volname, secret=ssh_secret_volsrc)
            )
            volume_mounts.append(
                self.api.V1VolumeMount(
                    name=ssh_secret_volname, mount_path="/root/.ssh", read_only=True
                )
            )

        # cscs-ci secret volume
        if target.runner == "cscs":
            cscs_secret_volname = "cscs-ci-volume"
            cscs_secret_volsrc = self.api.V1SecretVolumeSource(
                secret_name="cscs-ci", default_mode=0o0600
            )
            volumes.append(
                self.api.V1Volume(name=cscs_secret_volname, secret=cscs_secret_volsrc)
            )
            volume_mounts.append(
                self.api.V1VolumeMount(
                    name=cscs_secret_volname,
                    mount_path="/var/secrets/cscs-ci",
                    read_only=True,
                )
            )

        # container with privileged=True as needed by docker build
        privileged = self.api.V1SecurityContext(privileged=True)
        k8s_env_vars = [self.api.V1EnvVar(k, v) for k, v in env_vars.items()]
        container = self.api.V1Container(
            name="main",
            image=f"{self.image_base}/img_cp2kci_toolbox_{target.arch}:latest",
            resources=self.resources(target),
            command=[f"./run_{target.runner}_target.sh"],
            volume_mounts=volume_mounts,
            security_context=privileged,
            env=k8s_env_vars,
        )

        # tolerations
        tol_costly = self.api.V1Toleration(key="costly", operator="Exists")
        tol_arch = self.api.V1Toleration(key="kubernetes.io/arch", value=target.arch)

        # pod
        pod_spec = self.api.V1PodSpec(
            containers=[container],
            volumes=volumes,
            tolerations=[tol_costly, tol_arch],
            termination_grace_period_seconds=0,
            restart_policy="OnFailure",  # https://github.com/kubernetes/kubernetes/issues/79398
            dns_policy="Default",  # bypass kube-dns
            affinity=self.affinity(target),
            automount_service_account_token=False,
            service_account_name="cp2kci-runner-k8s-account",
            priority_class_name=priority,
        )
        pod_template = self.api.V1PodTemplateSpec(spec=pod_spec)

        # job metadata
        job_metadata = self.api.V1ObjectMeta(
            name=job_name, labels={"cp2kci": "run"}, annotations=job_annotations
        )

        # job
        job_spec = self.api.V1JobSpec(
            template=pod_template, backoff_limit=6, active_deadline_seconds=10800
        )  # 3 hours
        job = self.api.V1Job(spec=job_spec, metadata=job_metadata)
        self.batch_api.create_namespaced_job(
            self.namespace, body=job, _request_timeout=self.timeout
        )  # type: ignore


# EOF
