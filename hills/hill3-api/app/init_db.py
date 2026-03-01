#!/usr/bin/env python3
"""Initialize the API Gateway database"""
import sqlite3
import os

DB_PATH = '/opt/api/data/gateway.db'

if os.path.exists(DB_PATH):
    print("[*] Database already exists, skipping init")
else:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            owner TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            rate_limit INTEGER DEFAULT 100,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            method TEXT DEFAULT 'GET',
            backend_url TEXT NOT NULL,
            auth_required INTEGER DEFAULT 1,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS request_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT,
            path TEXT,
            method TEXT,
            status_code INTEGER,
            ip_address TEXT,
            user_agent TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- API Keys (including a hidden admin key)
        INSERT INTO api_keys (key, owner, role, rate_limit) VALUES
            ('gw-pub-001-2026', 'public', 'user', 100),
            ('gw-dev-042-test', 'developer', 'developer', 500),
            ('gw-adm-MASTER-key', 'admin', 'admin', 99999),
            ('gw-svc-internal', 'service-account', 'service', 1000);

        -- Routes
        INSERT INTO routes (path, method, backend_url, auth_required, description) VALUES
            ('/api/v1/status', 'GET', 'http://localhost:8080/internal/status', 0, 'Public status'),
            ('/api/v1/users', 'GET', 'http://localhost:8080/internal/users', 1, 'User listing'),
            ('/api/v1/config', 'GET', 'http://localhost:8080/internal/config', 1, 'Gateway config'),
            ('/api/v1/admin', 'POST', 'http://localhost:8080/internal/admin', 1, 'Admin operations'),
            ('/api/v1/proxy', 'POST', 'http://localhost:8080/internal/proxy', 1, 'SSRF proxy endpoint');

        -- Config
        INSERT INTO config (key, value) VALUES
            ('jwt_secret', 's3cret-jwt-k3y-g4teway'),
            ('admin_password', 'G4t3w4y@dmin!'),
            ('debug_mode', 'true'),
            ('allow_ssrf', 'true'),
            ('version', '3.2.1');
    ''')
    conn.close()
    os.chmod(DB_PATH, 0o666)
    print("[+] Database initialized")
