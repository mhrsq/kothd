#!/bin/bash
# Maintenance script - runs every 5 minutes via cron as root
# VULNERABLE: This file is world-writable (chmod 777)
# Attacker can replace contents with malicious commands
redis-cli -a VaultR3dis2026 --no-auth-warning BGSAVE
