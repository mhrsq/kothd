#!/bin/bash
set -e

# Start SSH
/usr/sbin/sshd

# Start Nginx
nginx

# Start vulnerable Flask app as webadmin (not root)
cd /opt/webapp
exec su -s /bin/bash webadmin -c "gunicorn -w 2 -b 127.0.0.1:5000 app:app --access-logfile - --error-logfile -"
