# Hill 1 - Web Fortress: Vulnerable Corporate Web Portal
# SLA: HTTP 200 on port 80
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx sqlite3 sudo openssh-server procps nano vim curl wget \
    gcc libc6-dev make \
    && rm -rf /var/lib/apt/lists/*

# Setup SSH
RUN mkdir -p /run/sshd && \
    echo 'root:koth2026root' | chpasswd && \
    sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Create vulnerable web user
RUN useradd -m -s /bin/bash webadmin && \
    echo 'webadmin:w3b@dm1n2026' | chpasswd

# Install Python deps
RUN pip install --no-cache-dir flask==3.0.0 gunicorn==21.2.0

# Copy vulnerable web app
COPY app/ /opt/webapp/
COPY checker/ /opt/checker/

# Setup vulnerable SQLite database
RUN mkdir -p /opt/webapp/data && \
    sqlite3 /opt/webapp/data/portal.db < /opt/webapp/init_db.sql && \
    chown -R webadmin:webadmin /opt/webapp

# Vulnerable SUID binary for privesc
COPY app/privesc/backup_tool.c /tmp/backup_tool.c
RUN gcc -o /usr/local/bin/backup_tool /tmp/backup_tool.c && \
    chmod u+s /usr/local/bin/backup_tool && \
    rm /tmp/backup_tool.c

# Nginx config — proxies to Flask app
COPY app/nginx.conf /etc/nginx/sites-available/default

# King file
RUN echo 'nobody' > /root/king.txt && chmod 644 /root/king.txt

# Startup script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22 80

CMD ["/entrypoint.sh"]
