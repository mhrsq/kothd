#!/usr/bin/env python3
"""
Initialize Data Vault with seed data.
Sets up Redis with structured data and credential breadcrumbs.
"""

import redis
import json
import hashlib
import os

REDIS_HOST = '127.0.0.1'
REDIS_PORT = 6379
REDIS_PASS = 'VaultR3dis2026'

def init_redis():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS, decode_responses=True)

    # ── Users ────────────────────────────────────────────────────────────
    users = {
        'admin': {
            'username': 'admin',
            'password': hashlib.md5(b'V4ultAdm1n!').hexdigest(),
            'password_plain': 'V4ultAdm1n!',  # VULNERABLE: plaintext stored
            'role': 'admin',
            'email': 'admin@vault.local',
        },
        'operator': {
            'username': 'operator',
            'password': hashlib.md5(b'0per4t0r#2026').hexdigest(),
            'password_plain': '0per4t0r#2026',
            'role': 'operator',
            'email': 'ops@vault.local',
        },
        'backup': {
            'username': 'backup',
            'password': hashlib.md5(b'bkp_user_123').hexdigest(),
            'password_plain': 'bkp_user_123',
            'role': 'backup',
            'email': 'backup@vault.local',
        },
        'monitor': {
            'username': 'monitor',
            'password': hashlib.md5(b'monitor').hexdigest(),
            'password_plain': 'monitor',
            'role': 'readonly',
            'email': 'monitor@vault.local',
        },
    }

    for name, data in users.items():
        r.hset(f'user:{name}', mapping=data)

    # ── Secrets vault ────────────────────────────────────────────────────
    secrets = {
        'db-master-key': {
            'value': 'MASTER-KEY-2026-vault-prod',
            'owner': 'admin',
            'created': '2026-01-15',
        },
        'ssh-private-key': {
            'value': '-----BEGIN RSA PRIVATE KEY-----\nFAKE_KEY_FOR_CTF_CHALLENGE\n-----END RSA PRIVATE KEY-----',
            'owner': 'admin',
            'created': '2026-02-01',
        },
        'api-token': {
            'value': 'vault-api-tok-8f7d6e5c4b3a',
            'owner': 'operator',
            'created': '2026-03-10',
        },
        'backup-encryption': {
            'value': 'aes256-key-bkp-v4ult-2026',
            'owner': 'backup',
            'created': '2026-01-20',
        },
        'system-credentials': {
            'value': json.dumps({
                'ssh_root': 'd4tav4ult_r00t',
                'dbadmin': 'db@dmin2026',
                'redis': 'VaultR3dis2026',
            }),
            'owner': 'admin',
            'created': '2026-01-01',
        },
    }

    for name, data in secrets.items():
        r.hset(f'secret:{name}', mapping=data)

    # ── Configuration ────────────────────────────────────────────────────
    config = {
        'version': '4.1.0',
        'debug_mode': 'true',
        'allow_remote_backup': 'true',
        'serialization_format': 'pickle',
        'max_connections': '100',
        'auth_method': 'md5',
        'vault_master_password': 'V4ult-M4st3r-2026!',
    }

    for k, v in config.items():
        r.hset('config', k, v)

    # ── Session tokens (breadcrumbs) ─────────────────────────────────────
    r.set('session:admin:current', 'sess-adm-1a2b3c4d5e6f')
    r.set('session:operator:current', 'sess-ops-7g8h9i0j1k2l')

    # ── VULNERABLE: Serialized data (pickle) ─────────────────────────────
    r.set('serialized:backup_config', json.dumps({
        'note': 'Backup configs are deserialized with pickle - see /opt/vault/services/vault_service.py',
        'format': 'base64-encoded pickle',
    }))

    print("[+] Redis data initialized successfully")
    print(f"    Users: {len(users)}")
    print(f"    Secrets: {len(secrets)}")
    print(f"    Config entries: {len(config)}")

if __name__ == '__main__':
    try:
        init_redis()
    except Exception as e:
        print(f"[-] Init failed: {e}")
        print("    Redis may not be ready yet, will retry on service start")
