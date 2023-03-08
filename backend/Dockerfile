FROM ubuntu:22.04

# author: Ole Schuett

# install Ubuntu packages
RUN export DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true && \
    apt-get update && apt-get install -y --no-install-recommends \
    vim \
    wget \
    python3 \
    python3-pip \
    python3-wheel \
    python3-setuptools \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cp2kci-backend

# install python packages
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# install backend
COPY *.py *.conf ./
CMD ["./backend.py"]

#EOF
