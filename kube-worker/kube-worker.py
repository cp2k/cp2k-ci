#!/usr/bin/env python3

# author: Ole Schuett

import traceback
import itertools
from time import sleep
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Literal, TypedDict

import psycopg2

import kubernetes.config
import kubernetes.client
from kubernetes.client.models.v1_pod import V1Pod
from kubernetes.client.models.v1_volume import V1Volume
from kubernetes.client.models.v1_env_var import V1EnvVar
from kubernetes.client.models.v1_pod_spec import V1PodSpec
from kubernetes.client.models.v1_container import V1Container
from kubernetes.client.models.v1_toleration import V1Toleration
from kubernetes.client.models.v1_object_meta import V1ObjectMeta
from kubernetes.client.models.v1_security_context import V1SecurityContext
from kubernetes.client.models.v1_resource_requirements import V1ResourceRequirements
from kubernetes.client.models.v1_volume_mount import V1VolumeMount
from kubernetes.client.models.v1_secret_volume_source import V1SecretVolumeSource
from kubernetes.client.models.v1_empty_dir_volume_source import V1EmptyDirVolumeSource
from kubernetes.client.models.v1_affinity import V1Affinity
from kubernetes.client.models.v1_node_selector import V1NodeSelector
from kubernetes.client.models.v1_node_affinity import V1NodeAffinity
from kubernetes.client.models.v1_node_selector_term import V1NodeSelectorTerm
from kubernetes.client.models.v1_node_selector_requirement import (
    V1NodeSelectorRequirement,
)

DbConnection = psycopg2._psycopg.connection
KubeClient = kubernetes.client.CoreV1Api

K8S_NAMESPACE = "default"
K8S_TIMEOUT = 3  # seconds
CONTAINER_IMAGE_BASE = f"us-central1-docker.pkg.dev/cp2k-org-project/cp2kci"


# ======================================================================================
def main() -> None:
    try:
        kubernetes.config.load_kube_config()
    except Exception:
        kubernetes.config.load_incluster_config()

    kube = kubernetes.client.CoreV1Api()

    # https://docs.cloud.google.com/sql/docs/postgres/iam-logins#cloud-sql-auth-proxy
    db = psycopg2.connect(
        host="127.0.0.1",
        user="cp2kci-backend@cp2k-org-project.iam",
        dbname="cp2k-ci",
    )
    db.autocommit = True
    print(f"Opened database connection: {db}")

    print("Starting main loop.")
    for i in itertools.count():
        try:
            process_new(db, kube)
            process_active(db, kube)
        except:
            print(traceback.format_exc())
        sleep(5)


# ======================================================================================
def process_new(db: DbConnection, kube: KubeClient) -> None:
    # Get all new jobs from database.
    with db.cursor() as cur:
        cur.execute(
            """SELECT name, spec, annotations FROM jobs WHERE jobs.state='NEW'"""
        )
        rows = cur.fetchall()

    # Create corresponding kubernetes pods.
    for row in rows:
        jobname, jobspec, annotations = row
        create_pod(kube=kube, jobname=jobname, jobspec=jobspec, annotations=annotations)
        update_job_state(db, jobname=row[0], state="QUEUING")


# ======================================================================================
def process_active(db: DbConnection, kube: KubeClient) -> None:
    # Get status of all active jobs from database.
    with db.cursor() as cur:
        cur.execute("""SELECT name, state FROM jobs
            WHERE state IN ('NEW', 'QUEUING', 'RUNNING', 'CANCELING')""")
        db_states: Dict[str, str] = {row[0]: row[1] for row in cur.fetchall()}

    # Get all relevant pods from kubernetes.
    pod_list = kube.list_namespaced_pod(  # type: ignore
        namespace=K8S_NAMESPACE,
        label_selector="cp2kci=run",
        _request_timeout=K8S_TIMEOUT,
    )

    # Get status of all kubernetes pods.
    kube_states: Dict[str, str] = {}
    for pod in pod_list.items:
        jobname = pod.metadata.name
        phase = pod.status.phase

        # Translate pod phase to job status.
        if phase == "Pending":
            kube_states[jobname] = "QUEUING"
        elif phase == "Running":
            kube_states[jobname] = "RUNNING"
        elif phase == "Succeeded":
            kube_states[jobname] = "SUCCEEDED"
        elif phase == "Failed":
            kube_states[jobname] = "FAILED"
        else:  # Unknown
            kube_states[jobname] = "QUEUING"

        # Check for timeout.
        if pod.status.reason == "DeadlineExceeded":
            kube_states[jobname] = "TIMEOUT"

        # Check for out of memory.
        for container in pod.status.container_statuses or []:
            if container.state.terminated:
                if container.state.terminated.reason == "OOMKilled":
                    kube_states[jobname] = "OUT_OF_MEMORY"

        # Check for preemption.
        pod_status_message = pod.status.message or ""
        if "terminated in response to imminent node shutdown" in pod_status_message:
            kube_states[jobname] = "PREEMPTED"

    # Compare states from database and kubernetes.
    for jobname in sorted(set(db_states.keys()) | set(kube_states.keys())):
        if jobname not in kube_states:
            if db_states[jobname] == "CANCELING":
                update_job_state(db, jobname, "CANCELED", finished=True)
            else:
                print(f"Found orphan job {jobname} in state {db_states[jobname]}.")
                update_job_state(db, jobname, "FAILED", finished=True)

        elif jobname not in db_states:
            continue  # Ignore leftover kubernetes jobs.

        elif db_states[jobname] == "CANCELING":
            print(f"Removing canceled pod {jobname}.")
            delete_pod(kube, jobname)

        elif db_states[jobname] != kube_states[jobname]:
            if kube_states[jobname] == "QUEUING":
                update_job_state(db, jobname, "QUEUING")
            elif kube_states[jobname] == "RUNNING":
                update_job_state(db, jobname, "RUNNING", started=True)
            else:
                update_job_state(db, jobname, kube_states[jobname], finished=True)

    # Remove successful pods, others will get garbage collected by kubernetes eventually.
    # https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-garbage-collection
    for jobname, state in kube_states.items():
        if state == "SUCCEEDED":
            print(f"Removing successful pod {jobname}.")
            delete_pod(kube, jobname)


# ======================================================================================
def delete_pod(kube: KubeClient, jobname: str) -> None:
    pod_list = kube.delete_namespaced_pod(  # type: ignore
        name=jobname,
        namespace=K8S_NAMESPACE,
        _request_timeout=K8S_TIMEOUT,
    )


# ======================================================================================
def update_job_state(
    db: DbConnection,
    jobname: str,
    state: str,
    started: Optional[bool] = False,
    finished: Optional[bool] = False,
) -> None:
    pass
    now = datetime.now(timezone.utc)
    if started:
        with db.cursor() as cur:
            cur.execute("UPDATE jobs SET started=%s WHERE name=%s", (now, jobname))
    if finished:
        with db.cursor() as cur:
            cur.execute("UPDATE jobs SET finished=%s WHERE name=%s", (now, jobname))

    print(f"Updating status of job {jobname} to {state}.")
    with db.cursor() as cur:
        cur.execute("UPDATE jobs SET state=%s WHERE name=%s", (state, jobname))


# ======================================================================================
def create_pod(
    kube: KubeClient,
    jobname: str,
    jobspec: Dict[str, Any],
    annotations: Dict[str, str],
) -> None:
    print(f"Creating pod for target: {jobspec["target_name"]}.")

    # environment variables
    env_vars: Dict[str, str] = {}
    env_vars["TARGET"] = jobspec["target_name"]
    env_vars["GIT_BRANCH"] = jobspec["git_branch"]
    env_vars["GIT_REF"] = jobspec["git_ref"]
    env_vars["GIT_REPO"] = jobspec["git_repo"]
    env_vars["REPORT_UPLOAD_URL"] = jobspec["report_upload_url"]
    env_vars["ARTIFACTS_UPLOAD_URL"] = jobspec["artifacts_upload_url"]

    if jobspec["target_type"] == "remote":
        env_vars["REMOTE_HOST"] = jobspec["remote_host"]
        env_vars["REMOTE_CMD"] = jobspec["remote_cmd"]
    elif jobspec["target_type"] == "cscs":
        env_vars["CSCS_PIPELINE"] = jobspec["cscs_pipeline"]
    elif jobspec["target_type"] == "local":
        env_vars["DOCKERFILE"] = jobspec["dockerfile"]
        env_vars["BUILD_PATH"] = jobspec["build_path"]
        env_vars["BUILD_ARGS"] = jobspec["build_args"]
        if jobspec["use_cache"]:
            env_vars["BUILD_ARGS"] += " SPACK_CACHE=gs://cp2k-spack-cache"
        env_vars["USE_CACHE"] = "yes" if jobspec["use_cache"] else "no"
        env_vars["CACHE_FROM"] = jobspec["cache_from"]
        env_vars["NUM_GPUS_REQUIRED"] = str(jobspec["gpu"])

    # volumens
    volumes = []
    volume_mounts = []

    # docker volume (needed for performance)
    if jobspec["target_type"] == "local":
        docker_volname = "volume-docker-" + jobname
        docker_volsrc = V1EmptyDirVolumeSource()
        volumes.append(V1Volume(name=docker_volname, empty_dir=docker_volsrc))
        volume_mounts.append(
            V1VolumeMount(name=docker_volname, mount_path="/var/lib/docker")
        )

    # ssh secret volume
    if jobspec["target_type"] == "remote":
        ssh_secret_volname = "ssh-config-volume"
        ssh_secret_volsrc = V1SecretVolumeSource(
            secret_name="ssh-config", default_mode=0o0600
        )
        volumes.append(V1Volume(name=ssh_secret_volname, secret=ssh_secret_volsrc))
        volume_mounts.append(
            V1VolumeMount(
                name=ssh_secret_volname, mount_path="/root/.ssh", read_only=True
            )
        )

    # cscs-ci secret volume
    if jobspec["target_type"] == "cscs":
        cscs_secret_volname = "cscs-ci-volume"
        cscs_secret_volsrc = V1SecretVolumeSource(
            secret_name="cscs-ci", default_mode=0o0600
        )
        volumes.append(V1Volume(name=cscs_secret_volname, secret=cscs_secret_volsrc))
        volume_mounts.append(
            V1VolumeMount(
                name=cscs_secret_volname,
                mount_path="/var/secrets/cscs-ci",
                read_only=True,
            )
        )

    # resources
    resources = V1ResourceRequirements(
        requests={"cpu": str(0.9 * jobspec["cpu"])},  # leave 10% for kubernetes
        limits={"nvidia.com/gpu": str(jobspec["gpu"])},
    )

    # container with privileged=True as needed by docker build
    privileged = V1SecurityContext(privileged=True)
    k8s_env_vars = [V1EnvVar(k, v) for k, v in env_vars.items()]
    arch = jobspec["arch"]
    container = V1Container(
        name="main",
        image=f"{CONTAINER_IMAGE_BASE}/img_cp2kci_toolbox_{arch}:latest",
        resources=resources,
        command=[f"./run_{jobspec['target_type']}_target.sh"],
        volume_mounts=volume_mounts,
        security_context=privileged,
        env=k8s_env_vars,
    )

    # tolerations
    tol_costly = V1Toleration(key="costly", operator="Exists")
    tol_arch = V1Toleration(key="kubernetes.io/arch", value=jobspec["arch"])

    # affinity
    requirement = V1NodeSelectorRequirement(
        key="cloud.google.com/gke-nodepool",
        operator="In",
        values=jobspec["nodepools"],
    )
    term = V1NodeSelectorTerm(match_expressions=[requirement])
    selector = V1NodeSelector([term])
    node_affinity = V1NodeAffinity(
        required_during_scheduling_ignored_during_execution=selector
    )
    affinity = V1Affinity(node_affinity=node_affinity)

    # pod spec
    pod_spec = V1PodSpec(
        containers=[container],
        volumes=volumes,
        tolerations=[tol_costly, tol_arch],
        active_deadline_seconds=3 * 60 * 60,  # 3 hours
        termination_grace_period_seconds=0,
        restart_policy="OnFailure",  # https://github.com/kubernetes/kubernetes/issues/79398
        dns_policy="Default",  # bypass kube-dns
        affinity=affinity,
        automount_service_account_token=False,
        service_account_name="cp2kci-runner-k8s-account",
        # priority_class_name=priority,
    )

    # metadata
    metadata = V1ObjectMeta(
        name=jobname, labels={"cp2kci": "run"}, annotations=annotations
    )

    kube.create_namespaced_pod(  # type: ignore
        namespace=K8S_NAMESPACE,
        body=V1Pod(spec=pod_spec, metadata=metadata),
        _request_timeout=K8S_TIMEOUT,
    )


# ======================================================================================
if __name__ == "__main__":
    main()

# EOF
