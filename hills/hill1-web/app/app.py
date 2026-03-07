"""
Hill 1 - Web Fortress: Vulnerable Corporate Web Portal
=======================================================
Vulnerabilities:
  1. SQL Injection in login & search (sqlite3 raw queries)
  2. File Upload bypass (double extension, MIME check only)
  3. Command Injection in "ping" diagnostic tool
  4. IDOR in user profile endpoint

Exploit chain:
  SQLi → admin access → file upload webshell → RCE as webadmin → SUID privesc → root → king.txt
"""

import os
import sqlite3
import subprocess
from functools import wraps
from flask import (Flask, request, render_template_string, redirect,
                   url_for, session, flash, send_from_directory, jsonify)

app = Flask(__name__)
app.secret_key = 'w3b-f0rtress-s3cret-k3y-2026'

DB_PATH = '/opt/webapp/data/portal.db'
UPLOAD_DIR = '/opt/webapp/uploads'
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Database helper (INTENTIONALLY VULNERABLE — raw string formatting) ──────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── Templates ───────────────────────────────────────────────────────────────

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Web Fortress - Corporate Portal</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #0f1923; color: #c9d1d9; }
        .navbar { background: #161b22; padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; }
        .navbar a { color: #58a6ff; text-decoration: none; margin: 0 12px; }
        .navbar .brand { color: #22c55e; font-weight: bold; font-size: 18px; }
        .container { max-width: 900px; margin: 30px auto; padding: 0 20px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 24px; margin: 16px 0; }
        input, textarea { width: 100%; padding: 10px; margin: 8px 0; background: #0d1117; border: 1px solid #30363d; border-radius: 4px; color: #c9d1d9; }
        button, .btn { background: #238636; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }
        button:hover, .btn:hover { background: #2ea043; }
        .btn-danger { background: #da3633; }
        .alert { padding: 12px; margin: 12px 0; border-radius: 4px; }
        .alert-error { background: #3d1f1f; border: 1px solid #da3633; color: #f85149; }
        .alert-success { background: #1f3d1f; border: 1px solid #238636; color: #3fb950; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #30363d; }
        th { color: #58a6ff; }
        .tag { background: #1f6feb33; color: #58a6ff; padding: 2px 8px; border-radius: 12px; font-size: 12px; }
        pre { background: #0d1117; padding: 16px; border-radius: 4px; overflow-x: auto; border: 1px solid #30363d; }
        footer { text-align: center; padding: 20px; color: #484f58; margin-top: 40px; }
    </style>
</head>
<body>
    <div class="navbar">
        <span class="brand">🏰 Web Fortress Portal</span>
        <div>
            <a href="/">Home</a>
            <a href="/posts">Posts</a>
            {% if session.get('user') %}
                <a href="/profile">Profile</a>
                <a href="/upload">Upload</a>
                {% if session.get('role') == 'admin' %}
                    <a href="/admin/diagnostic">Diagnostic</a>
                    <a href="/admin/users">Users</a>
                {% endif %}
                <a href="/logout">Logout ({{ session['user'] }})</a>
            {% else %}
                <a href="/login">Login</a>
            {% endif %}
        </div>
    </div>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for cat, msg in messages %}
                    <div class="alert alert-{{ cat }}">{{ msg }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        {{ content|safe }}
    </div>
    <footer>Web Fortress Corporate Portal v2.1.3 &copy; 2026</footer>
</body>
</html>
'''

def render(content, **kwargs):
    return render_template_string(BASE_TEMPLATE, content=render_template_string(content, **kwargs), session=session)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            flash('Please login first', 'error')
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

# ── Routes ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render('''
        <h1>Welcome to Web Fortress</h1>
        <div class="card">
            <h3>Corporate Internal Portal</h3>
            <p>Access company resources, internal communications, and file sharing.</p>
            <p style="margin-top:12px"><a href="/login" class="btn">Login to Portal</a></p>
        </div>
        <div class="card">
            <h3>Recent Announcements</h3>
            <p>• System maintenance scheduled for this weekend</p>
            <p>• Security policy update — change your passwords</p>
            <p>• New file sharing feature now available</p>
        </div>
    ''')

@app.route('/health')
def health():
    """SLA health check endpoint"""
    return jsonify({"status": "ok", "service": "web-fortress", "version": "2.1.3"}), 200

# ── VULN #1: SQL Injection in Login ─────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        # VULNERABLE: Raw string formatting in SQL query
        db = get_db()
        query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
        try:
            user = db.execute(query).fetchone()
            if user:
                session['user'] = user['username']
                session['user_id'] = user['id']
                session['role'] = user['role']
                flash(f'Welcome back, {user["full_name"]}!', 'success')
                return redirect('/')
            else:
                flash('Invalid credentials', 'error')
        except Exception as e:
            flash(f'Database error: {str(e)}', 'error')
        finally:
            db.close()

    return render('''
        <h2>Login</h2>
        <div class="card">
            <form method="POST">
                <label>Username</label>
                <input type="text" name="username" placeholder="Enter username" required>
                <label>Password</label>
                <input type="password" name="password" placeholder="Enter password" required>
                <button type="submit" style="margin-top:12px">Login</button>
            </form>
        </div>
    ''')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ── VULN #1b: SQL Injection in Search ───────────────────────────────────────

@app.route('/search')
def search():
    q = request.args.get('q', '')
    results = []
    if q:
        db = get_db()
        # VULNERABLE: Raw string in LIKE query
        query = f"SELECT * FROM posts WHERE title LIKE '%{q}%' OR content LIKE '%{q}%'"
        try:
            results = db.execute(query).fetchall()
        except Exception as e:
            flash(f'Search error: {str(e)}', 'error')
        finally:
            db.close()

    return render('''
        <h2>Search Posts</h2>
        <div class="card">
            <form method="GET">
                <input type="text" name="q" value="{{ q }}" placeholder="Search posts...">
                <button type="submit">Search</button>
            </form>
        </div>
        {% if results %}
        <div class="card">
            <h3>Results ({{ results|length }})</h3>
            {% for r in results %}
                <div style="margin:12px 0; padding:12px; border:1px solid #30363d; border-radius:4px;">
                    <strong>{{ r['title'] }}</strong>
                    <p>{{ r['content'][:200] }}</p>
                </div>
            {% endfor %}
        </div>
        {% elif q %}
        <div class="card"><p>No results found for "{{ q }}"</p></div>
        {% endif %}
    ''', q=q, results=results)

# ── Posts ───────────────────────────────────────────────────────────────────

@app.route('/posts')
def posts():
    db = get_db()
    posts = db.execute('''
        SELECT p.*, u.username as author_name
        FROM posts p LEFT JOIN users u ON p.author_id = u.id
        ORDER BY p.created_at DESC
    ''').fetchall()
    db.close()

    return render('''
        <h2>Posts</h2>
        <div style="margin-bottom:12px">
            <a href="/search" class="btn">🔍 Search</a>
            {% if session.get('user') %}
                <a href="/posts/new" class="btn">+ New Post</a>
            {% endif %}
        </div>
        {% for p in posts %}
        <div class="card">
            <h3>{{ p['title'] }}</h3>
            <p>{{ p['content'] }}</p>
            <small style="color:#484f58">By {{ p['author_name'] or 'Unknown' }} | {{ p['created_at'] }}</small>
        </div>
        {% endfor %}
    ''', posts=posts)

@app.route('/posts/new', methods=['GET', 'POST'])
@login_required
def new_post():
    if request.method == 'POST':
        title = request.form.get('title', '')
        content = request.form.get('content', '')
        db = get_db()
        db.execute('INSERT INTO posts (title, content, author_id) VALUES (?, ?, ?)',
                    (title, content, session.get('user_id')))
        db.commit()
        db.close()
        flash('Post created!', 'success')
        return redirect('/posts')

    return render('''
        <h2>New Post</h2>
        <div class="card">
            <form method="POST">
                <label>Title</label>
                <input type="text" name="title" required>
                <label>Content</label>
                <textarea name="content" rows="6" required></textarea>
                <button type="submit" style="margin-top:12px">Publish</button>
            </form>
        </div>
    ''')

# ── VULN #2: File Upload Bypass ─────────────────────────────────────────────

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'csv'}

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or f.filename == '':
            flash('No file selected', 'error')
            return redirect('/upload')

        # VULNERABLE: Only checks MIME type, not actual extension
        # Bypass: Upload shell.png.php with Content-Type: image/png
        # Also: double extension check is weak — "file.php.jpg" passes but
        # the real vuln is that we save with ORIGINAL filename
        content_type = f.content_type or ''
        if not any(content_type.startswith(t) for t in ['image/', 'text/', 'application/pdf', 'application/octet-stream']):
            flash('File type not allowed', 'error')
            return redirect('/upload')

        filename = f.filename  # VULNERABLE: No sanitization of filename
        filepath = os.path.join(UPLOAD_DIR, filename)
        f.save(filepath)

        # Make uploaded file executable if it looks like a script
        # (simulating misconfigured permissions — intentional vuln)
        os.chmod(filepath, 0o755)

        db = get_db()
        db.execute('INSERT INTO files (filename, filepath, uploaded_by) VALUES (?, ?, ?)',
                    (filename, filepath, session.get('user_id')))
        db.commit()
        db.close()

        flash(f'File uploaded: {filename}', 'success')
        return redirect('/upload')

    # List uploaded files
    db = get_db()
    files = db.execute('SELECT * FROM files ORDER BY uploaded_at DESC').fetchall()
    db.close()

    return render('''
        <h2>File Manager</h2>
        <div class="card">
            <h3>Upload File</h3>
            <form method="POST" enctype="multipart/form-data">
                <input type="file" name="file" required>
                <button type="submit" style="margin-top:12px">Upload</button>
            </form>
            <p style="margin-top:8px;color:#484f58">Allowed: images, text, PDF, docs</p>
        </div>
        {% if files %}
        <div class="card">
            <h3>Uploaded Files</h3>
            <table>
                <tr><th>Filename</th><th>Uploaded</th><th>Action</th></tr>
                {% for f in files %}
                <tr>
                    <td>{{ f['filename'] }}</td>
                    <td>{{ f['uploaded_at'] }}</td>
                    <td><a href="/files/{{ f['filename'] }}" class="btn" style="padding:4px 12px;font-size:12px">Download</a></td>
                </tr>
                {% endfor %}
            </table>
        </div>
        {% endif %}
    ''', files=files)

@app.route('/files/<path:filename>')
def download_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# ── VULN #3: Command Injection in Diagnostic Tool ──────────────────────────

@app.route('/admin/diagnostic', methods=['GET', 'POST'])
@login_required
def diagnostic():
    if session.get('role') != 'admin':
        flash('Admin access required', 'error')
        return redirect('/')

    output = ''
    if request.method == 'POST':
        target = request.form.get('target', '')
        # VULNERABLE: Direct command injection via subprocess
        # Input: ; cat /etc/passwd
        # Input: $(whoami)
        # Input: | id
        try:
            cmd = f"ping -c 2 -W 2 {target}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            output = "Command timed out"
        except Exception as e:
            output = f"Error: {str(e)}"

    return render('''
        <h2>Network Diagnostic Tool</h2>
        <div class="card">
            <h3>Ping Test</h3>
            <form method="POST">
                <label>Target Host / IP</label>
                <input type="text" name="target" placeholder="e.g. 10.0.0.1" required>
                <button type="submit" style="margin-top:12px">Run Ping</button>
            </form>
        </div>
        {% if output %}
        <div class="card">
            <h3>Output</h3>
            <pre>{{ output }}</pre>
        </div>
        {% endif %}
    ''', output=output)

# ── VULN #4: IDOR in Profile ───────────────────────────────────────────────

@app.route('/profile')
@login_required
def profile():
    user_id = request.args.get('id', session.get('user_id'))
    db = get_db()
    # VULNERABLE: No authorization check — any user can view any profile by ID
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    db.close()

    if not user:
        flash('User not found', 'error')
        return redirect('/')

    return render('''
        <h2>User Profile</h2>
        <div class="card">
            <table>
                <tr><th>Field</th><th>Value</th></tr>
                <tr><td>ID</td><td>{{ user['id'] }}</td></tr>
                <tr><td>Username</td><td>{{ user['username'] }}</td></tr>
                <tr><td>Password</td><td>{{ user['password'] }}</td></tr>
                <tr><td>Role</td><td><span class="tag">{{ user['role'] }}</span></td></tr>
                <tr><td>Email</td><td>{{ user['email'] }}</td></tr>
                <tr><td>Full Name</td><td>{{ user['full_name'] }}</td></tr>
            </table>
        </div>
    ''', user=user)

# ── Admin: User Management ─────────────────────────────────────────────────

@app.route('/admin/users')
@login_required
def admin_users():
    if session.get('role') != 'admin':
        flash('Admin access required', 'error')
        return redirect('/')

    db = get_db()
    users = db.execute('SELECT * FROM users').fetchall()
    db.close()

    return render('''
        <h2>User Management</h2>
        <div class="card">
            <table>
                <tr><th>ID</th><th>Username</th><th>Role</th><th>Email</th><th>Actions</th></tr>
                {% for u in users %}
                <tr>
                    <td>{{ u['id'] }}</td>
                    <td>{{ u['username'] }}</td>
                    <td><span class="tag">{{ u['role'] }}</span></td>
                    <td>{{ u['email'] }}</td>
                    <td><a href="/profile?id={{ u['id'] }}">View</a></td>
                </tr>
                {% endfor %}
            </table>
        </div>
    ''', users=users)

# ── API endpoints for programmatic access ──────────────────────────────────

@app.route('/api/status')
def api_status():
    """Machine-readable status for monitoring"""
    return jsonify({
        "service": "web-fortress",
        "status": "running",
        "version": "2.1.3",
        "uptime": "ok"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
