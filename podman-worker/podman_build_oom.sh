#!/bin/bash

# author: Ole Schuett

# Rootless podman build that group-kills the build container on OOM
# and exits with 137 when that happens.
# Usage: podman-build-oom [podman build args...]

# Re-run this script to put ourselves into our own cgroup scope.
if [ -z "${IN_OWN_SCOPE:-}" ]; then
    IN_OWN_SCOPE=1 exec systemd-run --user --scope --quiet -p Delegate=yes "$0" "$@"
fi

# This is the outer scope that we own.
outer_scope="/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup)"

# Move this script into a subscope to empty the $outer_scope... 
mkdir "${outer_scope}/supervisor" || exit 1
echo $$ > "${outer_scope}/supervisor/cgroup.procs"  || exit 1

# ... so that we can deligate control of memory to subtrees.
echo "+memory" > "${outer_scope}/cgroup.subtree_control"  || exit 1
    
# Create build scope.
build_scope="${outer_scope}/build"
mkdir "$build_scope" || exit 1

# Configure OOM group killer in $build_scope (possible because memory control was deligated)
echo 1 > "$build_scope/memory.oom.group"  || exit 1

# Run podman build in the $build_scope
podman build --cgroup-manager cgroupfs --cgroup-parent "${build_scope#/sys/fs/cgroup}" "$@"
exit_code=$?

# Check $outer_scope for OOM events.
oom=$(awk '$1=="oom_kill"{print $2}' "$outer_scope/memory.events")
if [ "$exit_code" -ne 0 ] && [ "${oom:-0}" -gt 0 ];  then
    echo "OOM killed"
    exit 137
else
    exit $exit_code
fi

#EOF
