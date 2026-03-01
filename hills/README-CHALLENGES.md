# KoTH Challenge Hills

> Overview of all challenge machines in the KoTH CTF platform.

## Hill Summary

| Hill | Name | Ports | SLA Check | Theme |
|------|------|-------|-----------|-------|
| 1 | Web Fortress | 80, 22 | HTTP GET :80/health | Vulnerable web application |
| 2 | Service Bastion | 9999, 21, 22 | TCP connect :9999 | Multi-service exploitation |
| 3 | API Gateway | 8080, 22 | HTTP GET :8080/api/v1/health | REST API vulnerabilities |
| 4 | Data Vault | 27017, 6379, 22 | TCP connect :27017 | Database / NoSQL exploitation |

> **Note**: Hills 3 and 4 run on the same Pivot DMZ server, differentiated by ports. Scorebot SSHes to port 2210 (Hill 3) and 2211 (Hill 4).

---

## Hill 1 — Web Fortress

A vulnerable web application with multiple attack vectors.

**Vulnerabilities:**
1. **SQL Injection** — Login form and search endpoint
2. **File Upload Bypass** — MIME type check only, original filename preserved
3. **Command Injection** — Admin diagnostic endpoint
4. **IDOR** — Profile endpoint exposes other users' data
5. **Directory Listing** — Nginx serves uploads directory with autoindex

**Privilege Escalation:** SUID binary calls `system()` with relative path — create a fake binary in `/tmp` and prepend to `PATH`.

**Goal:** Gain root access and write your team name to `/root/king.txt`.

**Source:** `hills/hill1-web/`

---

## Hill 2 — Service Bastion

A multi-service box with FTP, a custom TCP service, and SSH.

**Vulnerabilities:**
1. **FTP Anonymous Access** — Exposes credential backup file
2. **Authentication Bypass** — TCP service has a debug backdoor
3. **Command Injection** — Diagnostic command in TCP service
4. **Weak Credentials** — Multiple services with default passwords

**Privilege Escalation:** Writable cron job or SUID binary (depends on configuration).

**Goal:** Gain root access and write your team name to `/root/king.txt`.

**Source:** `hills/hill2-services/`

---

## Hill 3 — API Gateway

A REST API with authentication and authorization flaws.

**Vulnerabilities:**
1. **Authentication Bypass** — Weak JWT validation
2. **SSRF** — Internal endpoint proxy
3. **Path Traversal** — File access endpoint
4. **Admin Endpoint Exposure** — Hidden admin tool

**Privilege Escalation:** Admin tool allows command execution, escalate from app user to root.

**Goal:** Gain root access and write your team name to `/root/king.txt`.

**Source:** `hills/hill3-api/`

---

## Hill 4 — Data Vault

A database-centric challenge with MongoDB and Redis.

**Vulnerabilities:**
1. **NoSQL Injection** — MongoDB query manipulation
2. **Redis Unauthenticated Access** — No password on Redis
3. **Backup Script Injection** — Admin maintenance scripts with injection flaws
4. **Weak File Permissions** — Sensitive files readable by low-privilege users

**Privilege Escalation:** SUID backup utility with command injection.

**Goal:** Gain root access and write your team name to `/root/king.txt`.

**Source:** `hills/hill4-db/`

---

## Pivot DMZ

Hills 3 and 4 share a single host (the Pivot DMZ server). Port mapping:

| Hill | SSH Port | Service Port |
|------|----------|-------------|
| Hill 3 (API Gateway) | 2210 → 22 | 8080 → 8080 |
| Hill 4 (Data Vault) | 2211 → 22 | 27017 → 27017 |

**Source:** `hills/pivot-dmz/`

---

## Adding Custom Hills

To add your own challenge:

1. Create a directory under `hills/` with a `Dockerfile` and `docker-compose.yml`
2. Ensure SSH is running (scorebot needs to read `/root/king.txt`)
3. Include a health endpoint for SLA checks
4. Register the hill via the admin API:

```bash
curl -X POST http://YOUR_SERVER/api/admin/hills \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Custom Hill",
    "ip": "HILL_IP",
    "ssh_port": 22,
    "sla_url": "http://HILL_IP:PORT/health",
    "points": 10
  }'
```

5. Deploy the hill agent (optional) for real-time status:

```bash
cd hill-agent
./deploy.sh --server http://KOTH_SERVER:8000 --hill-id N
```
