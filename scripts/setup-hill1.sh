#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Hill 1 (Web) Setup Script
# Run on: Hill 1 (${HILL1_PUBLIC_IP:-YOUR_HILL1_IP} / ${HILL1_VPC_IP:-10.x.x.2})
# Deploys vulnerable web applications
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

HILL_DIR="/opt/hill1"

echo "════════════════════════════════════════════════════════"
echo "  KoTH CTF — Hill 1 (Web) Setup"
echo "  Server: ${HILL1_PUBLIC_IP:-YOUR_HILL1_IP} (${HILL1_VPC_IP:-10.x.x.2})"
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
  # Vulnerable PHP web app (SQL injection, file upload, LFI)
  vuln-web:
    build:
      context: ./vuln-web
      dockerfile: Dockerfile
    container_name: hill1-vuln-web
    ports:
      - "80:80"
    volumes:
      - web_uploads:/var/www/html/uploads
    restart: unless-stopped
    networks:
      - hill1

  # Vulnerable Node.js API (broken auth, IDOR, command injection)
  vuln-api:
    build:
      context: ./vuln-api
      dockerfile: Dockerfile
    container_name: hill1-vuln-api
    ports:
      - "3000:3000"
    environment:
      - SECRET_KEY=super-secret-jwt-key-2026
      - DB_FILE=/data/api.db
    volumes:
      - api_data:/data
    restart: unless-stopped
    networks:
      - hill1

  # MySQL for vuln-web
  db:
    image: mysql:8.0
    container_name: hill1-db
    environment:
      MYSQL_ROOT_PASSWORD: r00tP4ss!
      MYSQL_DATABASE: vulnapp
      MYSQL_USER: webapp
      MYSQL_PASSWORD: webapp123
    volumes:
      - db_data:/var/lib/mysql
      - ./init-db.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "3306:3306"
    restart: unless-stopped
    networks:
      - hill1

volumes:
  web_uploads:
  api_data:
  db_data:

networks:
  hill1:
    driver: bridge
EOF

# ── Vulnerable PHP App ───────────────────────────────────────────────
mkdir -p ${HILL_DIR}/vuln-web

cat > ${HILL_DIR}/vuln-web/Dockerfile << 'DOCKEREOF'
FROM php:8.1-apache
RUN docker-php-ext-install mysqli pdo pdo_mysql
RUN a2enmod rewrite
COPY . /var/www/html/
RUN chown -R www-data:www-data /var/www/html && chmod -R 755 /var/www/html
RUN mkdir -p /var/www/html/uploads && chmod 777 /var/www/html/uploads
EXPOSE 80
DOCKEREOF

cat > ${HILL_DIR}/vuln-web/index.php << 'PHPEOF'
<?php
session_start();
$host = 'db';
$user = 'webapp';
$pass = 'webapp123';
$dbname = 'vulnapp';

$conn = new mysqli($host, $user, $pass, $dbname);

$page = isset($_GET['page']) ? $_GET['page'] : 'home';
?>
<!DOCTYPE html>
<html>
<head><title>Hill 1 — Vulnerable Web Portal</title></head>
<body>
<h1>VulnCorp Internal Portal</h1>
<nav>
  <a href="?page=home">Home</a> |
  <a href="?page=login">Login</a> |
  <a href="?page=search">Search</a> |
  <a href="?page=upload">Upload</a> |
  <a href="?page=profile">Profile</a>
</nav>
<hr>
<?php
// LFI vulnerability — include arbitrary files
if (file_exists($page . '.php')) {
    include($page . '.php');
} else {
    // Path traversal possible
    include($page);
}
?>
<hr>
<p><small>VulnCorp v1.0 — Internal Use Only</small></p>
</body>
</html>
PHPEOF

cat > ${HILL_DIR}/vuln-web/home.php << 'PHPEOF'
<h2>Welcome to VulnCorp Portal</h2>
<p>This is the internal employee portal.</p>
<?php
// Intentional info disclosure
echo "<!-- Server: " . php_uname() . " -->";
echo "<!-- DB Host: db:3306 -->";
?>
PHPEOF

cat > ${HILL_DIR}/vuln-web/login.php << 'PHPEOF'
<?php
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $username = $_POST['username'];
    $password = $_POST['password'];

    // SQL Injection vulnerability — unsanitized input
    $query = "SELECT * FROM users WHERE username='$username' AND password='$password'";
    $result = $conn->query($query);

    if ($result && $result->num_rows > 0) {
        $user = $result->fetch_assoc();
        $_SESSION['user'] = $user;
        echo "<p style='color:green'>Welcome, " . $user['username'] . "!</p>";
    } else {
        echo "<p style='color:red'>Invalid credentials. Query: $query</p>";
    }
}
?>
<h2>Login</h2>
<form method="POST">
    <label>Username:</label><br>
    <input type="text" name="username"><br>
    <label>Password:</label><br>
    <input type="password" name="password"><br><br>
    <input type="submit" value="Login">
</form>
PHPEOF

cat > ${HILL_DIR}/vuln-web/search.php << 'PHPEOF'
<?php
if (isset($_GET['q'])) {
    $q = $_GET['q'];
    // SQL Injection + XSS
    $query = "SELECT * FROM products WHERE name LIKE '%$q%'";
    $result = $conn->query($query);

    echo "<h2>Search Results for: $q</h2>";
    if ($result && $result->num_rows > 0) {
        echo "<ul>";
        while ($row = $result->fetch_assoc()) {
            echo "<li>" . $row['name'] . " — $" . $row['price'] . "</li>";
        }
        echo "</ul>";
    } else {
        echo "<p>No results found.</p>";
    }
}
?>
<h2>Product Search</h2>
<form method="GET">
    <input type="text" name="q" placeholder="Search products...">
    <input type="submit" value="Search">
</form>
PHPEOF

cat > ${HILL_DIR}/vuln-web/upload.php << 'PHPEOF'
<?php
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_FILES['file'])) {
    $target = "uploads/" . basename($_FILES['file']['name']);
    // No file type validation — allows PHP shell upload
    if (move_uploaded_file($_FILES['file']['tmp_name'], $target)) {
        echo "<p style='color:green'>File uploaded: <a href='$target'>$target</a></p>";
    } else {
        echo "<p style='color:red'>Upload failed.</p>";
    }
}
?>
<h2>File Upload</h2>
<form method="POST" enctype="multipart/form-data">
    <input type="file" name="file">
    <input type="submit" value="Upload">
</form>
<h3>Uploaded Files:</h3>
<ul>
<?php
foreach (glob("uploads/*") as $f) {
    echo "<li><a href='$f'>" . basename($f) . "</a></li>";
}
?>
</ul>
PHPEOF

cat > ${HILL_DIR}/vuln-web/profile.php << 'PHPEOF'
<?php
if (isset($_GET['cmd'])) {
    // Command injection backdoor (hidden)
    echo "<pre>" . shell_exec($_GET['cmd']) . "</pre>";
}

if (isset($_SESSION['user'])) {
    echo "<h2>Profile: " . $_SESSION['user']['username'] . "</h2>";
    echo "<p>Role: " . $_SESSION['user']['role'] . "</p>";
} else {
    echo "<h2>Please log in first.</h2>";
}
?>
PHPEOF

# ── MySQL Init Script ────────────────────────────────────────────────
cat > ${HILL_DIR}/init-db.sql << 'SQLEOF'
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50),
    password VARCHAR(100),
    role VARCHAR(20) DEFAULT 'user'
);

INSERT INTO users (username, password, role) VALUES
('admin', 'admin123', 'admin'),
('operator', 'oper4t0r!', 'operator'),
('guest', 'guest', 'user'),
('backup', 'b4ckup2026', 'admin');

CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100),
    price DECIMAL(10,2),
    description TEXT
);

INSERT INTO products (name, price, description) VALUES
('Server Rack Unit', 2500.00, 'Standard 42U server rack'),
('Firewall Appliance', 5000.00, 'Enterprise-grade firewall'),
('Managed Switch', 1200.00, '48-port managed switch'),
('UPS System', 3000.00, 'Uninterruptible power supply'),
('SSD Storage', 800.00, '2TB NVMe SSD');

CREATE TABLE IF NOT EXISTS secrets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    flag VARCHAR(200),
    description VARCHAR(200)
);

INSERT INTO secrets (flag, description) VALUES
('FLAG{sql_1nj3ct10n_m4st3r}', 'SQL injection flag'),
('FLAG{f1l3_upl04d_rc3}', 'File upload RCE flag'),
('FLAG{lf1_p4th_tr4v3rs4l}', 'LFI flag'),
('FLAG{c0mm4nd_1nj3ct10n}', 'Command injection flag');
SQLEOF

# ── Vulnerable Node.js API ───────────────────────────────────────────
mkdir -p ${HILL_DIR}/vuln-api

cat > ${HILL_DIR}/vuln-api/Dockerfile << 'DOCKEREOF'
FROM node:20-alpine
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
EXPOSE 3000
CMD ["node", "server.js"]
DOCKEREOF

cat > ${HILL_DIR}/vuln-api/package.json << 'JSONEOF'
{
  "name": "hill1-vuln-api",
  "version": "1.0.0",
  "dependencies": {
    "express": "^4.18.2",
    "jsonwebtoken": "^9.0.0",
    "better-sqlite3": "^9.4.3"
  }
}
JSONEOF

cat > ${HILL_DIR}/vuln-api/server.js << 'JSEOF'
const express = require('express');
const jwt = require('jsonwebtoken');
const Database = require('better-sqlite3');
const { execSync } = require('child_process');
const fs = require('fs');

const app = express();
app.use(express.json());

const SECRET = process.env.SECRET_KEY || 'super-secret-jwt-key-2026';
const DB_FILE = process.env.DB_FILE || '/data/api.db';

// Initialize DB
const db = new Database(DB_FILE);
db.exec(`
  CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT,
    content TEXT,
    private INTEGER DEFAULT 0
  );
  INSERT OR IGNORE INTO notes (id, user_id, title, content, private) VALUES
    (1, 1, 'Admin Config', 'FLAG{br0k3n_4uth_1d0r}', 1),
    (2, 1, 'Server Keys', 'SSH key: /root/.ssh/id_rsa', 1),
    (3, 2, 'Meeting Notes', 'Regular meeting notes...', 0),
    (4, 2, 'Public Update', 'System update v1.2', 0);
`);

// No rate limiting, weak JWT
app.post('/api/login', (req, res) => {
  const { username, password } = req.body;
  // Hardcoded creds (intentional)
  const users = {
    admin: { id: 1, password: 'admin123', role: 'admin' },
    user: { id: 2, password: 'user123', role: 'user' },
    guest: { id: 3, password: 'guest', role: 'guest' }
  };

  const u = users[username];
  if (u && u.password === password) {
    // Weak JWT — algorithm not enforced
    const token = jwt.sign({ id: u.id, role: u.role, username }, SECRET);
    return res.json({ token });
  }
  res.status(401).json({ error: 'Invalid credentials' });
});

// IDOR vulnerability — no ownership check
app.get('/api/notes/:id', (req, res) => {
  const note = db.prepare('SELECT * FROM notes WHERE id = ?').get(req.params.id);
  if (note) return res.json(note);
  res.status(404).json({ error: 'Not found' });
});

app.get('/api/notes', (req, res) => {
  const notes = db.prepare('SELECT id, user_id, title, private FROM notes').all();
  res.json(notes);
});

// Command injection via ping endpoint
app.post('/api/tools/ping', (req, res) => {
  const { host } = req.body;
  try {
    // Command injection — unsanitized input to exec
    const output = execSync(`ping -c 2 ${host}`, { timeout: 5000 }).toString();
    res.json({ output });
  } catch (e) {
    res.json({ output: e.stderr ? e.stderr.toString() : 'Ping failed' });
  }
});

// Server status endpoint (info disclosure)
app.get('/api/status', (req, res) => {
  res.json({
    uptime: process.uptime(),
    memory: process.memoryUsage(),
    env: process.env,  // Leaks all env vars including SECRET
    version: '1.0.0'
  });
});

app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', service: 'hill1-api' });
});

app.listen(3000, '0.0.0.0', () => {
  console.log('Hill 1 Vuln API running on :3000');
});
JSEOF

# ── Start Services ───────────────────────────────────────────────────
echo "[4/4] Starting services..."
cd ${HILL_DIR}
docker compose up -d --build 2>/dev/null || docker-compose up -d --build 2>/dev/null || echo "  ⚠ Docker compose failed — check logs"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ Hill 1 (Web) Setup Complete!"
echo "════════════════════════════════════════════════════════"
echo "  Services:"
echo "    :80   — Vulnerable PHP Web App (SQLi, LFI, Upload)"
echo "    :3000 — Vulnerable Node.js API (IDOR, CMDi, Auth)"
echo "    :3306 — MySQL (exposed intentionally)"
echo ""
echo "  King file: /root/king.txt (current: $(cat /root/king.txt))"
echo ""
echo "  SLA Check: curl http://${HILL1_VPC_IP:-10.x.x.2}:80 && curl http://${HILL1_VPC_IP:-10.x.x.2}:3000/api/health"
echo "════════════════════════════════════════════════════════"
