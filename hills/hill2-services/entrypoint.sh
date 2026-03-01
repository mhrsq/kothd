#!/bin/bash
set -e

# Start SSH
/usr/sbin/sshd

# Start FTP
vsftpd /etc/vsftpd.conf &

# Start cron
service cron start 2>/dev/null || cron

# Start vulnerable TCP service on port 9999 (SLA check port)
exec python3 /opt/services/tcp_service.py
