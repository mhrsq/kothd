#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Hill 2 (Services) Setup Script
# Run on: Hill 2 (${HILL2_PUBLIC_IP:-YOUR_HILL2_IP} / ${HILL2_VPC_IP:-10.x.x.3})
# Deploys vulnerable network services (FTP, Redis, SSH)
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

HILL_DIR="/opt/hill2"

echo "════════════════════════════════════════════════════════"
echo "  KoTH CTF — Hill 2 (Services) Setup"
echo "  Server: ${HILL2_PUBLIC_IP:-YOUR_HILL2_IP} (${HILL2_VPC_IP:-10.x.x.3})"
echo "════════════════════════════════════════════════════════"

# ── Install Dependencies ──────────────────────────────────────────────
echo "[1/4] Installing dependencies..."
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-plugin curl

systemctl enable docker
systemctl start docker

# ── Initialize King File ──────────────────────────────────────────────
echo "[2/4] Setting up king.txt..."
echo "nobody" > /root/king.txt
chmod 644 /root/king.txt

# ── Deploy Vulnerable Services ───────────────────────────────────────
echo "[3/4] Deploying vulnerable services..."
mkdir -p ${HILL_DIR}

cat > ${HILL_DIR}/docker-compose.yml << 'EOF'
version: "3.8"
services:
  # Vulnerable FTP with anonymous access + writable dirs
  vuln-ftp:
    image: fauria/vsftpd
    container_name: hill2-vuln-ftp
    environment:
      FTP_USER: ftpuser
      FTP_PASS: ftp123
      PASV_ADDRESS: ${HILL2_VPC_IP:-10.x.x.3}
    ports:
      - "21:21"
      - "21100-21110:21100-21110"
    volumes:
      - ftp_data:/home/vsftpd
      - ./ftp-files:/home/vsftpd/ftpuser:rw
    restart: unless-stopped
    networks:
      - hill2

  # Vulnerable Redis (no auth, exposed)
  vuln-redis:
    image: redis:7-alpine
    container_name: hill2-vuln-redis
    # Intentionally no password
    command: redis-server --protected-mode no
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
    networks:
      - hill2

  # Vulnerable SSH with weak creds + SUID binaries
  vuln-ssh:
    build:
      context: ./vuln-ssh
      dockerfile: Dockerfile
    container_name: hill2-vuln-ssh
    ports:
      - "2222:22"
    restart: unless-stopped
    networks:
      - hill2

  # Vulnerable web dashboard (monitoring app with RCE)
  vuln-dashboard:
    build:
      context: ./vuln-dashboard
      dockerfile: Dockerfile
    container_name: hill2-vuln-dashboard
    ports:
      - "80:5000"
    environment:
      - REDIS_HOST=vuln-redis
    restart: unless-stopped
    networks:
      - hill2

volumes:
  ftp_data:
  redis_data:

networks:
  hill2:
    driver: bridge
EOF

# ── FTP Files (planted flags) ────────────────────────────────────────
mkdir -p ${HILL_DIR}/ftp-files/public
mkdir -p ${HILL_DIR}/ftp-files/.hidden

cat > ${HILL_DIR}/ftp-files/public/readme.txt << 'FTPEOF'
Welcome to the VulnCorp FTP Server.
Please do not upload unauthorized files.

For support, contact admin@vulncorp.local
FTPEOF

cat > ${HILL_DIR}/ftp-files/.hidden/credentials.txt << 'FTPEOF'
# Internal credentials backup
# FLAG{ftp_4n0nym0us_4cc3ss}
admin:sup3r_s3cr3t_p4ss!
dbadmin:r00tDB2026
redis:no_password_lol
FTPEOF

# ── Vulnerable SSH Container ─────────────────────────────────────────
mkdir -p ${HILL_DIR}/vuln-ssh

cat > ${HILL_DIR}/vuln-ssh/Dockerfile << 'DOCKEREOF'
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y openssh-server sudo vim nano curl wget nmap netcat-openbsd python3
RUN mkdir -p /run/sshd

# Create users with weak passwords
RUN useradd -m -s /bin/bash admin && echo 'admin:admin123' | chpasswd
RUN useradd -m -s /bin/bash -g operator operator && echo 'operator:oper4t0r' | chpasswd
RUN useradd -m -s /bin/bash backup && echo 'backup:backup' | chpasswd
RUN echo 'root:toor' | chpasswd

# SUID binary (privilege escalation)
RUN cp /usr/bin/python3 /usr/local/bin/python3-suid && chmod u+s /usr/local/bin/python3-suid

# Writable /etc/passwd (vuln)
RUN chmod 666 /etc/passwd

# Plant flags
RUN echo 'FLAG{w34k_ssh_cr3ds}' > /root/flag.txt && chmod 600 /root/flag.txt
RUN echo 'FLAG{su1d_pr1v3sc}' > /root/privesc-flag.txt && chmod 600 /root/privesc-flag.txt
RUN echo 'FLAG{wr1t4bl3_p4sswd}' > /opt/.secret && chmod 600 /opt/.secret

# Cron job hint
RUN echo '*/5 * * * * root /opt/backup.sh' >> /etc/crontab
RUN echo '#!/bin/bash\ntar czf /tmp/backup.tar.gz /home/ 2>/dev/null\nchmod 644 /tmp/backup.tar.gz' > /opt/backup.sh && chmod 755 /opt/backup.sh

# SSH config (allow password auth)
RUN sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config

EXPOSE 22
CMD ["/usr/sbin/sshd", "-D"]
DOCKEREOF

# ── Vulnerable Dashboard ─────────────────────────────────────────────
mkdir -p ${HILL_DIR}/vuln-dashboard

cat > ${HILL_DIR}/vuln-dashboard/Dockerfile << 'DOCKEREOF'
FROM python:3.11-slim
WORKDIR /app
RUN pip install flask redis requests
COPY app.py .
EXPOSE 5000
CMD ["python", "app.py"]
DOCKEREOF

cat > ${HILL_DIR}/vuln-dashboard/app.py << 'PYEOF'
from flask import Flask, request, render_template_string, jsonify
import redis
import subprocess
import os

app = Flask(__name__)
r = redis.Redis(host=os.getenv('REDIS_HOST', 'vuln-redis'), port=6379, decode_responses=True)

TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Hill 2 — Service Monitor</title></head>
<body>
<h1>VulnCorp Service Monitor</h1>
<nav>
  <a href="/">Dashboard</a> |
  <a href="/check">Service Check</a> |
  <a href="/redis">Redis Console</a> |
  <a href="/logs">Logs</a>
</nav>
<hr>
{{ content | safe }}
</body>
</html>
"""

@app.route('/')
def index():
    stats = {
        'redis_connected': r.ping(),
        'uptime': subprocess.getoutput('uptime'),
        'hostname': subprocess.getoutput('hostname'),
    }
    content = f"""
    <h2>System Status</h2>
    <ul>
        <li>Redis: {'Connected' if stats['redis_connected'] else 'Disconnected'}</li>
        <li>Uptime: {stats['uptime']}</li>
        <li>Host: {stats['hostname']}</li>
    </ul>
    """
    return render_template_string(TEMPLATE, content=content)

@app.route('/check', methods=['GET', 'POST'])
def check():
    output = ''
    if request.method == 'POST':
        host = request.form.get('host', '')
        # Command injection via service check
        output = subprocess.getoutput(f'nmap -sT -p 21,22,80,3306,6379 {host} 2>&1')
        output = f'<pre>{output}</pre>'

    content = f"""
    <h2>Service Health Check</h2>
    <form method="POST">
        <label>Target Host:</label>
        <input type="text" name="host" placeholder="${HILL2_VPC_IP:-10.x.x.3}">
        <input type="submit" value="Scan">
    </form>
    {output}
    """
    return render_template_string(TEMPLATE, content=content)

@app.route('/redis', methods=['GET', 'POST'])
def redis_console():
    output = ''
    if request.method == 'POST':
        cmd = request.form.get('cmd', '')
        try:
            # Direct Redis command execution (dangerous)
            parts = cmd.split()
            result = r.execute_command(*parts)
            output = f'<pre>{result}</pre>'
        except Exception as e:
            output = f'<pre style="color:red">{e}</pre>'

    content = f"""
    <h2>Redis Console</h2>
    <p><small>Execute Redis commands directly.</small></p>
    <form method="POST">
        <input type="text" name="cmd" placeholder="INFO" size="50">
        <input type="submit" value="Execute">
    </form>
    {output}
    <p><small>Try: INFO, KEYS *, CONFIG GET dir</small></p>
    """
    return render_template_string(TEMPLATE, content=content)

@app.route('/logs')
def logs():
    # SSTI vulnerability via user-agent
    ua = request.headers.get('User-Agent', 'unknown')
    # Server-Side Template Injection
    log_entry = f"Access from: {ua}"
    content = f"""
    <h2>Access Logs</h2>
    <p>Recent visitor: {log_entry}</p>
    <p>FLAG{{sst1_t3mpl4t3_1nj3ct10n}} (hidden in template)</p>
    """
    # render_template_string is vulnerable to SSTI
    return render_template_string(TEMPLATE, content=render_template_string(content))

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'hill2-dashboard'})

# Plant flag in Redis on startup
try:
    r.set('admin:secret', 'FLAG{r3d1s_n0_4uth}')
    r.set('backup:key', '/root/.ssh/id_rsa')
except:
    pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
PYEOF

# ── Start Services ───────────────────────────────────────────────────
echo "[4/4] Starting services..."
cd ${HILL_DIR}
docker compose up -d --build 2>/dev/null || docker-compose up -d --build 2>/dev/null || echo "  ⚠ Docker compose failed — check logs"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ Hill 2 (Services) Setup Complete!"
echo "════════════════════════════════════════════════════════"
echo "  Services:"
echo "    :21   — Vulnerable FTP (anonymous + weak creds)"
echo "    :80   — Vulnerable Dashboard (SSTI, CMDi, Redis)"
echo "    :2222 — Vulnerable SSH (weak creds, SUID, writeable)"
echo "    :6379 — Vulnerable Redis (no auth)"
echo ""
echo "  King file: /root/king.txt (current: $(cat /root/king.txt))"
echo ""
echo "  SLA Check: curl http://${HILL2_VPC_IP:-10.x.x.3}:80/health"
echo "════════════════════════════════════════════════════════"
