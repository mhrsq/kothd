"""
Hill 3 - API Gateway: Vulnerable REST API
==========================================
Vulnerabilities:
  1. JWT auth bypass (weak secret, algorithm confusion)
  2. SSRF via proxy endpoint
  3. Command injection in admin "exec" action
  4. SQL Injection in API key lookup
  5. Information disclosure (debug mode, config leak)

Exploit chain:
  Discover API → info disclosure (debug=true leaks config) →
  JWT forge with leaked secret → admin access →
  SSRF to internal endpoints OR command injection →
  SSH as apiuser → sudo python3 admin_tool.py → root → king.txt
"""

import os
import json
import sqlite3
import subprocess
import jwt
import yaml
import requests
from functools import wraps
from flask import Flask, request, jsonify, g
from datetime import datetime, timedelta

app = Flask(__name__)

DB_PATH = '/opt/api/data/gateway.db'
JWT_SECRET = 's3cret-jwt-k3y-g4teway'  # VULNERABLE: weak & hardcoded

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── Auth helpers ────────────────────────────────────────────────────────────

def verify_api_key(key):
    """VULNERABLE: SQL injection in API key lookup"""
    db = get_db()
    # VULNERABLE: raw string format
    query = f"SELECT * FROM api_keys WHERE key = '{key}' AND is_active = 1"
    try:
        result = db.execute(query).fetchone()
        db.close()
        return dict(result) if result else None
    except Exception as e:
        db.close()
        return None

def verify_jwt(token):
    """VULNERABLE: Accepts 'none' algorithm"""
    try:
        # VULNERABLE: algorithms list includes 'none' and 'HS256'
        # Attacker can forge token with alg=none
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256', 'none'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check API key first
        api_key = request.headers.get('X-API-Key', '')
        if api_key:
            key_data = verify_api_key(api_key)
            if key_data:
                g.auth = key_data
                g.auth_method = 'api_key'
                return f(*args, **kwargs)

        # Check JWT token
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            payload = verify_jwt(token)
            if payload:
                g.auth = payload
                g.auth_method = 'jwt'
                return f(*args, **kwargs)

        return jsonify({"error": "Authentication required", "hint": "Use X-API-Key header or Bearer JWT token"}), 401

    return decorated

def require_admin(f):
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        role = g.auth.get('role', 'user')
        if role not in ('admin', 'service'):
            return jsonify({"error": "Admin access required", "your_role": role}), 403
        return f(*args, **kwargs)
    return decorated

# ── Public endpoints ────────────────────────────────────────────────────────

@app.route('/')
def index():
    return jsonify({
        "service": "API Gateway",
        "version": "3.2.1",
        "status": "running",
        "endpoints": [
            "/api/v1/status",
            "/api/v1/health",
            "/api/v1/keys",
            "/api/v1/routes",
            "/api/v1/config",
            "/api/v1/admin",
            "/api/v1/proxy",
            "/api/v1/auth/token",
            "/api/v1/debug",
        ]
    })

@app.route('/api/v1/health')
def health():
    """SLA health check"""
    return jsonify({"status": "ok", "service": "api-gateway", "version": "3.2.1"}), 200

@app.route('/api/v1/status')
def status():
    return jsonify({
        "status": "operational",
        "uptime": "ok",
        "services": {
            "api": "running",
            "database": "connected",
            "auth": "enabled"
        }
    })

# ── VULN #5: Debug / Info disclosure ────────────────────────────────────────

@app.route('/api/v1/debug')
def debug_info():
    """VULNERABLE: Debug mode leaks sensitive config including JWT secret"""
    db = get_db()
    config = {}
    try:
        rows = db.execute("SELECT key, value FROM config").fetchall()
        config = {r['key']: r['value'] for r in rows}
    except:
        pass
    db.close()

    return jsonify({
        "debug": True,
        "config": config,
        "environment": {
            "user": os.environ.get('USER', 'unknown'),
            "home": os.environ.get('HOME', 'unknown'),
            "path": os.environ.get('PATH', ''),
        },
        "hints": [
            "JWT secret is in the config",
            "Admin API key format: gw-adm-XXXXX",
            "Try /api/v1/auth/token to generate a JWT",
            "SSRF endpoint at /api/v1/proxy",
        ]
    })

# ── Auth token generation ───────────────────────────────────────────────────

@app.route('/api/v1/auth/token', methods=['POST'])
def generate_token():
    """Generate JWT token — VULNERABLE: uses weak secret"""
    data = request.get_json(silent=True) or {}
    username = data.get('username', 'anonymous')
    role = data.get('role', 'user')  # VULNERABLE: user controls their own role

    # Only allow 'user' role unless they know the admin password
    if role == 'admin':
        password = data.get('password', '')
        if password != 'G4t3w4y@dmin!':
            # VULNERABLE: Still creates token but with 'user' role
            # However, the JWT secret is leaked in /api/v1/debug
            # so attacker can forge their own admin token
            role = 'user'

    payload = {
        'sub': username,
        'role': role,
        'iat': datetime.utcnow(),
        'exp': datetime.utcnow() + timedelta(hours=24),
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
    return jsonify({
        "token": token,
        "type": "Bearer",
        "role": role,
        "expires_in": 86400,
    })

# ── API Key management ──────────────────────────────────────────────────────

@app.route('/api/v1/keys')
@require_auth
def list_keys():
    db = get_db()
    keys = db.execute('SELECT id, key, owner, role, rate_limit, created_at FROM api_keys WHERE is_active = 1').fetchall()
    db.close()
    return jsonify({"keys": [dict(k) for k in keys]})

# ── Route management ────────────────────────────────────────────────────────

@app.route('/api/v1/routes')
@require_auth
def list_routes():
    db = get_db()
    routes = db.execute('SELECT * FROM routes').fetchall()
    db.close()
    return jsonify({"routes": [dict(r) for r in routes]})

# ── Config endpoint ─────────────────────────────────────────────────────────

@app.route('/api/v1/config')
@require_auth
def get_config():
    db = get_db()
    config = db.execute('SELECT * FROM config').fetchall()
    db.close()
    return jsonify({"config": {r['key']: r['value'] for r in config}})

# ── VULN #2: SSRF Proxy ────────────────────────────────────────────────────

@app.route('/api/v1/proxy', methods=['POST'])
@require_auth
def proxy_request():
    """
    VULNERABLE: Server-Side Request Forgery (SSRF)
    Attacker can make the server request internal URLs like:
      - file:///etc/passwd
      - http://169.254.169.254/latest/meta-data/ (cloud metadata)
      - http://127.0.0.1:22 (internal port scanning)
    """
    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    method = data.get('method', 'GET').upper()

    if not url:
        return jsonify({"error": "URL is required", "usage": {"url": "http://target", "method": "GET"}}), 400

    try:
        if method == 'GET':
            resp = requests.get(url, timeout=5, allow_redirects=True)
        elif method == 'POST':
            resp = requests.post(url, json=data.get('body', {}), timeout=5)
        else:
            return jsonify({"error": f"Method {method} not supported"}), 400

        return jsonify({
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "body": resp.text[:10000],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── VULN #3: Command Injection in Admin ─────────────────────────────────────

@app.route('/api/v1/admin', methods=['POST'])
@require_admin
def admin_action():
    """
    VULNERABLE: Command injection in admin actions
    Payload: {"action": "check_service", "target": "; cat /etc/shadow"}
    """
    data = request.get_json(silent=True) or {}
    action = data.get('action', '')

    if action == 'check_service':
        target = data.get('target', 'localhost')
        # VULNERABLE: command injection
        try:
            cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://{target} 2>&1"
            result = subprocess.check_output(cmd, shell=True, text=True, timeout=10)
            return jsonify({"action": "check_service", "target": target, "result": result})
        except Exception as e:
            return jsonify({"action": "check_service", "error": str(e)})

    elif action == 'run_diagnostic':
        cmd = data.get('command', 'uptime')
        # VULNERABLE: direct command execution
        try:
            result = subprocess.check_output(cmd, shell=True, text=True, timeout=10,
                                              stderr=subprocess.STDOUT)
            return jsonify({"action": "run_diagnostic", "output": result})
        except Exception as e:
            return jsonify({"action": "run_diagnostic", "error": str(e)})

    elif action == 'read_config':
        filepath = data.get('file', '/opt/api/data/gateway.db')
        # VULNERABLE: arbitrary file read
        try:
            with open(filepath, 'r') as f:
                content = f.read(8192)
            return jsonify({"action": "read_config", "file": filepath, "content": content})
        except Exception as e:
            return jsonify({"action": "read_config", "error": str(e)})

    elif action == 'write_config':
        filepath = data.get('file', '')
        content = data.get('content', '')
        if not filepath:
            return jsonify({"error": "file path required"}), 400
        try:
            with open(filepath, 'w') as f:
                f.write(content)
            return jsonify({"action": "write_config", "file": filepath, "status": "written"})
        except Exception as e:
            return jsonify({"action": "write_config", "error": str(e)})

    elif action == 'list_actions':
        return jsonify({
            "available_actions": [
                {"name": "check_service", "params": {"target": "host:port"}},
                {"name": "run_diagnostic", "params": {"command": "shell command"}},
                {"name": "read_config", "params": {"file": "/path/to/file"}},
                {"name": "write_config", "params": {"file": "/path", "content": "data"}},
                {"name": "list_actions", "params": {}},
            ]
        })

    else:
        return jsonify({"error": f"Unknown action: {action}", "hint": "Try action: list_actions"}), 400

# ── VULN #4: YAML deserialization (bonus vuln) ─────────────────────────────

@app.route('/api/v1/import', methods=['POST'])
@require_auth
def import_config():
    """VULNERABLE: Unsafe YAML load → potential RCE"""
    data = request.get_data(as_text=True)
    content_type = request.headers.get('Content-Type', '')

    if 'yaml' in content_type:
        try:
            # VULNERABLE: yaml.load without SafeLoader
            parsed = yaml.load(data, Loader=yaml.FullLoader)
            return jsonify({"imported": parsed})
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        return jsonify({"error": "Content-Type must contain 'yaml'"}), 400

# ── Request logging ─────────────────────────────────────────────────────────

@app.after_request
def log_request(response):
    try:
        db = get_db()
        db.execute(
            'INSERT INTO request_logs (api_key, path, method, status_code, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?)',
            (
                request.headers.get('X-API-Key', ''),
                request.path,
                request.method,
                response.status_code,
                request.remote_addr,
                request.headers.get('User-Agent', ''),
            )
        )
        db.commit()
        db.close()
    except:
        pass
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
