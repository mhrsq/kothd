# Hill 3 - API Gateway: Vulnerable REST API Service
# SLA: HTTP 200 on port 8080
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server procps nano vim curl wget sudo \
    && rm -rf /var/lib/apt/lists/*

# Setup SSH (root password matches scorebot creds for king.txt reading)
RUN mkdir -p /run/sshd && \
    echo "root:${ROOT_PASSWORD:-changeme}" | chpasswd && \
    sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Create API service user
RUN useradd -m -s /bin/bash apiuser && \
    echo 'apiuser:api2026' | chpasswd

# Install Python deps
RUN pip install --no-cache-dir flask==3.0.0 pyjwt==2.8.0 gunicorn==21.2.0 pyyaml==6.0.1 requests==2.31.0

# Copy vulnerable API
COPY app/ /opt/api/

# Create API data dirs
RUN mkdir -p /opt/api/data /opt/api/uploads /opt/api/logs && \
    chown -R apiuser:apiuser /opt/api

# VULNERABLE: sudo misconfiguration — apiuser can run python3 as root without password
RUN echo 'apiuser ALL=(root) NOPASSWD: /usr/bin/python3 /opt/api/admin_tool.py *' >> /etc/sudoers

# King file
RUN echo 'nobody' > /root/king.txt && chmod 644 /root/king.txt

# Startup script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22 8080

CMD ["/entrypoint.sh"]
