"""
Command handler for Service Bastion TCP management console.
Contains multiple intentional vulnerabilities.
"""

import os
import subprocess
import socket
import platform


class CommandHandler:

    def execute(self, cmd, args, username):
        """Route command to handler method"""
        handlers = {
            'status': self._cmd_status,
            'info': self._cmd_info,
            'users': self._cmd_users,
            'logs': self._cmd_logs,
            'diagnostic': self._cmd_diagnostic,
            'exec': self._cmd_exec,
            'config': self._cmd_config,
            'backup': self._cmd_backup,
        }

        handler = handlers.get(cmd)
        if handler:
            return handler(args, username)
        return f"Unknown command: {cmd}. Type 'help' for available commands."

    def _cmd_status(self, args, username):
        """Show service status"""
        try:
            uptime = subprocess.check_output(['uptime'], text=True).strip()
        except:
            uptime = 'unknown'

        return f"""
=== Service Bastion Status ===
  Hostname:   {socket.gethostname()}
  Services:   TCP Console (9999), SSH (22), FTP (21)
  Status:     RUNNING
  Uptime:     {uptime}
  King File:  /root/king.txt
"""

    def _cmd_info(self, args, username):
        """VULNERABLE: Information disclosure — leaks sensitive system info"""
        try:
            kernel = subprocess.check_output(['uname', '-a'], text=True).strip()
            passwd_hint = subprocess.check_output(['head', '-5', '/etc/passwd'], text=True).strip()
            suid_files = subprocess.check_output(
                ['find', '/usr/local/bin', '-perm', '-4000'],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception as e:
            return f"Error gathering info: {e}"

        return f"""
=== System Information ===
  Kernel:     {kernel}
  Platform:   {platform.platform()}
  
=== User Accounts (partial) ===
{passwd_hint}

=== SUID Binaries ===
{suid_files or '  (none found)'}

=== Environment Hints ===
  Backup script: /opt/services/maintenance.sh (cron every 3 min)
  Service config: /opt/services/
  FTP pub: /srv/ftp/pub/
"""

    def _cmd_users(self, args, username):
        """List system users"""
        try:
            users = subprocess.check_output(
                ['grep', '-E', '/bin/(ba)?sh$', '/etc/passwd'],
                text=True
            ).strip()
        except:
            users = 'Unable to list users'

        return f"=== System Users (with shell) ===\n{users}"

    def _cmd_logs(self, args, username):
        """Show log entries — VULNERABLE: path traversal via log file arg"""
        n = 10
        log_file = '/var/log/syslog'

        if args:
            # VULNERABLE: First arg could be a path like /etc/shadow
            try:
                n = int(args[0])
            except ValueError:
                # If it's not a number, treat as filename (VULN: arbitrary file read)
                log_file = args[0]
                if len(args) > 1:
                    try:
                        n = int(args[1])
                    except:
                        pass

        try:
            result = subprocess.check_output(
                ['tail', f'-{n}', log_file],
                text=True, stderr=subprocess.STDOUT
            ).strip()
            return f"=== Last {n} lines of {log_file} ===\n{result}"
        except Exception as e:
            return f"Error reading logs: {e}"

    def _cmd_diagnostic(self, args, username):
        """VULNERABLE: Command injection in diagnostic ping"""
        if not args:
            return "Usage: diagnostic <host>"

        target = ' '.join(args)
        # VULNERABLE: Direct shell execution with user input
        try:
            cmd = f"ping -c 2 -W 2 {target} 2>&1"
            result = subprocess.check_output(cmd, shell=True, text=True, timeout=10)
            return f"=== Diagnostic: ping {target} ===\n{result}"
        except subprocess.TimeoutExpired:
            return "Diagnostic timed out"
        except subprocess.CalledProcessError as e:
            return f"=== Diagnostic output ===\n{e.output}"
        except Exception as e:
            return f"Diagnostic error: {e}"

    def _cmd_exec(self, args, username):
        """
        VULNERABLE: Command execution — 'admin only' but check is bypassable.
        The 'svcadmin' user can run arbitrary commands.
        """
        if username not in ('svcadmin', 'admin', 'root'):
            return "Error: Only admin users can execute commands"

        if not args:
            return "Usage: exec <command>"

        cmd = ' '.join(args)

        # "Whitelist" of allowed commands — but VULNERABLE: substring match
        # e.g., "systemctl status && cat /etc/shadow" matches "systemctl"
        allowed = ['systemctl', 'service', 'df', 'free', 'ps', 'netstat', 'ls', 'cat']
        if not any(a in cmd for a in allowed):
            return f"Error: Command not in whitelist: {allowed}"

        try:
            result = subprocess.check_output(
                cmd, shell=True, text=True, timeout=10,
                stderr=subprocess.STDOUT
            )
            return f"=== Output ===\n{result}"
        except subprocess.CalledProcessError as e:
            return f"=== Output (error) ===\n{e.output}"
        except Exception as e:
            return f"Execution error: {e}"

    def _cmd_config(self, args, username):
        """Show service configuration"""
        try:
            maint_content = open('/opt/services/maintenance.sh').read()
        except:
            maint_content = '(unable to read)'

        return f"""
=== Service Configuration ===
  TCP Port:         9999
  SSH Port:         22
  FTP Port:         21
  King File:        /root/king.txt
  Backup Script:    /opt/services/maintenance.sh
  Backup Schedule:  Every 3 minutes (cron)
  
=== maintenance.sh content ===
{maint_content}

=== Hint ===
  The maintenance script is writable and runs as root via cron.
  Backup output goes to /opt/backups/
"""

    def _cmd_backup(self, args, username):
        """Trigger manual backup"""
        try:
            result = subprocess.check_output(
                ['/opt/services/maintenance.sh'],
                text=True, timeout=10,
                stderr=subprocess.STDOUT
            )
            return f"Backup triggered.\n{result}"
        except Exception as e:
            return f"Backup failed: {e}"
