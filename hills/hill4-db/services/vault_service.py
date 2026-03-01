#!/usr/bin/env python3
"""
Hill 4 - Data Vault: Custom Database Service on TCP 27017
==========================================================
A NoSQL-like data store TCP service with multiple vulnerabilities.

Vulnerabilities:
  1. Auth bypass via debug backdoor password
  2. Pickle deserialization RCE in "restore" command
  3. Command injection in "export" command
  4. Redis password leak via "info" command
  5. Arbitrary file read/write via "dump"/"load" commands

Exploit chain:
  Connect TCP:27017 → auth bypass (debug/backdoor OR info leak → creds) →
  command injection in export OR pickle RCE in restore →
  shell as dbadmin → writable cron script → root → king.txt
  
  Alternative: Redis password from info → redis-cli AUTH → CONFIG SET dir/dbfilename → write SSH key or cron
"""

import socket
import threading
import json
import pickle
import base64
import hashlib
import os
import subprocess
import redis
import traceback

HOST = '0.0.0.0'
PORT = 27017
REDIS_HOST = '127.0.0.1'
REDIS_PORT = 6379
REDIS_PASS = 'VaultR3dis2026'

BANNER = """
╔══════════════════════════════════════════╗
║        DATA VAULT v4.1.0                 ║
║   Enterprise Secure Data Storage         ║
║                                          ║
║   Type 'help' for available commands     ║
╚══════════════════════════════════════════╝
"""

class VaultSession:
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.authenticated = False
        self.username = None
        self.role = None
        self.redis = None

    def get_redis(self):
        if not self.redis:
            self.redis = redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT,
                password=REDIS_PASS, decode_responses=True
            )
        return self.redis

    def send(self, msg):
        try:
            if not msg.endswith('\n'):
                msg += '\n'
            self.conn.sendall(msg.encode())
        except:
            pass

    def recv(self):
        try:
            data = self.conn.recv(4096).decode('utf-8', errors='ignore').strip()
            return data
        except:
            return None

    def handle(self):
        self.send(BANNER)
        self.send("vault> Login required. Use: auth <username> <password>")
        self.send("vault> ")

        while True:
            data = self.recv()
            if data is None:
                break
            if not data:
                self.send("vault> ")
                continue

            parts = data.split(None, 2)
            cmd = parts[0].lower() if parts else ''
            args = parts[1:] if len(parts) > 1 else []

            try:
                if cmd == 'quit' or cmd == 'exit':
                    self.send("Goodbye.\n")
                    break
                elif cmd == 'auth':
                    self.cmd_auth(args)
                elif cmd == 'help':
                    self.cmd_help()
                elif not self.authenticated:
                    self.send("Error: Not authenticated. Use: auth <username> <password>")
                elif cmd == 'whoami':
                    self.send(f"User: {self.username}, Role: {self.role}")
                elif cmd == 'get':
                    self.cmd_get(args)
                elif cmd == 'set':
                    self.cmd_set(args)
                elif cmd == 'list':
                    self.cmd_list(args)
                elif cmd == 'info':
                    self.cmd_info()
                elif cmd == 'users':
                    self.cmd_users()
                elif cmd == 'secrets':
                    self.cmd_secrets()
                elif cmd == 'export':
                    self.cmd_export(args)
                elif cmd == 'dump':
                    self.cmd_dump(args)
                elif cmd == 'load':
                    self.cmd_load(args)
                elif cmd == 'restore':
                    self.cmd_restore(args)
                elif cmd == 'backup':
                    self.cmd_backup(args)
                elif cmd == 'exec':
                    self.cmd_exec(args)
                elif cmd == 'config':
                    self.cmd_config(args)
                else:
                    self.send(f"Unknown command: {cmd}. Type 'help' for available commands.")
            except Exception as e:
                self.send(f"Error: {str(e)}")

            self.send("vault> ")

        self.conn.close()

    # ── Authentication ───────────────────────────────────────────────────

    def cmd_auth(self, args):
        """
        VULNERABLE: 
          1. Debug backdoor: auth debug V4ult-Backdoor-2026
          2. MD5 auth is weak
          3. After auth, role is taken from Redis (can be manipulated)
        """
        if len(args) < 2:
            self.send("Usage: auth <username> <password>")
            return

        username = args[0]
        password = args[1] if len(args) > 1 else ''

        # VULNERABLE: Debug backdoor
        if username == 'debug' and password == 'V4ult-Backdoor-2026':
            self.authenticated = True
            self.username = 'admin'
            self.role = 'admin'
            self.send("[DEBUG] Authenticated as admin via debug backdoor")
            return

        # Normal auth via Redis
        try:
            r = self.get_redis()
            user_data = r.hgetall(f'user:{username}')
            if not user_data:
                self.send("Authentication failed: user not found")
                return

            stored_hash = user_data.get('password', '')
            input_hash = hashlib.md5(password.encode()).hexdigest()

            if input_hash == stored_hash:
                self.authenticated = True
                self.username = username
                self.role = user_data.get('role', 'user')
                self.send(f"Authenticated as {username} (role: {self.role})")
            else:
                self.send("Authentication failed: wrong password")
                # VULNERABLE: Hint about password format
                self.send("Hint: Passwords are stored as MD5 hashes. Check user data.")
        except Exception as e:
            self.send(f"Auth error: {e}")

    # ── Help ─────────────────────────────────────────────────────────────

    def cmd_help(self):
        help_text = """Available commands:
  auth <user> <pass>   Authenticate to the vault
  help                 Show this help
  quit                 Disconnect

After authentication:
  whoami               Show current user
  get <key>            Get a value from the data store
  set <key> <value>    Set a value in the data store
  list [pattern]       List keys matching pattern
  info                 Show vault system information
  users                List user accounts
  secrets              List stored secrets
  config [key] [val]   View or update configuration
  export <format>      Export data (json, csv, raw)
  dump <filepath>      Read a file from the system
  load <filepath> <d>  Write data to a file
  backup [name]        Create a backup
  restore <data>       Restore from backup (base64 encoded)
  exec <query>         Execute a data query
"""
        self.send(help_text)

    # ── Data operations ──────────────────────────────────────────────────

    def cmd_get(self, args):
        if not args:
            self.send("Usage: get <key>")
            return
        r = self.get_redis()
        key = args[0]
        # Try different types
        val = r.get(key)
        if val:
            self.send(f"{key} = {val}")
            return
        val = r.hgetall(key)
        if val:
            self.send(json.dumps(val, indent=2))
            return
        self.send(f"Key not found: {key}")

    def cmd_set(self, args):
        if len(args) < 2:
            self.send("Usage: set <key> <value>")
            return
        r = self.get_redis()
        key = args[0]
        value = args[1] if len(args) > 1 else ''
        r.set(key, value)
        self.send(f"OK: {key} = {value}")

    def cmd_list(self, args):
        r = self.get_redis()
        pattern = args[0] if args else '*'
        keys = r.keys(pattern)
        if keys:
            self.send(f"Keys matching '{pattern}':")
            for k in sorted(keys):
                self.send(f"  {k}")
            self.send(f"Total: {len(keys)}")
        else:
            self.send(f"No keys matching '{pattern}'")

    # ── VULN #4: Info disclosure ─────────────────────────────────────────

    def cmd_info(self):
        """VULNERABLE: Leaks Redis password, system info, file paths"""
        info = {
            'vault_version': '4.1.0',
            'backend': 'redis',
            'redis_host': REDIS_HOST,
            'redis_port': REDIS_PORT,
            'redis_password': REDIS_PASS,  # VULNERABLE: leaks password
            'data_dir': '/opt/vault/data',
            'backup_dir': '/opt/vault/backups',
            'serialization': 'pickle',
            'os_user': os.environ.get('USER', 'dbadmin'),
            'suid_binaries': ['/usr/local/bin/vault_backup'],
            'cron_scripts': ['/opt/vault/admin/maintenance.sh (writable)'],
            'sudo_cmds': [
                'redis-cli (as root, no password)',
                '/opt/vault/admin/db_admin.sh (as root, no password)',
            ],
        }
        self.send(json.dumps(info, indent=2))

    def cmd_users(self):
        r = self.get_redis()
        user_keys = r.keys('user:*')
        self.send("Vault Users:")
        self.send(f"{'Username':<15} {'Role':<12} {'Email':<25}")
        self.send("-" * 52)
        for key in sorted(user_keys):
            data = r.hgetall(key)
            # VULNERABLE: Shows all fields including password for admin role
            if self.role == 'admin':
                self.send(f"{data.get('username', '?'):<15} {data.get('role', '?'):<12} {data.get('email', '?'):<25} pwd:{data.get('password_plain', '?')}")
            else:
                self.send(f"{data.get('username', '?'):<15} {data.get('role', '?'):<12} {data.get('email', '?'):<25}")

    def cmd_secrets(self):
        if self.role not in ('admin', 'operator'):
            self.send("Access denied: admin or operator role required")
            return
        r = self.get_redis()
        secret_keys = r.keys('secret:*')
        self.send("Stored Secrets:")
        for key in sorted(secret_keys):
            data = r.hgetall(key)
            name = key.replace('secret:', '')
            self.send(f"\n  [{name}]")
            for k, v in data.items():
                self.send(f"    {k}: {v}")

    # ── VULN #3: Command injection in export ─────────────────────────────

    def cmd_export(self, args):
        """VULNERABLE: Command injection via format parameter"""
        if not args:
            self.send("Usage: export <format>  (json, csv, raw)")
            return

        fmt = args[0]

        # VULNERABLE: command injection - format is passed to shell
        try:
            cmd = f"redis-cli -a {REDIS_PASS} --no-auth-warning KEYS '*' | head -50 | xargs -I {{}} redis-cli -a {REDIS_PASS} --no-auth-warning GET {{}} 2>/dev/null | {fmt}"
            result = subprocess.check_output(cmd, shell=True, text=True, timeout=10,
                                              stderr=subprocess.STDOUT)
            self.send(f"Export ({fmt}):\n{result}")
        except Exception as e:
            self.send(f"Export error: {e}")

    # ── VULN #5: Arbitrary file read ─────────────────────────────────────

    def cmd_dump(self, args):
        """VULNERABLE: Arbitrary file read"""
        if not args:
            self.send("Usage: dump <filepath>")
            return
        filepath = args[0]
        try:
            with open(filepath, 'r') as f:
                content = f.read(8192)
            self.send(f"--- {filepath} ---\n{content}\n--- END ---")
        except Exception as e:
            self.send(f"Error reading {filepath}: {e}")

    # ── VULN #5: Arbitrary file write ────────────────────────────────────

    def cmd_load(self, args):
        """VULNERABLE: Arbitrary file write"""
        if len(args) < 2:
            self.send("Usage: load <filepath> <data>")
            return
        filepath = args[0]
        data = args[1]
        try:
            with open(filepath, 'w') as f:
                f.write(data)
            self.send(f"Written {len(data)} bytes to {filepath}")
        except Exception as e:
            self.send(f"Error writing {filepath}: {e}")

    # ── VULN #2: Pickle deserialization ──────────────────────────────────

    def cmd_restore(self, args):
        """
        VULNERABLE: Unsafe pickle deserialization
        Attacker can craft a pickle payload to get RCE:
        
        python3 -c "
        import pickle, base64, os
        class Exploit(object):
            def __reduce__(self):
                return (os.system, ('id > /tmp/pwned',))
        print(base64.b64encode(pickle.dumps(Exploit())).decode())
        "
        
        Then: restore <base64-payload>
        """
        if not args:
            self.send("Usage: restore <base64-encoded-backup-data>")
            self.send("Hint: Backups are serialized with pickle and base64-encoded")
            return

        data = args[0]
        try:
            raw = base64.b64decode(data)
            # VULNERABLE: pickle.loads on user input
            obj = pickle.loads(raw)
            self.send(f"Restored data: {obj}")
            # If it's a dict, store in Redis
            if isinstance(obj, dict):
                r = self.get_redis()
                for k, v in obj.items():
                    r.set(f"restored:{k}", str(v))
                self.send(f"Stored {len(obj)} keys in Redis under 'restored:*'")
        except Exception as e:
            self.send(f"Restore error: {e}")

    def cmd_backup(self, args):
        name = args[0] if args else 'backup'
        r = self.get_redis()
        keys = r.keys('*')
        data = {}
        for key in keys:
            t = r.type(key)
            if t == 'string':
                data[key] = r.get(key)
            elif t == 'hash':
                data[key] = r.hgetall(key)
        
        serialized = base64.b64encode(pickle.dumps(data)).decode()
        backup_path = f"/opt/vault/backups/{name}.bak"
        try:
            with open(backup_path, 'w') as f:
                f.write(serialized)
            self.send(f"Backup created: {backup_path}")
            self.send(f"Size: {len(serialized)} bytes (base64)")
            self.send(f"To restore: restore <base64-data>")
        except Exception as e:
            self.send(f"Backup error: {e}")

    # ── Exec query ───────────────────────────────────────────────────────

    def cmd_exec(self, args):
        """Execute Redis commands directly"""
        if not args:
            self.send("Usage: exec <redis-command>")
            return
        
        query = ' '.join(args)
        r = self.get_redis()
        try:
            # Parse and execute redis command
            parts = query.split()
            result = r.execute_command(*parts)
            if isinstance(result, (list, tuple)):
                for item in result:
                    self.send(f"  {item}")
            else:
                self.send(str(result))
        except Exception as e:
            self.send(f"Exec error: {e}")

    # ── Config ───────────────────────────────────────────────────────────

    def cmd_config(self, args):
        r = self.get_redis()
        if not args:
            config = r.hgetall('config')
            self.send("Vault Configuration:")
            for k, v in config.items():
                self.send(f"  {k}: {v}")
            return
        
        if len(args) == 1:
            val = r.hget('config', args[0])
            self.send(f"{args[0]}: {val}")
        elif len(args) >= 2:
            r.hset('config', args[0], args[1])
            self.send(f"Config updated: {args[0]} = {args[1]}")


def handle_client(conn, addr):
    print(f"[+] Connection from {addr}")
    session = VaultSession(conn, addr)
    try:
        session.handle()
    except Exception as e:
        print(f"[-] Error with {addr}: {e}")
        traceback.print_exc()
    finally:
        conn.close()
        print(f"[-] Disconnected: {addr}")


def main():
    # Wait for Redis to be ready
    import time
    for i in range(10):
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS)
            r.ping()
            print("[+] Redis connected")
            break
        except:
            print(f"[*] Waiting for Redis... ({i+1}/10)")
            time.sleep(2)

    # Re-init data to make sure it's loaded
    try:
        from init_data import init_redis
        init_redis()
    except:
        pass

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(20)

    print(f"[+] Data Vault listening on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.daemon = True
        thread.start()


if __name__ == '__main__':
    main()
