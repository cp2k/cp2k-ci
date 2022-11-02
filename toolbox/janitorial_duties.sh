#!/bin/bash -e

# author: Ole Schuett

# Remove old GCP container images.

#https://issuetracker.google.com/issues/38098801
gcloud auth activate-service-account --key-file="${GOOGLE_APPLICATION_CREDENTIALS}"

echo "Looking for old images..."

DOCKER_REPO="us-central1-docker.pkg.dev/cp2k-org-project/cp2kci"
for IMAGE in $(gcloud artifacts docker images list ${DOCKER_REPO} --format="get(package)"); do
    if [[ $IMAGE == *"img_cp2kci_"* || $IMAGE == *"img_cp2kprecommit"* ]]; then
        # For system images we only keep current production version.
        FILTER="-tags:(latest)"
    elif [[ $IMAGE == *"img_"* ]]; then
        # CI images are removed after 7 days to keep storage costs low.
        MAX_AGE_DAYS=7
        FILTER="updateTime < -P${MAX_AGE_DAYS}D AND -tags:(master)"
    else
        # All other images that don't match "img_*" are ignored.
        continue
    fi

    for SHA in $(gcloud artifacts docker images list --include-tags --filter="${FILTER}" --format="get(version)" "${IMAGE}"); do
        gcloud --quiet artifacts docker images delete --delete-tags "${IMAGE}@${SHA}"
    done

    # Remove images without tags. They are created by simultaneous builds.
    for SHA in $(gcloud artifacts docker images list --include-tags --filter="-tags:*" --format="get(version)" "${IMAGE}"); do
        gcloud --quiet artifacts docker images delete --delete-tags "${IMAGE}@${SHA}"
    done
done

# Cloud storage is cleaned via lifecycle management.

./update_usage_stats.py --upload

#EOF
