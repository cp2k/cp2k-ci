FROM ubuntu:20.04

# author: Ole Schuett

# install Ubuntu packages
RUN export DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true && \
    apt-get update && apt-get install -y --no-install-recommends \
    cron \
    less \
    certbot \
    apache2 \
    libapache2-mod-wsgi-py3 \
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

RUN /usr/sbin/a2enmod rewrite ssl
COPY 000-default.conf ci.cp2k.org.conf /etc/apache2/sites-available/

COPY letsencrypt.ini .
RUN mkdir -m 0755 /var/www/letsencrypt && \
    chown www-data:www-data /var/www/letsencrypt

# Install Flask app.
COPY frontend.py frontend.wsgi /var/www/cp2k.org/ci/

COPY cmd.sh .
CMD ["./cmd.sh"]

#EOF
