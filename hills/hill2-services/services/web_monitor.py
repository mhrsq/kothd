#!/usr/bin/env python3
"""
Hill 2 - Service Bastion: Web Monitoring Dashboard
===================================================
Vulnerable web interface for the service bastion.
Serves as the primary entry point for attackers.

Vulnerabilities:
  1. Hidden /api/debug endpoint leaks internal config (info disclosure)
  2. /api/logs has path traversal (arbitrary file read)
  3. Default session secret allows cookie forgery
  4. /api/health?service= has command injection
"""

from flask import Flask, request, jsonify, session, redirect, render_template_string
import subprocess
import os
import hashlib
import time

app = Flask(__name__)
app.secret_key = 'b4st10n-m0n1t0r-s3cr3t'  # Weak secret (discoverable)

DASHBOARD_HTML = '''<!DOCTYPE html>
<html>
<head>
    <title>Service Bastion Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0e17; color: #c9d1d9; font-family: 'Courier New', monospace; }
        .header { background: #161b22; padding: 20px 30px; border-bottom: 1px solid #30363d; }
        .header h1 { color: #58a6ff; font-size: 20px; }
        .header span { color: #484f58; font-size: 12px; }
        .container { max-width: 900px; margin: 30px auto; padding: 0 20px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 20px; margin: 15px 0; }
        .card h3 { color: #58a6ff; margin-bottom: 10px; }
        .status-ok { color: #3fb950; }
        .status-warn { color: #d29922; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #21262d; }
        th { color: #8b949e; font-size: 12px; text-transform: uppercase; }
        .api-note { color: #484f58; font-size: 12px; margin-top: 20px; text-align: center; }
    </style>
</head>
<body>
    <div class="header">
        <h1>&#x1f6e1; Service Bastion - Monitoring Dashboard</h1>
        <span>Internal Network Monitor v2.3.1</span>
    </div>
    <div class="container">
        <div class="card">
            <h3>Service Status</h3>
            <table>
                <tr><th>Service</th><th>Port</th><th>Status</th></tr>
                <tr><td>SSH Daemon</td><td>22</td><td class="status-ok">&#x2713; Running</td></tr>
                <tr><td>FTP Server</td><td>21</td><td class="status-ok">&#x2713; Running</td></tr>
                <tr><td>Management Console</td><td>9999</td><td class="status-ok">&#x2713; Running</td></tr>
                <tr><td>Monitor Web</td><td>8080</td><td class="status-ok">&#x2713; Running</td></tr>
            </table>
        </div>
        <div class="card">
            <h3>System Overview</h3>
            <table>
                <tr><td>Hostname</td><td>{{ hostname }}</td></tr>
                <tr><td>Uptime</td><td>{{ uptime }}</td></tr>
                <tr><td>Load</td><td>{{ load }}</td></tr>
            </table>
        </div>
        <div class="card">
            <h3>API Endpoints</h3>
            <table>
                <tr><td><code>/api/status</code></td><td>Service health status</td></tr>
                <tr><td><code>/api/health?service=&lt;name&gt;</code></td><td>Check specific service health</td></tr>
            </table>
        </div>
        <p class="api-note">Service Bastion Monitor &copy; 2026 - Internal Use Only</p>
    </div>
</body>
</html>'''

LOGIN_HTML = '''<!DOCTYPE html>
<html>
<head>
    <title>Monitor Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0e17; color: #c9d1d9; font-family: 'Courier New', monospace;
               display: flex; justify-content: center; align-items: center; min-height: 100vh; }
        .login-box { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                     padding: 30px; width: 350px; }
        .login-box h2 { color: #58a6ff; margin-bottom: 20px; text-align: center; }
        input { width: 100%; padding: 10px; margin: 8px 0; background: #0d1117;
                border: 1px solid #30363d; color: #c9d1d9; border-radius: 4px; }
        button { width: 100%; padding: 10px; margin-top: 12px; background: #238636;
                 color: white; border: none; border-radius: 4px; cursor: pointer; }
        .error { color: #f85149; font-size: 13px; text-align: center; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h2>&#x1f512; Monitor Login</h2>
        <form method="POST">
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
        {% if error %}<p class="error">{{ error }}</p>{% endif %}
    </div>
</body>
</html>'''


@app.route('/')
def index():
    try:
        hostname = subprocess.check_output(['hostname'], text=True).strip()
        uptime = subprocess.check_output(['uptime', '-p'], text=True).strip()
        load = open('/proc/loadavg').read().split()[:3]
        load = ' '.join(load)
    except:
        hostname = 'service-bastion'
        uptime = 'unknown'
        load = 'unknown'
    return render_template_string(DASHBOARD_HTML, hostname=hostname, uptime=uptime, load=load)


@app.route('/api/status')
def api_status():
    return jsonify({
        'status': 'operational',
        'services': {
            'ssh': {'port': 22, 'status': 'running'},
            'ftp': {'port': 21, 'status': 'running'},
            'mgmt_console': {'port': 9999, 'status': 'running'},
            'monitor': {'port': 8080, 'status': 'running'}
        },
        'version': '2.3.1'
    })


@app.route('/api/health')
def api_health():
    """VULNERABLE: Command injection via service parameter"""
    service = request.args.get('service', '')
    if not service:
        return jsonify({'error': 'Missing service parameter. Example: /api/health?service=ssh'})

    # VULNERABLE: shell=True with user input
    try:
        cmd = f"pgrep -a {service} 2>&1 | head -5"
        result = subprocess.check_output(cmd, shell=True, text=True, timeout=5)
        return jsonify({'service': service, 'status': 'running', 'processes': result.strip()})
    except subprocess.CalledProcessError:
        return jsonify({'service': service, 'status': 'not found', 'processes': ''})
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Health check timed out'})


@app.route('/api/logs')
def api_logs():
    """VULNERABLE: Path traversal in log file parameter"""
    logfile = request.args.get('file', 'syslog')
    lines = request.args.get('lines', '20')

    # Weak sanitization — only blocks literal "../" but not encoded or absolute paths
    if '../' in logfile:
        return jsonify({'error': 'Invalid path'}), 400

    # VULNERABLE: Absolute paths like /etc/shadow are not blocked
    if logfile.startswith('/'):
        filepath = logfile
    else:
        filepath = f'/var/log/{logfile}'

    try:
        result = subprocess.check_output(
            ['tail', f'-{lines}', filepath],
            text=True, stderr=subprocess.STDOUT, timeout=5
        )
        return jsonify({'file': logfile, 'lines': int(lines), 'content': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 404


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        # VULNERABLE: Hardcoded creds, same as TCP service
        if username == 'monitor' and password == 'monitor':
            session['user'] = username
            session['role'] = 'viewer'
            return redirect('/dashboard')
        elif username == 'svcadmin' and password == 'service123':
            session['user'] = username
            session['role'] = 'admin'
            return redirect('/dashboard')
        else:
            error = 'Invalid credentials'
    return render_template_string(LOGIN_HTML, error=error)


@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect('/login')
    user = session.get('user')
    role = session.get('role')
    return jsonify({
        'message': f'Welcome {user}',
        'role': role,
        'note': 'Dashboard under construction. Use API endpoints for monitoring.',
        'endpoints': ['/api/status', '/api/health', '/api/logs']
    })


# VULNERABLE: Hidden debug endpoint — discoverable via directory bruteforce
@app.route('/api/debug/config')
def debug_config():
    """Leaks internal service configuration including credentials"""
    return jsonify({
        'debug': True,
        'warning': 'Debug mode active — disable in production!',
        'internal_config': {
            'tcp_console': {
                'host': '127.0.0.1',
                'port': 9999,
                'auth_accounts': [
                    {'user': 'svcadmin', 'pass': 'service123', 'role': 'admin'},
                    {'user': 'operator', 'pass': 'P@ssw0rd', 'role': 'operator'},
                ],
                'backdoor_cmd': 'debug override'
            },
            'ftp': {
                'anonymous': True,
                'pub_dir': '/srv/ftp/pub/',
                'note': 'Check .credentials.bak in pub directory'
            },
            'ssh': {
                'root_password': 'toor',
                'svcadmin_password': 'service123'
            },
            'maintenance': {
                'cron_script': '/opt/services/maintenance.sh',
                'interval': 'every 3 minutes',
                'permissions': 'world-writable'
            }
        },
        'flask_secret': app.secret_key,
        'environment': dict(os.environ)
    })


@app.route('/api/debug/env')
def debug_env():
    """Another debug endpoint — less obvious"""
    return jsonify({
        'python_version': subprocess.check_output(['python3', '--version'], text=True).strip(),
        'hostname': subprocess.check_output(['hostname'], text=True).strip(),
        'user': subprocess.check_output(['whoami'], text=True).strip(),
        'pwd': os.getcwd(),
        'suid_binaries': subprocess.check_output(
            'find / -perm -4000 -type f 2>/dev/null | head -10',
            shell=True, text=True
        ).strip(),
    })


@app.route('/robots.txt')
def robots():
    """Hint for attackers to enumerate"""
    return "User-agent: *\nDisallow: /api/debug/\nDisallow: /login\nDisallow: /dashboard\n", 200, {'Content-Type': 'text/plain'}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
