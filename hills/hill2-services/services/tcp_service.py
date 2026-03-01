#!/usr/bin/env python3
"""
Hill 2 - Service Bastion: Custom TCP Service
=============================================
Simulates an "internal management console" accessible on port 9999.

Vulnerabilities:
  1. Hardcoded auth bypass (hidden backdoor command)
  2. Command injection in "diagnostic" function
  3. Information disclosure (leaks system info)
  4. Format string-style vuln in "log" command

Exploit chain:
  FTP anon → discover credentials → SSH as svcadmin → 
  TCP service backdoor or cmd injection → 
  writable cron script (maintenance.sh) → root → king.txt

OR:
  TCP service → auth bypass → command injection → svcadmin shell →
  SUID svc_manager → root
"""

import socket
import threading
import logging
import signal
import sys

from command_handler import CommandHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s [TCP-SVC] %(message)s')
logger = logging.getLogger('tcp_service')

HOST = '0.0.0.0'
PORT = 9999
MAX_CONNECTIONS = 20

BANNER = """
╔══════════════════════════════════════════════╗
║     Service Bastion Management Console       ║
║          Internal Access Only v3.7            ║
║                                              ║
║  Type 'help' for available commands           ║
║  Type 'quit' to disconnect                    ║
╚══════════════════════════════════════════════╝
"""

class ServiceHandler:
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.authenticated = False
        self.username = None
        self.handler = CommandHandler()

    def send(self, msg):
        try:
            self.conn.sendall((msg + '\n').encode())
        except:
            pass

    def recv(self):
        try:
            data = self.conn.recv(4096).decode('utf-8', errors='ignore').strip()
            return data
        except:
            return None

    def prompt(self):
        prefix = f'{self.username}@bastion' if self.authenticated else 'bastion'
        try:
            self.conn.sendall(f'{prefix}> '.encode())
        except:
            pass

    def handle(self):
        logger.info(f"Connection from {self.addr}")
        self.send(BANNER)
        self.send("Authentication required. Use 'auth <username> <password>'")

        while True:
            self.prompt()
            data = self.recv()
            if data is None:
                break
            if not data:
                continue

            parts = data.split(None, 2)
            cmd = parts[0].lower()

            if cmd == 'quit' or cmd == 'exit':
                self.send("Goodbye!")
                break

            elif cmd == 'auth':
                self._handle_auth(parts)

            elif cmd == 'help':
                self._handle_help()

            # VULNERABLE: Hidden backdoor command
            elif cmd == 'debug' and len(parts) > 1 and parts[1] == 'override':
                self.authenticated = True
                self.username = 'svcadmin'
                self.send("[DEBUG] Authentication overridden — access granted")

            elif not self.authenticated:
                self.send("Error: Not authenticated. Use 'auth <username> <password>'")

            else:
                response = self.handler.execute(cmd, parts[1:] if len(parts) > 1 else [], self.username)
                self.send(response)

        self.conn.close()
        logger.info(f"Disconnected: {self.addr}")

    def _handle_auth(self, parts):
        if len(parts) < 3:
            self.send("Usage: auth <username> <password>")
            return

        username = parts[1]
        password = parts[2]

        # VULNERABLE: Hardcoded credentials
        valid_creds = {
            'svcadmin': 'service123',
            'operator': 'P@ssw0rd',
            'monitor': 'monitor',  # Hidden account
        }

        if username in valid_creds and valid_creds[username] == password:
            self.authenticated = True
            self.username = username
            self.send(f"Welcome, {username}! Type 'help' for commands.")
        else:
            self.send("Authentication failed.")

    def _handle_help(self):
        if self.authenticated:
            self.send("""
Available Commands:
  status        - Show service status
  info          - System information
  users         - List system users
  logs [n]      - Show last N log entries
  diagnostic    - Run network diagnostic
  exec <cmd>    - Execute maintenance command (admin only)
  config        - Show service configuration
  backup        - Trigger backup
  help          - Show this help
  quit          - Disconnect
""")
        else:
            self.send("""
Available Commands (unauthenticated):
  auth <user> <pass>  - Authenticate
  help                - Show this help
  quit                - Disconnect
""")


def handle_client(conn, addr):
    try:
        handler = ServiceHandler(conn, addr)
        handler.handle()
    except Exception as e:
        logger.error(f"Handler error for {addr}: {e}")
    finally:
        conn.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(MAX_CONNECTIONS)

    logger.info(f"Service Bastion Management Console listening on {HOST}:{PORT}")

    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    while True:
        try:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
        except OSError:
            break


if __name__ == '__main__':
    main()
