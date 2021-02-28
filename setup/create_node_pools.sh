#!/bin/bash -e

# author: Ole Schuett

CLUSTER_NAME="cp2k-cluster"

set -x

# node-taints are still a beta feature

for CPUS in 8 16 32 64 ; do
    #gcloud container node-pools delete pool-highcpu-${CPUS}-skylake
    gcloud beta container node-pools create pool-highcpu-${CPUS}-skylake \
        --cluster="${CLUSTER_NAME}" \
        --machine-type="n1-highcpu-${CPUS}" \
        --min-cpu-platform="Intel Skylake" \
        --preemptible \
        --enable-autoupgrade \
        --enable-autorepair \
        --enable-autoscaling \
        --max-nodes=4 \
        --min-nodes=0 \
        --num-nodes=0 \
        --node-taints="costly=true:NoSchedule"
done

for GPUS in 2 4 ; do
    CPUS=$((8 * ${GPUS}))
    gcloud beta container node-pools create pool-tesla-k80-haswell-${CPUS} \
       --cluster="${CLUSTER_NAME}" \
       --machine-type="n1-standard-${CPUS}" \
       --accelerator="type=nvidia-tesla-k80,count=${GPUS}" \
       --min-cpu-platform="Intel Haswell" \
       --preemptible \
       --enable-autoupgrade \
       --enable-autorepair \
       --enable-autoscaling \
       --max-nodes=1 \
       --min-nodes=0 \
       --num-nodes=0 \
       --node-taints="costly=true:NoSchedule"
done

# There is no n1-standard-24 machine type.
# Using custom type with same 3.75GB/vCPU ratio.
gcloud container node-pools create pool-tesla-p4-haswell-24 \
       --cluster="${CLUSTER_NAME}" \
       --machine-type="custom-24-92160" \
       --accelerator="type=nvidia-tesla-p4,count=1" \
       --min-cpu-platform="Intel Haswell" \
       --preemptible \
       --enable-autoupgrade \
       --enable-autorepair \
       --enable-autoscaling \
       --max-nodes=4 \
       --min-nodes=0 \
       --num-nodes=0 \
       --node-taints="costly=true:NoSchedule"

gcloud container node-pools create pool-tesla-p100-haswell-16 \
       --cluster="${CLUSTER_NAME}" \
       --machine-type="n1-standard-16" \
       --accelerator="type=nvidia-tesla-p100,count=1" \
       --min-cpu-platform="Intel Haswell" \
       --preemptible \
       --enable-autoupgrade \
       --enable-autorepair \
       --enable-autoscaling \
       --max-nodes=1 \
       --min-nodes=0 \
       --num-nodes=0 \
       --node-taints="costly=true:NoSchedule"

#EOF
