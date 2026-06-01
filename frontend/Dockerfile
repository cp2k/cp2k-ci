FROM ubuntu:26.04

# author: Ole Schuett

# install Ubuntu packages
RUN export DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true && \
    apt-get update && apt-get install -y --no-install-recommends \
    vim \
    less \
    python3 \
    python3 \
    python3-pip \
    python3-venv \
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

# Install Flask app.
COPY frontend.py .
RUN mypy --strict frontend.py

CMD ["gunicorn", "--bind=:8080", "--workers=1", "--threads=8", "--timeout=0", "frontend:app"]

#EOF
