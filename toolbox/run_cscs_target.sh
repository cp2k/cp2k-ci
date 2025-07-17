#!/bin/bash -e
# shellcheck disable=SC2155,SC2029

# author: Ole Schuett

# Check input.
for key in TARGET GIT_REPO GIT_BRANCH GIT_REF REPORT_UPLOAD_URL ARTIFACTS_UPLOAD_URL CSCS_PIPELINE ; do
    value="$(eval echo \$${key})"
    echo "${key}=\"${value}\""
done

./run_cscs_target.py

echo "Toolbox Done :-)"

#EOF
