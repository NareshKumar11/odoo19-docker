FROM odoo:19

USER root

RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    nano \
    vim \
    python3-pip \
    gcc \
    g++ \
    libpq-dev \
    libsasl2-dev \
    libldap2-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN pip3 install --break-system-packages --no-cache-dir -r /tmp/requirements.txt

USER odoo
