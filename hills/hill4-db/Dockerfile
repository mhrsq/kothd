FROM python:3.11-slim

# ── System packages ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    sudo \
    gcc \
    libc6-dev \
    make \
    redis-server \
    curl \
    netcat-openbsd \
    procps \
    cron \
    nano vim \
    && rm -rf /var/lib/apt/lists/*

# ── SSH configuration ────────────────────────────────────────────────────
RUN mkdir -p /var/run/sshd && \
    echo "root:${ROOT_PASSWORD:-changeme}" | chpasswd && \
    sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# ── Create service user ─────────────────────────────────────────────────
RUN useradd -m -s /bin/bash dbadmin && \
    echo 'dbadmin:db@dmin2026' | chpasswd && \
    usermod -aG sudo dbadmin

# ── Sudo misconfiguration ───────────────────────────────────────────────
# dbadmin can run redis-cli as root without password
RUN echo 'dbadmin ALL=(root) NOPASSWD: /usr/bin/redis-cli *' >> /etc/sudoers && \
    echo 'dbadmin ALL=(root) NOPASSWD: /opt/vault/admin/db_admin.sh *' >> /etc/sudoers

# ── Python dependencies ─────────────────────────────────────────────────
RUN pip install --no-cache-dir msgpack pymongo redis

# ── Application files ───────────────────────────────────────────────────
COPY services/ /opt/vault/services/
COPY admin/ /opt/vault/admin/

# ── SUID binary for privesc ─────────────────────────────────────────────
COPY privesc/vault_backup.c /tmp/vault_backup.c
RUN gcc -o /usr/local/bin/vault_backup /tmp/vault_backup.c && \
    chmod u+s /usr/local/bin/vault_backup && \
    rm /tmp/vault_backup.c

# ── Redis configuration (intentionally weak) ────────────────────────────
COPY services/redis.conf /etc/redis/redis.conf

# ── Cron job (writable by dbadmin) ──────────────────────────────────────
RUN echo '*/5 * * * * root /opt/vault/admin/maintenance.sh' >> /etc/crontab && \
    touch /opt/vault/admin/maintenance.sh && \
    chmod 777 /opt/vault/admin/maintenance.sh && \
    echo '#!/bin/bash\nredis-cli -a VaultR3dis2026 BGSAVE' > /opt/vault/admin/maintenance.sh

# ── King file ────────────────────────────────────────────────────────────
RUN echo "UNCLAIMED" > /root/king.txt && \
    chmod 644 /root/king.txt

# ── Credentials breadcrumb ──────────────────────────────────────────────
RUN echo "# Redis internal password: VaultR3dis2026" > /opt/vault/.env && \
    echo "# DB Admin: dbadmin / db@dmin2026" >> /opt/vault/.env && \
    chmod 644 /opt/vault/.env

# ── Permissions ──────────────────────────────────────────────────────────
RUN chmod +x /opt/vault/services/*.py 2>/dev/null || true && \
    chmod +x /opt/vault/admin/*.sh 2>/dev/null || true && \
    mkdir -p /opt/vault/data /opt/vault/backups && \
    chown -R dbadmin:dbadmin /opt/vault/data /opt/vault/backups

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22 27017 6379

ENTRYPOINT ["/entrypoint.sh"]
