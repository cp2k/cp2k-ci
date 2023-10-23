#!/bin/bash -e

# author: Ole Schuett

CLUSTER_NAME="cp2k-cluster"
NODE_LOCATIONS="us-central1-a,us-central1-b,us-central1-c,us-central1-f"

DEFAULT_ARGS=()
DEFAULT_ARGS+=("--cluster='${CLUSTER_NAME}'")
DEFAULT_ARGS+=("--disk-type=pd-ssd")
DEFAULT_ARGS+=("--spot")
DEFAULT_ARGS+=("--node-locations='${NODE_LOCATIONS}'")
DEFAULT_ARGS+=("--location-policy=ANY")
DEFAULT_ARGS+=("--enable-autoupgrade")
DEFAULT_ARGS+=("--enable-autorepair")
DEFAULT_ARGS+=("--enable-autoscaling")
DEFAULT_ARGS+=("--total-max-nodes=1")
DEFAULT_ARGS+=("--total-min-nodes=0")
DEFAULT_ARGS+=("--num-nodes=0")
DEFAULT_ARGS+=("--node-taints='costly=true:NoSchedule'")

set -x

for CPUS in 4 32 ; do
    gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-t2d-${CPUS}
    gcloud container node-pools create pool-t2d-${CPUS} ${DEFAULT_ARGS:+""} \
        --machine-type="t2d-standard-${CPUS}" \
        --total-max-nodes=4
done

# TODO: Checkout c3-standard-22 instances once they are generally available.
gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-c2-30
gcloud container node-pools create pool-c2-30 "${DEFAULT_ARGS[@]}" \
    --machine-type="c2-standard-30" \
    --total-max-nodes=4

# ARM machines are currently only available in a few zones:
# https://cloud.google.com/kubernetes-engine/docs/concepts/arm-on-gke#arm-requirements-limitations
# Note that the current quota for T2A_CPU is at 16.
# Note T2A is not available in us-central1-c.
gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-t2a-16
gcloud container node-pools create pool-t2a-16 "${DEFAULT_ARGS[@]}" \
    --node-locations="us-central1-a,us-central1-b,us-central1-f" \
    --machine-type="t2a-standard-16"

# There is no n1-standard-24 machine type.
# Using custom type with same 3.75GB/vCPU ratio.
# Note Tesla P4 is not available in us-central1-b and us-central1-f.
gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-p4-skylake-24
gcloud container node-pools create pool-p4-skylake-24  "${DEFAULT_ARGS[@]}" \
    --node-locations="us-central1-a,us-central1-c" \
    --machine-type="custom-24-92160" \
    --accelerator="type=nvidia-tesla-p4,count=1" \
    --min-cpu-platform="Intel Skylake" \
    --total-max-nodes=4

# There is no n1-standard-12 machine type.
# Using custom type with same 3.75GB/vCPU ratio.
gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet pool-v100-skylake-12
gcloud container node-pools create pool-v100-skylake-12 "${DEFAULT_ARGS[@]}" \
    --machine-type="custom-12-46080" \
    --accelerator="type=nvidia-tesla-v100,count=1" \
    --min-cpu-platform="Intel Skylake"

gcloud container node-pools delete --cluster="${CLUSTER_NAME}" --quiet default-pool
gcloud container node-pools create default-pool \
    --cluster="${CLUSTER_NAME}" \
    --machine-type="n2d-standard-2" \
    --disk-size="20GB" \
    --spot \
    --enable-autoupgrade \
    --enable-autorepair \
    --num-nodes=1

#EOF
