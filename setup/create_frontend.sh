#!/bin/bash -e

# author: Ole Schuett

if [ -z "${GITHUB_WEBHOOK_SECRET}" ]; then
    echo "Please set \$GITHUB_WEBHOOK_SECRET"
    exit 1
fi

PROJECT=$(gcloud config list --format 'value(core.project)')
FRONTEND_ACCOUNT_NAME="cp2kci-frontend"
FRONTEND_ACCOUNT="${FRONTEND_ACCOUNT_NAME}@${PROJECT}.iam.gserviceaccount.com"

set -x

gcloud run deploy "cp2kci-frontend" \
   --cpu="1" \
   --memory="128Mi" \
   --max-instances="3" \
   --platform="managed" \
   --region="us-central1" \
   --allow-unauthenticated \
   --service-account="${FRONTEND_ACCOUNT}" \
   --image="us-central1-docker.pkg.dev/${PROJECT}/cp2kci/img_cp2kci_frontend" \
   --update-env-vars="GITHUB_WEBHOOK_SECRET=${GITHUB_WEBHOOK_SECRET}"

gcloud beta run domain-mappings create \
   --platform="managed" \
   --region="us-central1" \
   --service="cp2kci-frontend" \
   --domain="ci.cp2k.org"

#EOF
