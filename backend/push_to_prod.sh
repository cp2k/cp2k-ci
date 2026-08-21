#!/bin/bash -e

set -x

IMAGE_NAME="us-central1-docker.pkg.dev/cp2k-org-project/cp2kci/img_cp2kci_backend"
TIMESTAMP=$(date +%s)

docker build -t "${IMAGE_NAME}:${TIMESTAMP}" .
docker tag "${IMAGE_NAME}:${TIMESTAMP}" "${IMAGE_NAME}:latest"

docker push "${IMAGE_NAME}:${TIMESTAMP}"
docker push "${IMAGE_NAME}:latest"

kubectl set image deployment cp2kci-backend-deployment "cp2kci-backend-container=${IMAGE_NAME}:${TIMESTAMP}"

#EOF
