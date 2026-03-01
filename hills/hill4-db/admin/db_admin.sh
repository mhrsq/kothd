#!/bin/bash
# Data Vault Admin Script
# Can be run with sudo by dbadmin: sudo /opt/vault/admin/db_admin.sh <action>
#
# VULNERABILITY: The 'query' action passes user input to eval
# VULNERABILITY: The 'log' action appends to arbitrary files

ACTION=$1
shift

case "$ACTION" in
    status)
        echo "[*] Data Vault Status"
        echo "    Redis: $(redis-cli -a VaultR3dis2026 --no-auth-warning ping 2>/dev/null)"
        echo "    Vault PID: $(pgrep -f vault_service.py)"
        echo "    Disk: $(df -h /opt/vault/data | tail -1)"
        ;;
    
    flush)
        echo "[*] Flushing Redis cache..."
        redis-cli -a VaultR3dis2026 --no-auth-warning FLUSHDB
        echo "[+] Done"
        ;;
    
    backup)
        echo "[*] Running backup..."
        redis-cli -a VaultR3dis2026 --no-auth-warning BGSAVE
        cp /opt/vault/data/dump.rdb "/opt/vault/backups/dump_$(date +%Y%m%d_%H%M%S).rdb"
        echo "[+] Backup saved"
        ;;
    
    query)
        # VULNERABLE: eval on user input
        QUERY="$*"
        echo "[*] Executing query: $QUERY"
        eval "$QUERY"
        ;;
    
    log)
        # VULNERABLE: append to arbitrary file
        LOGFILE="$1"
        shift
        MESSAGE="$*"
        echo "[$(date)] $MESSAGE" >> "$LOGFILE"
        echo "[+] Logged to $LOGFILE"
        ;;
    
    restart)
        echo "[*] Restarting vault service..."
        pkill -f vault_service.py
        sleep 1
        python3 /opt/vault/services/vault_service.py &
        echo "[+] Vault restarted"
        ;;

    *)
        echo "Usage: db_admin.sh <action> [args]"
        echo "Actions:"
        echo "  status   - Show service status"
        echo "  flush    - Flush Redis cache"
        echo "  backup   - Create Redis backup"
        echo "  query    - Execute a query"
        echo "  log      - Write to log file"
        echo "  restart  - Restart vault service"
        ;;
esac
