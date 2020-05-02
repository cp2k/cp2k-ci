FROM ubuntu:20.04

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

# install cuda base libraries
# https://gitlab.com/nvidia/cuda/blob/ubuntu18.04/10.1/base/Dockerfile
# For libraries in the cuda-compat-* package: https://docs.nvidia.com/cuda/eula/index.html#attachment-a
RUN wget -qO- https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/7fa2af80.pub | apt-key add - && \
    echo "deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64 /" > /etc/apt/sources.list.d/cuda.list && \
    echo "deb https://developer.download.nvidia.com/compute/machine-learning/repos/ubuntu1804/x86_64 /" > /etc/apt/sources.list.d/nvidia-ml.list && \
    apt-get update -qq && \
    apt-get install -qq --no-install-recommends cuda-cudart-10.1 cuda-compat-10-1 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -s cuda-10.1 /usr/local/cuda

ENV PATH /usr/local/nvidia/bin:/usr/local/cuda/bin:${PATH}
ENV LD_LIBRARY_PATH /usr/local/nvidia/lib:/usr/local/nvidia/lib64
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES compute,utility
ENV NVIDIA_REQUIRE_CUDA "cuda>=10.1 brand=tesla,driver>=384,driver<385 brand=tesla,driver>=396,driver<397 brand=tesla,driver>=410,driver<411"

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
