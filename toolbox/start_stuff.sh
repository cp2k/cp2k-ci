#!/bin/bash -e

# author: Ole Schuett

# The nvidia libraries depend on the driver and are mounted at runtime.
# Since dockerd ignores $LD_LIBRARY_PATH for some reason, we'll run ldconfig now.
echo "/usr/local/nvidia/lib" >> /etc/ld.so.conf.d/nvidia.conf
echo "/usr/local/nvidia/lib64" >> /etc/ld.so.conf.d/nvidia.conf
ldconfig

# Start nvidia persistence daemon, if available.
#https://docs.nvidia.com/deploy/driver-persistence/index.html
if which nvidia-persistenced &> /dev/null ; then
  nvidia-persistenced
fi

# Using dm.basesize=20G to allow for very large images.
# https://docs.docker.com/engine/reference/commandline/dockerd/#options-per-storage-driver
# Use `docker system df` to check storage usage.
/usr/bin/dockerd --storage-opt overlay2.size=20G --default-runtime=nvidia -H unix:// &> /var/log/dockerd.log &
sleep 1  # wait a bit for docker deamon

if ! docker version ; then
    cat /var/log/docker.log
    echo "Docker does not work, not running with --privileged?"
    exit 1
fi

#https://issuetracker.google.com/issues/38098801
gcloud auth activate-service-account --key-file=$GOOGLE_APPLICATION_CREDENTIALS
#gcloud auth list
#gcloud config list account


gcloud auth configure-docker --quiet

#EOF
