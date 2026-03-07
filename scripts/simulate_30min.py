#!/usr/bin/env python3
"""
KoTH CTF — 30-Minute Realistic Simulation
==========================================
Simulates 6 teams attacking 4 hills with realistic attack/defense/patch patterns.

Uses HOST SSH + docker exec for reliability (container SSH may be flaky).
Run on the scoreboard server (178.128.222.1).
"""

import subprocess
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("simulation")

# ── Configuration ────────────────────────────────────────────────────────────
# Each hill: host IP, host SSH pass, container name
HILLS = {
    1: {
        "name": "Web Fortress",
        "host_ip": "165.22.149.130",
        "host_pwd": "anonyM404.a",
        "container": "hill1-web-fortress",
    },
    2: {
        "name": "Service Bastion",
        "host_ip": "165.227.10.119",
        "host_pwd": "anonyM404.a",
        "container": "hill2-service-bastion",
    },
    3: {
        "name": "API Gateway",
        "host_ip": "165.227.16.235",
        "host_pwd": "anonyM404.a",
        "container": "hill3-api-gateway",
    },
    4: {
        "name": "Data Vault",
        "host_ip": "129.212.235.51",
        "host_pwd": "anonyM404.a",
        "container": "hill4-data-vault",
    },
}

# Simulation timeline
TIMELINE = {
    # ── Phase 1: First Blood (Ticks 1-5) ──
    3: [(2, "GarudaCyber")],
    4: [(4, "ZeroDaySquad"), (1, "BugHunters")],
    5: [(3, "GarudaCyber"), (4, "CyberTNI-1")],

    # ── Phase 2: Active Exploitation (Ticks 6-12) ──
    6: [(4, "ZeroDaySquad"), (2, "ByteForce")],
    7: [(2, "GarudaCyber"), (1, "RajawaliBiru")],
    8: [(1, "BugHunters"), (3, "CyberTNI-1")],
    9: [(3, "ZeroDaySquad")],
    10: [(1, "GarudaCyber"), (4, "ByteForce")],
    11: [(4, "RajawaliBiru"), (3, "BugHunters")],
    12: [(3, "CyberTNI-1"), (1, "ZeroDaySquad")],

    # ── Phase 3: Patching & Defense (Ticks 13-20) ──
    13: [(1, "GarudaCyber")],
    14: [(2, "ZeroDaySquad")],
    16: [(1, "BugHunters")],
    17: [(1, "GarudaCyber")],
    18: [(3, "RajawaliBiru")],
    19: [(4, "ByteForce")],
    20: [(3, "CyberTNI-1")],

    # ── Phase 4: Counter-attacks (Ticks 21-25) ──
    21: [(1, "ZeroDaySquad")],
    22: [(1, "GarudaCyber"), (4, "GarudaCyber")],
    23: [(2, "BugHunters")],
    24: [(3, "ZeroDaySquad")],
    25: [(3, "GarudaCyber")],

    # ── Phase 5: Frozen (Ticks 26-30) ──
    26: [(2, "CyberTNI-1")],
    27: [(4, "ZeroDaySquad")],
}


def write_king(hill_id, team_name):
    """Write team name to king.txt via host SSH + docker exec"""
    h = HILLS[hill_id]
    remote_cmd = f"docker exec {h['container']} bash -c \"echo '{team_name}' > /root/king.txt\""
    cmd = [
        "sshpass", "-p", h["host_pwd"],
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=8",
        f"root@{h['host_ip']}",
        remote_cmd,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            log.info(f"  ✅ Hill {hill_id} ({h['name']}): king → {team_name}")
        else:
            log.warning(f"  ❌ Hill {hill_id} ({h['name']}): Failed: {result.stderr.strip()[:100]}")
    except subprocess.TimeoutExpired:
        log.warning(f"  ❌ Hill {hill_id} ({h['name']}): Timeout")
    except Exception as e:
        log.warning(f"  ❌ Hill {hill_id} ({h['name']}): Error: {e}")


def reset_all_kings():
    """Reset all hills to 'nobody'"""
    log.info("Resetting all king.txt to 'nobody'...")
    for hill_id in HILLS:
        write_king(hill_id, "nobody")


def main():
    log.info("=" * 60)
    log.info("KoTH CTF — 30-Minute Realistic Simulation")
    log.info("=" * 60)
    log.info(f"Hills: {len(HILLS)}, Timeline: {len(TIMELINE)} tick events")
    log.info("")

    reset_all_kings()
    log.info("")

    tick_interval = 60
    max_ticks = 30

    log.info(f"Starting simulation ({max_ticks} ticks × {tick_interval}s)")
    log.info("Waiting 10s for first tick to process...")
    time.sleep(10)

    for tick in range(1, max_ticks + 1):
        log.info(f"{'─' * 40}")
        log.info(f"TICK {tick:02d}/{max_ticks}")

        if tick in TIMELINE:
            changes = TIMELINE[tick]
            log.info(f"  {len(changes)} change(s):")
            for hill_id, team_name in changes:
                write_king(hill_id, team_name)
        else:
            log.info(f"  No changes — teams holding")

        if tick <= 2:
            log.info("  📍 Recon phase")
        elif tick <= 5:
            log.info("  📍 First Blood")
        elif tick <= 12:
            log.info("  ⚔️  Active exploitation")
        elif tick <= 20:
            log.info("  🔒 Patching & defense")
        elif tick <= 25:
            log.info("  💥 Counter-attacks")
        else:
            log.info("  🧊 FROZEN scoreboard")

        if tick < max_ticks:
            log.info(f"  ⏳ Next tick in {tick_interval}s...")
            time.sleep(tick_interval)

    log.info("=" * 60)
    log.info("SIMULATION COMPLETE!")
    log.info("Final state:")
    log.info("  Hill 1: GarudaCyber (TNI)")
    log.info("  Hill 2: CyberTNI-1 (TNI)")
    log.info("  Hill 3: GarudaCyber (TNI)")
    log.info("  Hill 4: ZeroDaySquad (Umum)")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
