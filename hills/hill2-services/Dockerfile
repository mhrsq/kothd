# Hill 2 - Service Bastion: Vulnerable Internal Server
# SLA: TCP connection on port 9999
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server procps nano vim curl wget netcat-openbsd \
    vsftpd gcc libc6-dev make sudo xinetd cron \
    && rm -rf /var/lib/apt/lists/*

# Setup SSH with weak credentials (VULNERABLE)
RUN mkdir -p /run/sshd && \
    echo 'root:toor' | chpasswd && \
    sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Create service user
RUN useradd -m -s /bin/bash svcadmin && \
    echo 'svcadmin:service123' | chpasswd

# Create a second user with weak password (VULNERABLE)
RUN useradd -m -s /bin/bash -g operator operator && \
    echo 'operator:P@ssw0rd' | chpasswd

# ── Vulnerable TCP Service (Python) ──
COPY services/tcp_service.py /opt/services/tcp_service.py
COPY services/command_handler.py /opt/services/command_handler.py
RUN chmod +x /opt/services/tcp_service.py

# ── Vulnerable FTP config (VULNERABLE: anon read, weak user write) ──
COPY services/vsftpd.conf /etc/vsftpd.conf
RUN mkdir -p /srv/ftp/pub /srv/ftp/upload && \
    echo "== Service Bastion Internal FTP ==" > /srv/ftp/pub/readme.txt && \
    echo "Credentials backup: svcadmin / service123" > /srv/ftp/pub/.credentials.bak && \
    chmod -R 755 /srv/ftp/pub && \
    chmod 777 /srv/ftp/upload

# ── SUID binary for privesc ──
COPY services/svc_manager.c /tmp/svc_manager.c
RUN gcc -o /usr/local/bin/svc_manager /tmp/svc_manager.c -fno-stack-protector && \
    chmod u+s /usr/local/bin/svc_manager && \
    rm /tmp/svc_manager.c

# ── Cronjob running as root (VULNERABLE: writable script) ──
RUN echo '#!/bin/bash\ntar czf /opt/backups/services_$(date +%s).tar.gz /opt/services/ 2>/dev/null' > /opt/services/maintenance.sh && \
    chmod 777 /opt/services/maintenance.sh && \
    mkdir -p /opt/backups /etc/cron.d && \
    echo '*/3 * * * * root /opt/services/maintenance.sh' > /etc/cron.d/maintenance

# King file
RUN echo 'nobody' > /root/king.txt && chmod 644 /root/king.txt

# Startup script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 21 22 9999

CMD ["/entrypoint.sh"]
