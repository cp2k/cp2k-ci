#!/bin/bash -e

# author: Ole Schuett

CLUSTER_NAME="cp2k-cluster"
NODE_LOCATIONS="us-central1-a,us-central1-b,us-central1-c,us-central1-f"

DEFAULT_ARGS=()
DEFAULT_ARGS+=("--zone=us-central1-c")
DEFAULT_ARGS+=("--cluster=${CLUSTER_NAME}")
DEFAULT_ARGS+=("--disk-type=pd-ssd")
DEFAULT_ARGS+=("--spot")
DEFAULT_ARGS+=("--node-locations=${NODE_LOCATIONS}")
DEFAULT_ARGS+=("--location-policy=ANY")
DEFAULT_ARGS+=("--enable-autoupgrade")
DEFAULT_ARGS+=("--enable-autorepair")
DEFAULT_ARGS+=("--enable-autoscaling")
DEFAULT_ARGS+=("--total-max-nodes=1")
DEFAULT_ARGS+=("--total-min-nodes=0")
DEFAULT_ARGS+=("--num-nodes=0")
DEFAULT_ARGS+=("--node-taints=costly=true:NoSchedule")

set -x

gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-main
gcloud container node-pools create pool-main  "${DEFAULT_ARGS[@]}" \
    --machine-type="t2d-standard-32" \
    --total-max-nodes=8

gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-intel
gcloud container node-pools create pool-intel "${DEFAULT_ARGS[@]}" \
    --workload-metadata=GKE_METADATA \
    --machine-type="c3-standard-22" \
    --total-max-nodes=4

# ARM machines are currently only available in a few zones:
# https://cloud.google.com/kubernetes-engine/docs/concepts/arm-on-gke#arm-requirements-limitations
# Note that the current quota for T2A_CPU is at 16.
# Note T2A is not available in us-central1-c.
gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-arm
gcloud container node-pools create pool-arm "${DEFAULT_ARGS[@]}" \
    --workload-metadata=GKE_METADATA \
    --node-locations="us-central1-a,us-central1-b,us-central1-f" \
    --machine-type="t2a-standard-16"

# There is no n1-standard-24 machine type.
# Using custom type with same 3.75GB/vCPU ratio.
# Note Tesla P4 is not available in us-central1-b and us-central1-f.
gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-nvidia-pascal
gcloud container node-pools create pool-nvidia-pascal  "${DEFAULT_ARGS[@]}" \
    --workload-metadata=GKE_METADATA \
    --node-locations="us-central1-a,us-central1-c" \
    --machine-type="custom-24-92160" \
    --image-type="UBUNTU_CONTAINERD" \
    --accelerator="type=nvidia-tesla-p4,count=1" \
    --min-cpu-platform="Intel Skylake" \
    --total-max-nodes=4

# There is no n1-standard-12 machine type.
# Using custom type with same 3.75GB/vCPU ratio.
gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-nvidia-volta
gcloud container node-pools create pool-nvidia-volta "${DEFAULT_ARGS[@]}" \
    --workload-metadata=GKE_METADATA \
    --machine-type="custom-12-46080" \
    --image-type="UBUNTU_CONTAINERD" \
    --accelerator="type=nvidia-tesla-v100,count=1" \
    --min-cpu-platform="Intel Skylake"

gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet default-pool
gcloud container node-pools create default-pool \
    --zone="us-central1-c" \
    --cluster="${CLUSTER_NAME}" \
    --machine-type="n2d-standard-2" \
    --disk-size="20GB" \
    --spot \
    --enable-autoupgrade \
    --enable-autorepair \
    --num-nodes=1

#EOF
