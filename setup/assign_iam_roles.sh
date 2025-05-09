#!/bin/bash -e

# author: Ole Schuett

PROJECT=$(gcloud config list --format 'value(core.project)')
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format 'value(projectNumber)')

CLOUDBUILD_ACCOUNT="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
FRONTEND_ACCOUNT="cp2kci-frontend@${PROJECT}.iam.gserviceaccount.com"
BACKEND_ACCOUNT="cp2kci-backend@${PROJECT}.iam.gserviceaccount.com"
RUNNER_ACCOUNT="cp2kci-runner@${PROJECT}.iam.gserviceaccount.com"
CRONJOB_ACCOUNT="cp2kci-cronjob@${PROJECT}.iam.gserviceaccount.com"


set -x

# cloud builder
gcloud projects add-iam-policy-binding "${PROJECT}" --member="serviceAccount:${CLOUDBUILD_ACCOUNT}" --role="roles/run.admin"               # for updating frontend container
gcloud projects add-iam-policy-binding "${PROJECT}" --member="serviceAccount:${CLOUDBUILD_ACCOUNT}" --role="roles/container.developer"     # for updating backend container
gcloud projects add-iam-policy-binding "${PROJECT}" --member="serviceAccount:${CLOUDBUILD_ACCOUNT}" --role="roles/iam.serviceAccountUser"  # somehow required too

# frontend
gcloud pubsub topics add-iam-policy-binding "cp2kci-topic" --member="serviceAccount:${FRONTEND_ACCOUNT}"  --role="roles/pubsub.publisher"  # for sending message to backend

# backend
gcloud storage buckets add-iam-policy-binding gs://cp2k-ci  --member="serviceAccount:${BACKEND_ACCOUNT}" --role="roles/storage.admin"        # for uploading empty reports
gcloud pubsub topics add-iam-policy-binding "cp2kci-topic" --member="serviceAccount:${BACKEND_ACCOUNT}"  --role="roles/pubsub.subscriber"    # for receiving messages from frontend
gcloud pubsub topics add-iam-policy-binding "cp2kci-topic" --member="serviceAccount:${BACKEND_ACCOUNT}"  --role="roles/pubsub.viewer"        # for receiving messages from frontend
gcloud iam service-accounts add-iam-policy-binding "${BACKEND_ACCOUNT}" --member="serviceAccount:${BACKEND_ACCOUNT}" --role="roles/iam.serviceAccountTokenCreator"  # for singing upload urls


# runner
gcloud artifacts repositories add-iam-policy-binding "cp2kci" --member="serviceAccount:${RUNNER_ACCOUNT}" --role="roles/artifactregistry.writer" --location="us-central1"  # for uploading docker images
gcloud storage buckets add-iam-policy-binding gs://cp2k-spack-cache --member="serviceAccount:${RUNNER_ACCOUNT}" --role="roles/storage.objectAdmin"

# cronjob
gcloud storage buckets add-iam-policy-binding gs://cp2k-ci  --member="serviceAccount:${CRONJOB_ACCOUNT}" --role="roles/storage.admin"        # for uploading usage_stats.txt
gcloud pubsub topics add-iam-policy-binding "cp2kci-topic" --member="serviceAccount:${CRONJOB_ACCOUNT}"  --role="roles/pubsub.publisher"     # for sending messsages to backend
gcloud artifacts repositories add-iam-policy-binding "cp2kci" --member="serviceAccount:${CRONJOB_ACCOUNT}" --role="roles/artifactregistry.repoAdmin" --location="us-central1"  # for removing old images

# Map the Kubernetes service account to the corresponding GCP account. Note that the GCP account is treated as a ressource here.
gcloud iam service-accounts add-iam-policy-binding "${BACKEND_ACCOUNT}" --member="serviceAccount:${PROJECT}.svc.id.goog[default/cp2kci-backend-k8s-account]" --role="roles/iam.workloadIdentityUser"
gcloud iam service-accounts add-iam-policy-binding "${RUNNER_ACCOUNT}" --member="serviceAccount:${PROJECT}.svc.id.goog[default/cp2kci-runner-k8s-account]" --role="roles/iam.workloadIdentityUser"
gcloud iam service-accounts add-iam-policy-binding "${CRONJOB_ACCOUNT}" --member="serviceAccount:${PROJECT}.svc.id.goog[default/cp2kci-cronjob-k8s-account]" --role="roles/iam.workloadIdentityUser"

#EOF
