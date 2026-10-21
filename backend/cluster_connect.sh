#!/bin/bash -e

set -x

gcloud container clusters get-credentials cp2k-cluster --zone us-central1-c

#EOF
