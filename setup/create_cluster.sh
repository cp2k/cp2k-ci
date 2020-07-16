#!/bin/bash -e

# author: Ole Schuett

CLUSTER_NAME="cp2k-cluster"

set -x

## pick zone that has Haswell and K80 GPUs
gcloud config set compute/zone "us-central1-c"
gcloud config set project "cp2k-org-project"

## gcloud container clusters delete $CLUSTER_NAME
gcloud container clusters create $CLUSTER_NAME \
   --zone="us-central1-c" \
   --machine-type="n1-standard-1" \
   --disk-size=20 \
   --num-nodes=1 \
   --preemptible \
   --autoscaling-profile optimize-utilization \
   --enable-autorepair \
   --enable-autoupgrade \
   --maintenance-window 3:00

gcloud config set container/cluster ${CLUSTER_NAME}
gcloud container clusters get-credentials ${CLUSTER_NAME}

# disable auto-mounting of service account
kubectl patch serviceaccount/default -p '{"automountServiceAccountToken":false}'

#EOF
