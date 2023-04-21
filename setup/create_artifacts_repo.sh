#!/bin/bash -e

# author: Ole Schuett

set -x

gcloud artifacts repositories create "cp2kci" \
   --location="us-central1" \
   --repository-format="docker"

#EOF
