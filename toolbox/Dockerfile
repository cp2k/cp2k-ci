FROM nvidia/cuda:11.8.0-base-ubuntu22.04

# author: Ole Schuett

USER root
WORKDIR /tmp

# install ubuntu packages
RUN export DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true && \
    apt-get update -qq && apt-get install -qq --no-install-recommends \
    ca-certificates \
    cpuid \
    wget \
    less \
    nano \
    git \
    gpg-agent \
    apt-transport-https \
    ca-certificates \
    software-properties-common \
    openssh-client \
    python3-pip \
    python3-wheel \
    python3-setuptools \
  && rm -rf /var/lib/apt/lists/*

# install python packages
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# install docker
RUN apt-key adv --fetch-keys https://download.docker.com/linux/ubuntu/gpg && \
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable" && \
    apt-get update  -qq && \
    apt-get install -qq docker-ce && \
    rm -rf /var/lib/apt/lists/*

# install nvidia-docker
# https://github.com/NVIDIA/nvidia-docker
RUN apt-key adv --fetch-keys https://nvidia.github.io/nvidia-docker/gpgkey && \
    wget -qO- https://nvidia.github.io/nvidia-docker/ubuntu$(lsb_release -rs)/nvidia-docker.list | tee /etc/apt/sources.list.d/nvidia-docker.list && \
    apt-get update -qq && \
    apt-get install -qq nvidia-docker2 && \
    rm -rf /var/lib/apt/lists/*

# install gcloud
RUN apt-key adv --fetch-keys https://packages.cloud.google.com/apt/doc/apt-key.gpg && \
    add-apt-repository "deb http://packages.cloud.google.com/apt cloud-sdk main" && \
    apt-get update -qq && \
    apt-get install -qq google-cloud-sdk && \
    rm -rf /var/lib/apt/lists/*

# clone repos
RUN git clone --recursive --depth=1 --single-branch -b master https://github.com/cp2k/cp2k.git /workspace/cp2k

WORKDIR /opt/cp2kci-toolbox
COPY *.sh *.py /opt/cp2kci-toolbox/

#EOF
