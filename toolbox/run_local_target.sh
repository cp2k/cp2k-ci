#!/bin/bash
# shellcheck disable=SC2155

# author: Ole Schuett

set -o pipefail

# Check input.
for key in TARGET DOCKERFILE BUILD_ARGS BUILD_PATH USE_CACHE CACHE_FROM NUM_GPUS_REQUIRED GIT_REPO GIT_BRANCH GIT_REF REPORT_UPLOAD_URL ARTIFACTS_UPLOAD_URL ; do
    value="$(eval echo \$${key})"
    echo "${key}=\"${value}\""
done

# Upload to cloud storage.
function upload_file {
    local url=$1
    local file=$2
    local content_type=$3
    wget --quiet --output-document=- --method=PUT --header="content-type: ${content_type}" --header="cache-control: no-cache" --body-file="${file}" "${url}" > /dev/null
}

# Append end date and upload report.
function upload_final_report {
    local end_date=$(date --utc --rfc-3339=seconds)
    echo -e "\\nEndDate: ${end_date}" | tee -a "${REPORT}"
    upload_file "${REPORT_UPLOAD_URL}" "${REPORT}" "text/plain;charset=utf-8"
}

# Handle preemption gracefully.
function sigterm_handler {
    echo -e "\\nThis job just got preempted. No worries, it should restart soon." | tee -a "${REPORT}"
    upload_final_report
    exit 1  # trigger retry
}
trap sigterm_handler SIGTERM

#===============================================================================

# Write report header
REPORT=/tmp/report.txt
START_DATE=$(date --utc --rfc-3339=seconds)
echo "StartDate: ${START_DATE}" | tee -a "${REPORT}"

CPUID=$(cpuid -1 | grep "(synth)" | cut -c14-)
NUM_CPUS=$(grep -c processor /proc/cpuinfo)
SMT_ACTIVE=$(cat /sys/devices/system/cpu/smt/active)
MEMORY_LIMIT_MB="$((NUM_CPUS * 3072))"  # ... ought to be enough for anybody.
if [ "${SMT_ACTIVE}" != "1" ] ; then
    CPUID="${CPUID} (SMT disabled)"
fi
echo "CpuId: ${NUM_CPUS}x ${CPUID}" | tee -a "${REPORT}"

if (( NUM_GPUS_REQUIRED > 0 )) ; then
    GPUID=$(nvidia-smi --query-gpu=gpu_name --format=csv | tail -n 1)
    NUM_GPUS=$(nvidia-smi --query-gpu=gpu_name --format=csv,noheader | wc -l)
    echo "GpuId: ${NUM_GPUS}x ${GPUID}" | tee -a "${REPORT}"
    if (( NUM_GPUS < NUM_GPUS_REQUIRED )) ; then
        echo -e "\\nNot enough GPUs found. Restarting..." | tee -a "${REPORT}"
        upload_final_report
        sleep 30
        exit 1  # trigger retry
    fi
fi

# Upload preliminary report every 30s in the background.
(
while true ; do
    sleep 1
    count=$(( (count + 1) % 30 ))
    if (( count == 1 )) && [ -n "${REPORT_UPLOAD_URL}" ]; then
        upload_file "${REPORT_UPLOAD_URL}" "${REPORT}" "text/plain;charset=utf-8"
    fi
done
)&

# Start docker deamon.
/opt/cp2kci-toolbox/start_stuff.sh
PROJECT=$(gcloud config list --format 'value(core.project)')
PROJECT=${PROJECT:-"cp2k-org-project"}
DOCKER_REPO="us-central1-docker.pkg.dev/${PROJECT}/cp2kci"

target_image="${DOCKER_REPO}/img_${TARGET}"
cache_image="${DOCKER_REPO}/img_${CACHE_FROM}"
branch="${GIT_BRANCH//\//-}"

# Update git repo which contains the Dockerfiles.
cd "/workspace/${GIT_REPO}" || exit
git fetch origin "${GIT_BRANCH}"
if ! git -c advice.detachedHead=false checkout "${GIT_REF}" ; then
    echo -e "\\nGit checkout of ${GIT_REF::7} failed. Restarting..." | tee -a "${REPORT}"
    upload_final_report
    sleep 30
    exit 1  # trigger retry
fi
git submodule update --init --recursive
git --no-pager log -1 --pretty='%nCommitSHA: %H%nCommitTime: %ci%nCommitAuthor: %an%nCommitSubject: %s%n' |& tee -a "${REPORT}"

echo -e "\\n#################### Building Image ${TARGET} ####################" | tee -a "${REPORT}"
echo -e "Dockerfile: ${DOCKERFILE}" |& tee -a "${REPORT}"
echo -e "Build-Path: ${BUILD_PATH}" |& tee -a "${REPORT}"
echo -e "Build-Args: ${BUILD_ARGS}" |& tee -a "${REPORT}"

if [ "${USE_CACHE}" == "yes" ] ; then
    echo -e "Build-Cache: Yes\\n" | tee -a "${REPORT}"
    echo -en "Populating docker build cache... " | tee -a "${REPORT}"
    echo ""
    docker image pull --quiet "${target_image}:${branch}"
    docker image pull --quiet "${target_image}:master"
    if [ "${CACHE_FROM}" != "" ] ; then
        docker image pull --quiet "${cache_image}:master"
    fi
    echo "done." >> "${REPORT}"
else
    echo -e "Build-Cache: No\\n" | tee -a "${REPORT}"
fi

# Convert BUILD_ARGS into array of flags suitable for docker build.
build_args_flags=()
for arg in ${BUILD_ARGS} ; do
    build_args_flags+=("--build-arg")
    build_args_flags+=("${arg}")
done

# Disable buildkit for now because its new output breaks the CI and Dashboard.
export DOCKER_BUILDKIT=0

# The order of the --cache-from images matters!
# Since builds step are usually not reproducible, there can be multiple suitable
# layers in the cache. Preferring prevalent images should counteract divergence.
if ! docker build \
       --memory "${MEMORY_LIMIT_MB}m" \
       --cache-from "${cache_image}:master" \
       --cache-from "${target_image}:master" \
       --cache-from "${target_image}:${branch}" \
       --tag "${target_image}:${branch}" \
       --file ".${DOCKERFILE}" \
       --shm-size=1g \
       "${build_args_flags[@]}" ".${BUILD_PATH}" |& tee -a "${REPORT}" ; then
  # Build failed, salvage last succesful step.
  last_layer=$(docker images --quiet | head -n 1)
  docker tag "${last_layer}" "${target_image}:${branch}"
  echo -en "\\nPushing image of last succesful step ${last_layer}... " | tee -a "${REPORT}"
  echo ""
  docker image push --quiet "${target_image}:${branch}"
  echo "done." >> "${REPORT}"
  # Give priority to the existing (presumably more helpful) failure message.
  if ! grep --quiet -xF "Status: FAILED" "${REPORT}" ; then
    echo -e "\\nSummary: Docker build had non-zero exit status.\\nStatus: FAILED" | tee -a "${REPORT}"
  fi
  # Upload report and quit.
  upload_final_report
  exit 0  # Prevent crash looping.
fi
echo -en "\\nPushing new image... " | tee -a "${REPORT}"
echo ""
docker image push --quiet "${target_image}:${branch}"
echo "done." >> "${REPORT}"

echo -e "\\n#################### Running Image ${TARGET} ####################" | tee -a "${REPORT}"
if ! docker run --init --cap-add=SYS_PTRACE --shm-size=1g \
       --memory "${MEMORY_LIMIT_MB}m" \
       --env "GIT_BRANCH=${GIT_BRANCH}" \
       --env "GIT_REF=${GIT_REF}" \
       --name "my_container" \
       "${target_image}:${branch}"  |& tee -a "${REPORT}" ; then
    echo -e "\\nSummary: Docker run had non-zero exit status.\\nStatus: FAILED" | tee -a "${REPORT}"
fi



# Upload artifacts.
if docker cp my_container:/workspace/artifacts /tmp/ ; then
    echo -en "\\nUploading artifacts... " | tee -a "${REPORT}"
    echo ""
    ARTIFACTS_ZIP="/tmp/artifacts.zip"
    cd /tmp/artifacts || exit
    zip -qr9 "${ARTIFACTS_ZIP}" -- *
    upload_file "${ARTIFACTS_UPLOAD_URL}" "${ARTIFACTS_ZIP}" "application/zip"
    echo "done" >> "${REPORT}"
fi

upload_final_report
echo "Toolbox Done :-)"

#EOF
