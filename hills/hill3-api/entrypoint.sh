#!/bin/bash
set -e

# Start SSH
/usr/sbin/sshd

# Initialize API database
cd /opt/api
python3 init_db.py

# Start vulnerable API as apiuser
exec su -s /bin/bash apiuser -c "cd /opt/api && gunicorn -w 2 -b 0.0.0.0:8080 api:app --access-logfile - --error-logfile -"
