FROM ubuntu:22.04

# author: Ole Schuett

# install Ubuntu packages
RUN export DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true && \
    apt-get update && apt-get install -y --no-install-recommends \
    less \
    python3 \
    python3-pip \
    python3-wheel \
    python3-setuptools \
    vim \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cp2kci-frontend

# install python packages
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Install Flask app.
COPY frontend.py .
CMD ["gunicorn", "--bind=:8080", "--workers=1", "--threads=8", "--timeout=0", "frontend:app"]

#EOF
