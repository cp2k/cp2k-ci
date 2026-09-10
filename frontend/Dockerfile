FROM ubuntu:26.04

# author: Ole Schuett

# install Ubuntu packages
RUN export DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-wheel \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cp2kci-frontend

# Create Python virtual environment to make pip3 happy.
WORKDIR /opt/cp2klab
RUN python3 -m venv .
ENV PATH="/opt/cp2klab/bin:${PATH}"

# install python packages
COPY requirements.txt .
RUN pip3 install -r requirements.txt
RUN pip3 freeze

# Install app.
COPY templates ./templates/
COPY frontend.py ./
RUN mypy --strict frontend.py

# For real-time logging.
ENV PYTHONUNBUFFERED=1

CMD ["./frontend.py", "--port=8080"]

#EOF
