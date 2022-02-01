#!/bin/bash
# shellcheck disable=SC2155

# author: Ole Schuett

set -o pipefail

# Check input.
for key in TARGET DOCKERFILE BUILD_ARGS BUILD_PATH NUM_GPUS_REQUIRED PARENT_TARGET PARENT_DOCKERFILE PARENT_BUILD_ARGS PARENT_BUILD_PATH GIT_REPO GIT_BRANCH GIT_REF REPORT_UPLOAD_URL ARTIFACTS_UPLOAD_URL ; do
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

# Helper for building or pulling docker images.
function docker_pull_or_build {
    local this_target=$1
    local this_dockerfile=$2
    local build_args_str=$3
    local this_build_path=$4

    # Convert build_arg_str into array of flags suitable for docker build.
    local build_args_flags=()
    for arg in ${build_args_str} ; do
        build_args_flags+=("--build-arg")
        build_args_flags+=("${arg}")
    done

    # Compute cache key for docker image.
    local git_tree_sha=$(git log -n1 --format=%H ".${this_build_path}")
    local build_args_hash=$(echo "${build_args_flags[@]}" | md5sum | awk '{print $1}')
    local arch_hash=$(echo "${CPUID} " | md5sum | awk '{print $1}')
    local image_name="gcr.io/${PROJECT}/img_${this_target}-arch-${arch_hash::3}"
    local image_tag="gittree-${git_tree_sha::7}-buildargs-${build_args_hash::7}"
    local image_ref="${image_name}:${image_tag}"
    local cache_ref="${image_name}:${GIT_BRANCH//\//-}"

    echo -en "Trying to pull image ${this_target}... " | tee -a "${REPORT}"
    if docker image pull "${image_ref}" ; then
        echo "success :-)" >> "${REPORT}"
    else
        echo "image not found." >> "${REPORT}"
        echo -e "\\n#################### Building Image ${this_target} ####################" | tee -a "${REPORT}"
        echo -e "Dockerfile: ${this_dockerfile}" |& tee -a "${REPORT}"
        echo -e "Build-Path: ${this_build_path}" |& tee -a "${REPORT}"
        echo -e "Build-Args: ${build_args_str}\\n" |& tee -a "${REPORT}"
        docker image pull "${cache_ref}" || docker image pull "${image_name}:master"
        if ! docker build \
               --memory "${MEMORY_LIMIT_MB}m" \
               --cache-from "${cache_ref}" \
               --cache-from "${image_name}:master" \
               --tag "${image_ref}" \
               --file ".${this_dockerfile}" \
               "${build_args_flags[@]}" ".${this_build_path}" |& tee -a "${REPORT}" ; then
          # Build failed, salvage last succesful step.
          last_layer=$(docker images --quiet | head -n 1)
          docker tag "${last_layer}" "${cache_ref}"
          echo -en "\\nPushing image of last succesful step ${last_layer} ... " | tee -a "${REPORT}"
          docker image push "${cache_ref}"
          echo "done." >> "${REPORT}"
          # Write error report and quit.
          echo -e "\\nSummary: Docker build had non-zero exit status.\\nStatus: FAILED" | tee -a "${REPORT}"
          upload_final_report
          exit 0  # Prevent crash looping.
        fi
        echo -en "\\nPushing image ${this_target}... " | tee -a "${REPORT}"
        docker image push "${image_ref}"
        echo "done." >> "${REPORT}"
    fi

    docker tag "${image_ref}" "${cache_ref}"
    docker image push "${cache_ref}"

    # Export image_ref into gobal variable for subsequent docker build or run.
    IMAGE_REF=${image_ref}
}

#===============================================================================

# Write report header
REPORT=/tmp/report.txt
START_DATE=$(date --utc --rfc-3339=seconds)
echo "StartDate: ${START_DATE}" | tee -a "${REPORT}"
CPUID=$(cpuid -1 | grep "(synth)" | cut -c14-)
NUM_CPUS=$(cpuid | grep -c "(synth)")
echo "CpuId: ${NUM_CPUS}x ${CPUID}" | tee -a "${REPORT}"
MEMORY_LIMIT_MB="$((NUM_CPUS * 700))"  # ... ought to be enough for anybody.
if (( NUM_GPUS_REQUIRED > 0 )) ; then
    GPUID=$(nvidia-smi --query-gpu=gpu_name --format=csv | tail -n 1)
    NUM_GPUS=$(nvidia-smi --query-gpu=gpu_name --format=csv,noheader | wc -l)
    echo "GpuId: ${NUM_GPUS}x ${GPUID}" | tee -a "${REPORT}"
    MEMORY_LIMIT_MB="$((MEMORY_LIMIT_MB * 4))"  # use a bit more for GPU runs
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

# Update git repo which contains the Dockerfiles.
cd "/workspace/${GIT_REPO}" || exit
git fetch origin "${GIT_BRANCH}"
if ! git -c advice.detachedHead=false checkout "${GIT_REF}" ; then
    echo -e "\\nGit checkout of ${GIT_REF::7} failed. Restarting..." | tee -a "${REPORT}"
    upload_final_report
    sleep 30
    exit 1  # trigger retry
fi
git --no-pager log -1 --pretty='%nCommitSHA: %H%nCommitTime: %ci%nCommitAuthor: %an%nCommitSubject: %s%n' |& tee -a "${REPORT}"

# Pull or build docker containers.
if [ "${PARENT_TARGET}" != "" ] ; then
    docker_pull_or_build "${PARENT_TARGET}" "${PARENT_DOCKERFILE}" "${PARENT_BUILD_ARGS}" "${PARENT_BUILD_PATH}"
    BUILD_ARGS=${BUILD_ARGS//__PARENT_IMAGE__/${IMAGE_REF}}
fi
docker_pull_or_build "${TARGET}" "${DOCKERFILE}" "${BUILD_ARGS}" "${BUILD_PATH}"


echo -e "\\n#################### Running Image ${TARGET} ####################" | tee -a "${REPORT}"
ARTIFACTS_DIR="/tmp/artifacts"
mkdir "${ARTIFACTS_DIR}"
if ! docker run --init --cap-add=SYS_PTRACE --shm-size=1g \
       --memory "${MEMORY_LIMIT_MB}m" \
       --env "GIT_BRANCH=${GIT_BRANCH}" \
       --env "GIT_REF=${GIT_REF}" \
       --volume "${ARTIFACTS_DIR}:/workspace/artifacts" \
       "${IMAGE_REF}"  |& tee -a "${REPORT}" ; then
    echo -e "\\nSummary: Docker run had non-zero exit status.\\nStatus: FAILED" | tee -a "${REPORT}"
fi

# Upload artifacts.
if [ -n "$(ls -A ${ARTIFACTS_DIR})" ]; then
    echo -en "\\nUploading artifacts... " | tee -a "${REPORT}"
    ARTIFACTS_TGZ="/tmp/artifacts.tgz"
    cd "${ARTIFACTS_DIR}" || exit
    tar -czf "${ARTIFACTS_TGZ}" -- *
    upload_file "${ARTIFACTS_UPLOAD_URL}" "${ARTIFACTS_TGZ}" "application/gzip"
    echo "done" >> "${REPORT}"
fi

upload_final_report
echo "Toolbox Done :-)"

#EOF
