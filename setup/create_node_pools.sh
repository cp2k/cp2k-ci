#!/bin/bash -e

# author: Ole Schuett

CLUSTER_NAME="cp2k-cluster"

set -x

for CPUS in 4 32 ; do
    gcloud container node-pools create pool-t2d-${CPUS} \
        --cluster="${CLUSTER_NAME}" \
        --machine-type="t2d-standard-${CPUS}" \
        --disk-type="pd-ssd" \
        --spot \
        --enable-autoupgrade \
        --enable-autorepair \
        --enable-autoscaling \
        --max-nodes=4 \
        --min-nodes=0 \
        --num-nodes=0 \
        --node-taints="costly=true:NoSchedule"
done

# TODO: Checkout c3-standard-22 instances once they are generally available.
gcloud container node-pools create pool-c2-30 \
    --cluster="${CLUSTER_NAME}" \
    --machine-type="c2-standard-30" \
    --disk-type="pd-ssd" \
    --spot \
    --enable-autoupgrade \
    --enable-autorepair \
    --enable-autoscaling \
    --max-nodes=4 \
    --min-nodes=0 \
    --num-nodes=0 \
    --node-taints="costly=true:NoSchedule"

# ARM machines are currently only available in a few zones:
# https://cloud.google.com/kubernetes-engine/docs/concepts/arm-on-gke#arm-requirements-limitations
# Note that the current quota for T2A_CPU is at 16.
gcloud container node-pools create pool-t2a-16 \
    --cluster="${CLUSTER_NAME}" \
    --machine-type="t2a-standard-16" \
    --disk-type="pd-ssd" \
    --spot \
    --node-locations="us-central1-a" \
    --enable-autoupgrade \
    --enable-autorepair \
    --enable-autoscaling \
    --max-nodes=1 \
    --min-nodes=0 \
    --num-nodes=0 \
    --node-taints="costly=true:NoSchedule"

# There is no n1-standard-24 machine type.
# Using custom type with same 3.75GB/vCPU ratio.
gcloud container node-pools create pool-p4-skylake-24 \
       --cluster="${CLUSTER_NAME}" \
       --machine-type="custom-24-92160" \
       --accelerator="type=nvidia-tesla-p4,count=1" \
       --min-cpu-platform="Intel Skylake" \
       --disk-type="pd-ssd" \
       --spot \
       --enable-autoupgrade \
       --enable-autorepair \
       --enable-autoscaling \
       --max-nodes=4 \
       --min-nodes=0 \
       --num-nodes=0 \
       --node-taints="costly=true:NoSchedule"

# There is no n1-standard-12 machine type.
# Using custom type with same 3.75GB/vCPU ratio.
gcloud container node-pools create pool-v100-skylake-12 \
       --cluster="${CLUSTER_NAME}" \
       --machine-type="custom-12-46080" \
       --accelerator="type=nvidia-tesla-v100,count=1" \
       --min-cpu-platform="Intel Skylake" \
       --disk-type="pd-ssd" \
       --spot \
       --enable-autoupgrade \
       --enable-autorepair \
       --enable-autoscaling \
       --max-nodes=1 \
       --min-nodes=0 \
       --num-nodes=0 \
       --node-taints="costly=true:NoSchedule"

gcloud container node-pools create default-pool \
    --cluster="${CLUSTER_NAME}" \
    --machine-type="n2d-standard-2" \
    --disk-size="20GB" \
    --spot \
    --enable-autoupgrade \
    --enable-autorepair \
    --num-nodes=1

#EOF
