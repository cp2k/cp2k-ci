#!/bin/bash -e

# author: Ole Schuett

# Remove old GCP container images.

#https://issuetracker.google.com/issues/38098801
gcloud auth activate-service-account --key-file=$GOOGLE_APPLICATION_CREDENTIALS

echo "Looking for old images..."

for IMAGE in $(gcloud container images list --format="get(name)"); do
    if [[ $IMAGE == *"img_cp2kci_"* || $IMAGE == *"img_cp2kprecommit"* ]]; then
        # For system images we only keep current production version.
        FILTER="-tags:(latest)"
    elif [[ $IMAGE == *"img_cp2k-toolchain"* ]]; then
        # Toolchain images a keep for 30 days because they are expensive to create
        # and don't degrade in performance.
        # The master toolchain is never deleted as it would trigger an avalanche
        # of builds in a following dasboard refresh.
        MAX_AGE_DAYS=30
        FILTER="timestamp.datetime < -P${MAX_AGE_DAYS}D AND -tags:(master)"
    elif [[ $IMAGE == *"img_"* ]]; then
        # Normal ci images are removed quickly as they degrade in performance,
        # as compilation takes more time and are quick (15min) to recreate.
        MAX_AGE_DAYS=3
        FILTER="timestamp.datetime < -P${MAX_AGE_DAYS}D"
    else
        # All other images that don't match "img_*" are ignored.
        continue
    fi

    for SHA in $(gcloud container images list-tags --filter="${FILTER}" --format="get(digest)" "${IMAGE}"); do
        gcloud --quiet container images delete --force-delete-tags "${IMAGE}@${SHA}"
    done

    # Remove images without tags. They are created by simultaneous builds.
    for SHA in $(gcloud container images list-tags --filter="-tags:*" --format="get(digest)" "${IMAGE}"); do
        gcloud --quiet container images delete --force-delete-tags "${IMAGE}@${SHA}"
    done
done

# Cloud storage is cleaned via lifecycle management.

./update_usage_stats.py --upload

#EOF
