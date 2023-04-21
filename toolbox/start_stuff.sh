#!/bin/bash -e

# author: Ole Schuett

# The nvidia libraries depend on the driver and are mounted at runtime.
# Since dockerd ignores $LD_LIBRARY_PATH for some reason, we'll run ldconfig now.
if [ -d "/usr/local/nvidia" ]; then
    echo "/usr/local/nvidia/lib" >> /etc/ld.so.conf.d/nvidia.conf
    echo "/usr/local/nvidia/lib64" >> /etc/ld.so.conf.d/nvidia.conf
    ldconfig
fi

# Start nvidia persistence daemon, if available.
#https://docs.nvidia.com/deploy/driver-persistence/index.html
if which nvidia-persistenced &> /dev/null ; then
    nvidia-persistenced
fi

# Docker relies on the old iptable behavior.
update-alternatives --set iptables /usr/sbin/iptables-legacy

if which nvidia-container-runtime &> /dev/null ; then
    DOCKER_RUNTIME="nvidia"
else
    DOCKER_RUNTIME="runc"
fi

/usr/bin/dockerd --default-runtime=${DOCKER_RUNTIME} -H unix:// --registry-mirror=https://mirror.gcr.io &
sleep 1  # wait a bit for docker deamon

if ! docker version ; then
    cat /var/log/docker.log
    echo "Docker does not work, not running with --privileged?"
    exit 1
fi

docker info

#https://issuetracker.google.com/issues/38098801
gcloud auth activate-service-account --key-file="$GOOGLE_APPLICATION_CREDENTIALS"
#gcloud auth list
#gcloud config list account


gcloud auth configure-docker us-central1-docker.pkg.dev --quiet

#EOF
