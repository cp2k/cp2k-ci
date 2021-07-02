#!/bin/bash
# shellcheck disable=SC2155,SC2029

# author: Ole Schuett

set -o pipefail

# Check input.
for key in TARGET GIT_REPO GIT_BRANCH GIT_REF REPORT_UPLOAD_URL ARTIFACTS_UPLOAD_URL ; do
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

echo -e "\\n#################### Running Remote Target ${TARGET} ####################" | tee -a "${REPORT}"

ssh "${REMOTE_HOST}" "${REMOTE_CMD}" "${GIT_BRANCH}" "${GIT_REF}" |& tee -a "${REPORT}"

upload_final_report

echo "Toolbox Done :-)"

#EOF
