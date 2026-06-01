FROM ubuntu:26.04

# author: Ole Schuett

# install Ubuntu packages
RUN export DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true && \
    apt-get update && apt-get install -y --no-install-recommends \
    vim \
    wget \
    python3 \
    python3-pip \
    python3-venv \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cp2kci-backend

# Create Python virtual environment to make pip3 happy.
WORKDIR /opt/cp2klab
RUN python3 -m venv .
ENV PATH="/opt/cp2klab/bin:${PATH}"

# install python packages
COPY requirements.txt .
RUN pip3 install -r requirements.txt
RUN pip3 freeze

# install backend
COPY *.py *.conf ./

RUN mypy --strict backend.py

CMD ["./backend.py"]

#EOF
