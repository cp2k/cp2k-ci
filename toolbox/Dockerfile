FROM nvidia/cuda:11.3.1-base-ubuntu20.04

# author: Ole Schuett

USER root
WORKDIR /tmp

# install ubuntu packages
RUN export DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true && \
    apt-get update -qq && apt-get install -qq --no-install-recommends \
    ca-certificates \
    wget \
    less \
    nano \
    git \
    gpg-agent \
    apt-transport-https \
    ca-certificates \
    software-properties-common \
    python3-pip \
    python3-wheel \
    python3-setuptools \
  && rm -rf /var/lib/apt/lists/*

# install python packages
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# install latest cpuid tool
# The Ubuntu version does not recognize the GCP Skylake CPUs.
RUN wget -q https://www.cp2k.org/static/downloads/cpuid-20180519.x86_64.tar.gz && \
    echo "76b8f7334068c894152ef04bbb0b3ce8  cpuid-20180519.x86_64.tar.gz" | md5sum --check && \
    tar -xzf cpuid-20180519.x86_64.tar.gz && \
    cp ./cpuid-20180519/cpuid /usr/bin/

# install docker
RUN wget -qO- docker.gpg https://download.docker.com/linux/ubuntu/gpg | apt-key add - && \
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu bionic stable" && \
    apt-get update  -qq && \
    apt-get install -qq docker-ce && \
    rm -rf /var/lib/apt/lists/*

# install nvidia-docker
# https://github.com/NVIDIA/nvidia-docker
RUN wget -qO- https://nvidia.github.io/nvidia-docker/gpgkey | apt-key add - && \
    wget -qO- https://nvidia.github.io/nvidia-docker/ubuntu$(lsb_release -rs)/nvidia-docker.list | tee /etc/apt/sources.list.d/nvidia-docker.list && \
    apt-get update -qq && \
    apt-get install -qq nvidia-docker2 && \
    rm -rf /var/lib/apt/lists/*

# install gcloud
RUN wget -qO- https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add - && \
    add-apt-repository "deb http://packages.cloud.google.com/apt cloud-sdk-bionic main"  && \
    apt-get update -qq && \
    apt-get install -qq google-cloud-sdk && \
    rm -rf /var/lib/apt/lists/*

# clone repos
RUN git clone --recursive --depth=1 --single-branch -b master https://github.com/cp2k/cp2k.git /workspace/cp2k

WORKDIR /opt/cp2kci-toolbox
COPY *.sh *.py /opt/cp2kci-toolbox/

#EOF
