#!/bin/bash
set -e

# Start SSH
/usr/sbin/sshd

# Start Redis with weak config
redis-server /etc/redis/redis.conf --daemonize yes

# Start cron for maintenance script
cron

# Initialize data store
python3 /opt/vault/services/init_data.py

# Start the Data Vault TCP service on port 27017
exec python3 /opt/vault/services/vault_service.py
