# author: Ole Schuett

import kubernetes
from uuid import uuid4
from datetime import datetime, timedelta

class KubernetesUtil:
    def __init__(self, config, output_bucket, image_base, namespace="default"):
        try:
            kubernetes.config.load_kube_config()
        except Exception:
            kubernetes.config.load_incluster_config()
        self.config = config
        self.output_bucket = output_bucket
        self.image_base = image_base
        self.namespace = namespace
        self.api = kubernetes.client
        self.batch_api = kubernetes.client.BatchV1Api()

    # --------------------------------------------------------------------------
    def get_upload_url(self, path, content_type="text/plain;charset=utf-8"):
        expiration = datetime.utcnow() + timedelta(hours=12)
        blob = self.output_bucket.blob(path)
        upload_url = blob.generate_signed_url(expiration, method='PUT',
                                              content_type=content_type)
        return upload_url

    # --------------------------------------------------------------------------
    def list_jobs(self, selector):
        return self.batch_api.list_namespaced_job(self.namespace,
                                                  label_selector=selector)

    # --------------------------------------------------------------------------
    def delete_job(self, job_name):
        print("deleting job: " + job_name)
        self.batch_api.delete_namespaced_job(job_name, self.namespace,
                                             propagation_policy="Background")

    # --------------------------------------------------------------------------
    def patch_job_annotations(self, job_name, new_annotations):
        new_job_metadata = self.api.V1ObjectMeta(annotations=new_annotations)
        new_job = self.api.V1Job(metadata=new_job_metadata)
        self.batch_api.patch_namespaced_job(job_name, self.namespace, new_job)

        # also update annotations of report_blob
        report_blob = self.output_bucket.blob(new_annotations["cp2kci-report-path"])
        if report_blob.exists():
            report_blob.metadata = new_annotations
            report_blob.patch()

    # --------------------------------------------------------------------------
    def resources(self, target):
        cpu = self.config.getint(target, "cpu")
        gpu = self.config.getint(target, "gpu", fallback=0)
        req_cpu = 0.97 * cpu   # Request 3% less to leave some for kubernetes.
        return self.api.V1ResourceRequirements(requests={"cpu": req_cpu},
                                               limits={"nvidia.com/gpu": gpu})

    # --------------------------------------------------------------------------
    def affinity(self, target):
        nodepools = self.config.get(target, "nodepools").split()
        requirement = self.api.V1NodeSelectorRequirement(
            key='cloud.google.com/gke-nodepool',
            operator='In', values=nodepools)
        term = self.api.V1NodeSelectorTerm(match_expressions=[requirement])
        selector = self.api.V1NodeSelector([term])
        node_affinity = self.api.V1NodeAffinity(
            required_during_scheduling_ignored_during_execution=selector)
        return self.api.V1Affinity(node_affinity=node_affinity)

    # --------------------------------------------------------------------------
    def submit_run(self, target, git_branch, git_ref, job_annotations, priority=None):
        print("Submitting run for target: {}.".format(target))

        job_name = "run-" + target + "-" + str(uuid4())[:8]
        report_path = job_name + "_report.txt"
        artifacts_path = job_name + "_artifacts.tgz"

        # upload waiting message
        report_blob = self.output_bucket.blob(report_path)
        assert not report_blob.exists()
        report_blob.cache_control = "no-cache"
        report_blob.upload_from_string("Report not yet available.")

        # amend job annotations
        job_annotations['cp2kci-target'] = target
        job_annotations['cp2kci-report-path'] = report_path
        job_annotations['cp2kci-report-url'] = report_blob.public_url
        job_annotations['cp2kci-artifacts-path'] = artifacts_path

        # publish job annotations also to report blob
        report_blob.metadata = job_annotations
        report_blob.patch()

        # environment variables
        env_vars = {}
        env_vars["TARGET"] = target
        env_vars["GIT_BRANCH"] = git_branch
        env_vars["GIT_REF"] = git_ref
        env_vars["GIT_REPO"] = self.config.get(target, "repository")
        env_vars["DOCKERFILE"] = self.config.get(target, "dockerfile")
        env_vars["BUILD_ARGS"] = self.config.get(target, "build_args", fallback="")
        env_vars["REPORT_UPLOAD_URL"] = self.get_upload_url(report_path)
        env_vars["ARTIFACTS_UPLOAD_URL"] = \
            self.get_upload_url(artifacts_path, content_type="application/gzip")

        # optional parent target, ie. cp2k toolchain.
        if self.config.has_option(target, "parent"):
            parent = self.config.get(target, "parent")
            assert not self.config.has_option(parent, "parent")
            assert self.config.get(parent, "repository") == env_vars["GIT_REPO"]
            env_vars["PARENT_TARGET"] = parent
            env_vars["PARENT_DOCKERFILE"] = self.config.get(parent, "dockerfile")
            env_vars["PARENT_BUILD_ARGS"] = self.config.get(parent, "build_args", fallback="")


        # docker volume (needed for performance)
        docker_source = self.api.V1EmptyDirVolumeSource()
        docker_volname = "volume-" + job_name
        docker_volume = self.api.V1Volume(name=docker_volname,
                                          empty_dir=docker_source)
        docker_mount = self.api.V1VolumeMount(mount_path="/var/lib/docker/",
                                              name=docker_volname)

        # secret stuff
        secret_source = self.api.V1SecretVolumeSource(secret_name="runner-gcp-key")
        secret_volume = self.api.V1Volume(name="runner-gcp-key-volume",
                                          secret=secret_source)
        secret_mount = self.api.V1VolumeMount(name="runner-gcp-key-volume",
                                              mount_path="/var/secrets/google",
                                              read_only=True)
        env_vars["GOOGLE_APPLICATION_CREDENTIALS"] = "/var/secrets/google/key.json"

        # container with privileged=True as needed by docker build
        privileged = self.api.V1SecurityContext(privileged=True)
        toolbox_image = self.image_base + "/img_cp2kci_toolbox:latest"
        k8s_env_vars = [self.api.V1EnvVar(k, v) for k, v in env_vars.items()]
        container = self.api.V1Container(name="main",
                                         image=toolbox_image,
                                         resources=self.resources(target),
                                         command=["./run_target.sh"],
                                         volume_mounts=[docker_mount,
                                                        secret_mount],
                                         security_context=privileged,
                                         env=k8s_env_vars)

        # pod
        tolerate_costly = self.api.V1Toleration(key="costly", operator="Exists")
        pod_spec = self.api.V1PodSpec(containers=[container],
                                      volumes=[docker_volume, secret_volume],
                                      tolerations=[tolerate_costly],
                                      termination_grace_period_seconds=0,
                                      restart_policy="OnFailure",  # https://github.com/kubernetes/kubernetes/issues/79398
                                      dns_policy="Default",  # bypass kube-dns
                                      affinity=self.affinity(target),
                                      automount_service_account_token=False,
                                      priority_class_name=priority)
        pod_template = self.api.V1PodTemplateSpec(spec=pod_spec)

        # metadata
        job_metadata = self.api.V1ObjectMeta(name=job_name,
                                             labels={'cp2kci': 'run'},
                                             annotations=job_annotations)

        # job
        job_spec = self.api.V1JobSpec(template=pod_template,
                                      backoff_limit=6,
                                      active_deadline_seconds=10800)  # 3 hours
        job = self.api.V1Job(spec=job_spec, metadata=job_metadata)
        self.batch_api.create_namespaced_job(self.namespace, body=job)

# EOF
