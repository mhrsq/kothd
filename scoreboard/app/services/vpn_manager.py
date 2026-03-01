"""
KoTH CTF Platform — VPN Manager Service
Auto-generates WireGuard configs per-team on registration.
Handles server key management and peer provisioning.
"""
import os
import json
import base64
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, GameConfig, AuditLog

logger = logging.getLogger("koth.vpn_manager")

# ─── VPN Constants ───────────────────────────────────────────────────────────
VPN_SERVER_PUBLIC_IP = os.getenv("VPN_SERVER_PUBLIC_IP", "")
VPN_LISTEN_PORT = int(os.getenv("VPN_PORT", "51820"))
VPN_NETWORK = "10.10.0"           # /24 — .1 = server, .2+ = teams
VPN_DNS = "1.1.1.1, 8.8.8.8"
VPN_ALLOWED_IPS = os.getenv("VPN_ALLOWED_IPS", "10.10.0.0/24")


def _generate_wg_keypair() -> Tuple[str, str]:
    """Generate a WireGuard X25519 keypair."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    private_key = X25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return (
        base64.b64encode(private_bytes).decode(),
        base64.b64encode(public_bytes).decode(),
    )


def _derive_public_key(private_b64: str) -> str:
    """Derive public key from a base64-encoded private key."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    priv_bytes = base64.b64decode(private_b64)
    priv_key = X25519PrivateKey.from_private_bytes(priv_bytes)
    pub_bytes = priv_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(pub_bytes).decode()


def _generate_preshared_key() -> str:
    """Generate a WireGuard preshared key (32 random bytes, base64)."""
    return base64.b64encode(os.urandom(32)).decode()


async def _ensure_server_keypair(db: AsyncSession) -> Tuple[str, str]:
    """
    Ensure the WireGuard server keypair exists in DB.
    Returns (server_private, server_public).
    """
    result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_private_key")
    )
    existing = result.scalar_one_or_none()

    if existing:
        server_private = existing.value
        server_public = _derive_public_key(server_private)
    else:
        server_private, server_public = _generate_wg_keypair()
        db.add(GameConfig(
            key="wg_server_private_key",
            value=server_private,
            description="WireGuard server private key (auto-generated)",
        ))
        db.add(GameConfig(
            key="wg_server_public_key",
            value=server_public,
            description="WireGuard server public key",
        ))
        logger.info("Generated new WireGuard server keypair")

    # Upsert public key
    pub_result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_public_key")
    )
    pub_row = pub_result.scalar_one_or_none()
    if pub_row:
        pub_row.value = server_public
    else:
        db.add(GameConfig(
            key="wg_server_public_key",
            value=server_public,
            description="WireGuard server public key",
        ))

    return server_private, server_public


async def _assign_vpn_ip(db: AsyncSession, team_id: int) -> str:
    """
    Assign a unique VPN IP to a team.
    Uses team_id + 1 as the IP suffix (team_id=1 → .2, team_id=2 → .3, etc.)
    If that IP conflicts, find the next available one.
    """
    # Start with team_id + 1 as the candidate
    candidate_suffix = team_id + 1

    # Get all assigned VPN IPs
    result = await db.execute(
        select(Team.vpn_ip).where(Team.vpn_ip.isnot(None), Team.is_active == True)
    )
    assigned_ips = {row[0] for row in result.fetchall()}

    # Find an available IP
    for suffix in range(candidate_suffix, 255):
        ip = f"{VPN_NETWORK}.{suffix}"
        if ip not in assigned_ips:
            return ip

    raise RuntimeError("VPN IP address pool exhausted (max 253 teams)")


async def generate_team_vpn_config(
    db: AsyncSession,
    team: Team,
) -> dict:
    """
    Generate WireGuard config for a single team.
    Called during team registration.
    Returns dict with {vpn_ip, config, public_key, psk}.
    """
    # 1. Ensure server keypair
    server_private, server_public = await _ensure_server_keypair(db)

    # 2. Assign VPN IP
    vpn_ip = await _assign_vpn_ip(db, team.id)
    team.vpn_ip = vpn_ip

    # 3. Generate team keypair
    team_private, team_public = _generate_wg_keypair()
    db.add(GameConfig(
        key=f"wg_team_{team.id}_private_key",
        value=team_private,
        description=f"WireGuard private key for team {team.name}",
    ))
    db.add(GameConfig(
        key=f"wg_team_{team.id}_public_key",
        value=team_public,
        description=f"WireGuard public key for team {team.name}",
    ))

    # 4. Generate PSK
    psk = _generate_preshared_key()
    db.add(GameConfig(
        key=f"wg_team_{team.id}_psk",
        value=psk,
        description=f"WireGuard PSK for team {team.name}",
    ))

    # 5. Build client config
    client_conf = (
        f"# KoTH CTF — WireGuard Config\n"
        f"# Team: {team.display_name or team.name}\n"
        f"# Generated automatically on registration\n"
        f"\n"
        f"[Interface]\n"
        f"PrivateKey = {team_private}\n"
        f"Address = {vpn_ip}/24\n"
        f"DNS = {VPN_DNS}\n"
        f"\n"
        f"[Peer]\n"
        f"PublicKey = {server_public}\n"
        f"PresharedKey = {psk}\n"
        f"Endpoint = {VPN_SERVER_PUBLIC_IP}:{VPN_LISTEN_PORT}\n"
        f"AllowedIPs = {VPN_ALLOWED_IPS}\n"
        f"PersistentKeepalive = 25\n"
    )

    # 6. Store in wg_team_configs JSON (for compatibility with existing endpoints)
    configs_result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_team_configs")
    )
    configs_row = configs_result.scalar_one_or_none()

    team_entry = {
        "team_name": team.name,
        "display_name": team.display_name,
        "vpn_ip": vpn_ip,
        "public_key": team_public,
        "config": client_conf,
    }

    if configs_row:
        existing_configs = json.loads(configs_row.value)
        existing_configs[str(team.id)] = team_entry
        configs_row.value = json.dumps(existing_configs)
    else:
        new_configs = {str(team.id): team_entry}
        db.add(GameConfig(
            key="wg_team_configs",
            value=json.dumps(new_configs),
            description="WireGuard client configs JSON (all teams)",
        ))

    # 7. Store server peer entry for this team
    peer_block = (
        f"# {team.display_name or team.name} ({vpn_ip})\n"
        f"[Peer]\n"
        f"PublicKey = {team_public}\n"
        f"PresharedKey = {psk}\n"
        f"AllowedIPs = {vpn_ip}/32\n"
    )

    # Append to server peers list
    peers_result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_peers")
    )
    peers_row = peers_result.scalar_one_or_none()
    if peers_row:
        existing_peers = json.loads(peers_row.value)
        existing_peers[str(team.id)] = peer_block
        peers_row.value = json.dumps(existing_peers)
    else:
        db.add(GameConfig(
            key="wg_server_peers",
            value=json.dumps({str(team.id): peer_block}),
            description="WireGuard server peer blocks per team",
        ))

    logger.info(f"Generated VPN config for team {team.name} → {vpn_ip}")

    return {
        "vpn_ip": vpn_ip,
        "config": client_conf,
        "public_key": team_public,
        "psk": psk,
        "peer_block": peer_block,
    }


async def get_team_vpn_config(db: AsyncSession, team_id: int) -> Optional[str]:
    """Get a team's WireGuard config from DB. Returns config string or None."""
    result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_team_configs")
    )
    row = result.scalar_one_or_none()
    if not row:
        return None

    configs = json.loads(row.value)
    team_cfg = configs.get(str(team_id))
    return team_cfg["config"] if team_cfg else None


async def get_full_server_config(db: AsyncSession) -> Optional[str]:
    """
    Build the full WireGuard server config from stored data.
    Combines server interface config with all team peer blocks.
    """
    # Get server private key
    priv_result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_private_key")
    )
    priv_row = priv_result.scalar_one_or_none()
    if not priv_row:
        return None

    server_private = priv_row.value

    # Get all peer blocks
    peers_result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_peers")
    )
    peers_row = peers_result.scalar_one_or_none()
    peer_blocks = ""
    if peers_row:
        peers_dict = json.loads(peers_row.value)
        peer_blocks = "\n".join(peers_dict.values())

    server_conf = (
        f"# KoTH CTF — WireGuard Server Config\n"
        f"# Auto-generated — do not edit manually\n"
        f"\n"
        f"[Interface]\n"
        f"PrivateKey = {server_private}\n"
        f"Address = {VPN_NETWORK}.1/24\n"
        f"ListenPort = {VPN_LISTEN_PORT}\n"
        f"PostUp = sysctl -w net.ipv4.ip_forward=1; "
        f"iptables -A FORWARD -i wg0 -j ACCEPT; "
        f"iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE\n"
        f"PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; "
        f"iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE\n"
        f"\n"
        f"{peer_blocks}"
    )

    # Also store/update the wg_server_config key for compatibility
    srv_cfg_result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_config")
    )
    srv_cfg_row = srv_cfg_result.scalar_one_or_none()
    if srv_cfg_row:
        srv_cfg_row.value = server_conf
    else:
        db.add(GameConfig(
            key="wg_server_config",
            value=server_conf,
            description="WireGuard server wg0.conf (auto-built)",
        ))

    return server_conf


async def apply_peer_to_vpn_server(
    team_public_key: str,
    psk: str,
    vpn_ip: str,
) -> bool:
    """
    Hot-add a peer to the running WireGuard server via SSH.
    This adds the peer without restarting WireGuard.
    Returns True on success.
    """
    import asyncio

    vpn_server_ip = VPN_SERVER_PUBLIC_IP
    ssh_user = "root"
    ssh_pass = os.getenv("VPN_SSH_PASS", "")

    # Write PSK to temp file, add peer, then remove temp file
    # wg set wg0 peer <pubkey> preshared-key /tmp/psk.tmp allowed-ips <ip>/32
    cmd = (
        f"echo '{psk}' > /tmp/wg_psk_tmp && "
        f"wg set wg0 peer {team_public_key} "
        f"preshared-key /tmp/wg_psk_tmp "
        f"allowed-ips {vpn_ip}/32 && "
        f"rm -f /tmp/wg_psk_tmp && "
        f"echo 'PEER_ADDED_OK'"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "sshpass", "-p", ssh_pass,
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{ssh_user}@{vpn_server_ip}",
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
        output = stdout.decode().strip()

        if "PEER_ADDED_OK" in output:
            logger.info(f"Hot-added VPN peer {vpn_ip} to WireGuard server")
            return True
        else:
            logger.warning(f"VPN peer add may have failed: {output} | {stderr.decode()}")
            return False
    except asyncio.TimeoutError:
        logger.error("Timeout adding VPN peer via SSH")
        return False
    except FileNotFoundError:
        logger.warning("sshpass not found — skipping live VPN peer add (will need manual sync)")
        return False
    except Exception as e:
        logger.error(f"Error adding VPN peer: {e}")
        return False
