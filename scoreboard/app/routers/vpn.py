"""
KoTH CTF Platform — VPN (WireGuard) Config Generator
Auto-generates WireGuard configs per team with auto-assigned IPs.
Now integrated with auto-generation on registration via vpn_manager service.
"""
import json
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Team, GameConfig, AuditLog
from app.services.vpn_manager import (
    generate_team_vpn_config,
    get_team_vpn_config,
    get_full_server_config,
    apply_peer_to_vpn_server,
    VPN_SERVER_PUBLIC_IP,
    VPN_LISTEN_PORT,
    VPN_NETWORK,
    VPN_DNS,
    VPN_ALLOWED_IPS,
    _generate_wg_keypair,
    _generate_preshared_key,
    _derive_public_key,
)

logger = logging.getLogger("koth.vpn")
router = APIRouter(tags=["vpn"])
settings = get_settings()


def require_admin(x_admin_token: str = Header(...)):
    if x_admin_token != settings.api_admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return True


# ─── Admin: Generate all VPN configs ────────────────────────────────────────

@router.post("/api/admin/vpn/generate")
async def generate_vpn_configs(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """
    Generate WireGuard server config + per-team client configs.
    Auto-assigns VPN IPs starting from 10.10.0.2.
    Stores keys in game_config and updates each team's vpn_ip.
    """
    # Get all active teams
    result = await db.execute(
        select(Team).where(Team.is_active == True).order_by(Team.id)
    )
    teams = result.scalars().all()

    if not teams:
        raise HTTPException(status_code=400, detail="No active teams found")

    # Check if server keypair already exists (reuse to avoid breaking existing conns)
    server_cfg = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_private_key")
    )
    existing_server_key = server_cfg.scalar_one_or_none()

    if existing_server_key:
        server_private = existing_server_key.value
        # Derive public from private
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        priv_bytes = base64.b64decode(server_private)
        priv_key = X25519PrivateKey.from_private_bytes(priv_bytes)
        pub_bytes = priv_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        server_public = base64.b64encode(pub_bytes).decode()
        logger.info("Reusing existing WireGuard server keypair")
    else:
        server_private, server_public = _generate_wg_keypair()
        # Store server private key
        db.add(GameConfig(
            key="wg_server_private_key",
            value=server_private,
            description="WireGuard server private key",
        ))
        logger.info("Generated new WireGuard server keypair")

    # Store/update server public key
    pub_cfg = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_public_key")
    )
    existing_pub = pub_cfg.scalar_one_or_none()
    if existing_pub:
        existing_pub.value = server_public
    else:
        db.add(GameConfig(
            key="wg_server_public_key",
            value=server_public,
            description="WireGuard server public key",
        ))

    # Generate per-team configs
    team_configs = {}
    server_peers = []

    for idx, team in enumerate(teams):
        ip_suffix = idx + 2  # .2, .3, .4, ...
        if ip_suffix > 254:
            logger.warning(f"Skipping team {team.name}: IP range exhausted")
            continue

        vpn_ip = f"{VPN_NETWORK}.{ip_suffix}"

        # Check if team already has keys stored
        key_cfg = await db.execute(
            select(GameConfig).where(
                GameConfig.key == f"wg_team_{team.id}_private_key"
            )
        )
        existing_team_key = key_cfg.scalar_one_or_none()

        if existing_team_key:
            team_private = existing_team_key.value
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from cryptography.hazmat.primitives import serialization
            priv_bytes = base64.b64decode(team_private)
            priv_key = X25519PrivateKey.from_private_bytes(priv_bytes)
            pub_bytes = priv_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            team_public = base64.b64encode(pub_bytes).decode()
        else:
            team_private, team_public = _generate_wg_keypair()
            db.add(GameConfig(
                key=f"wg_team_{team.id}_private_key",
                value=team_private,
                description=f"WireGuard private key for team {team.name}",
            ))

        psk = _generate_preshared_key()

        # Store preshared key
        psk_cfg = await db.execute(
            select(GameConfig).where(
                GameConfig.key == f"wg_team_{team.id}_psk"
            )
        )
        existing_psk = psk_cfg.scalar_one_or_none()
        if existing_psk:
            psk = existing_psk.value
        else:
            db.add(GameConfig(
                key=f"wg_team_{team.id}_psk",
                value=psk,
                description=f"WireGuard PSK for team {team.name}",
            ))

        # Update team VPN IP
        team.vpn_ip = vpn_ip

        # Client config
        client_conf = (
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

        team_configs[str(team.id)] = {
            "team_name": team.name,
            "display_name": team.display_name,
            "vpn_ip": vpn_ip,
            "public_key": team_public,
            "config": client_conf,
        }

        # Server peer block
        server_peers.append(
            f"# {team.display_name or team.name} ({vpn_ip})\n"
            f"[Peer]\n"
            f"PublicKey = {team_public}\n"
            f"PresharedKey = {psk}\n"
            f"AllowedIPs = {vpn_ip}/32\n"
        )

    # Build server config
    server_conf = (
        f"[Interface]\n"
        f"PrivateKey = {server_private}\n"
        f"Address = {VPN_NETWORK}.1/24\n"
        f"ListenPort = {VPN_LISTEN_PORT}\n"
        f"PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; "
        f"iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE\n"
        f"PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; "
        f"iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE\n"
        f"\n"
        + "\n".join(server_peers)
    )

    # Store server config
    srv_conf_row = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_config")
    )
    existing_srv = srv_conf_row.scalar_one_or_none()
    if existing_srv:
        existing_srv.value = server_conf
    else:
        db.add(GameConfig(
            key="wg_server_config",
            value=server_conf,
            description="WireGuard server wg0.conf",
        ))

    # Store team configs JSON
    configs_row = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_team_configs")
    )
    existing_configs = configs_row.scalar_one_or_none()
    configs_json = json.dumps(team_configs)
    if existing_configs:
        existing_configs.value = configs_json
    else:
        db.add(GameConfig(
            key="wg_team_configs",
            value=configs_json,
            description="WireGuard client configs JSON (all teams)",
        ))

    # Audit
    db.add(AuditLog(
        event_type="vpn_configs_generated",
        actor="admin",
        details={"teams_count": len(team_configs)},
    ))

    await db.commit()

    logger.info(f"Generated WireGuard configs for {len(team_configs)} teams")

    return {
        "status": "ok",
        "teams_configured": len(team_configs),
        "server_public_key": server_public,
        "server_endpoint": f"{VPN_SERVER_PUBLIC_IP}:{VPN_LISTEN_PORT}",
        "server_config_preview": server_conf[:500] + "...",
        "team_assignments": [
            {"team_id": int(tid), "team_name": cfg["team_name"], "vpn_ip": cfg["vpn_ip"]}
            for tid, cfg in team_configs.items()
        ],
    }


# ─── Admin: Download server config ──────────────────────────────────────────

@router.get("/api/admin/vpn/server-config")
async def download_server_config(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Download the WireGuard server config (wg0.conf)."""
    result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_server_config")
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="VPN configs not generated yet. Run POST /api/admin/vpn/generate first.")

    return PlainTextResponse(
        content=row.value,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=wg0.conf"},
    )


# ─── Admin: Download specific team config ───────────────────────────────────

@router.get("/api/admin/vpn/team-config/{team_id}")
async def admin_download_team_config(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Admin downloads a specific team's WireGuard config."""
    result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_team_configs")
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="VPN configs not generated yet")

    configs = json.loads(row.value)
    team_cfg = configs.get(str(team_id))
    if not team_cfg:
        raise HTTPException(status_code=404, detail="Config not found for this team")

    safe_name = team_cfg["team_name"].replace(" ", "-").lower()
    return PlainTextResponse(
        content=team_cfg["config"],
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="wg-{safe_name}.conf"'},
    )


# ─── Team: Download own config ──────────────────────────────────────────────

@router.get("/api/vpn/my-config")
async def download_my_vpn_config(
    x_team_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Team downloads their own WireGuard config.
    Authenticated via X-Team-Token header.
    """
    # Verify team token
    team_result = await db.execute(
        select(Team).where(Team.token == x_team_token, Team.is_active == True)
    )
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=401, detail="Invalid team token")

    # Get configs
    result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_team_configs")
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="VPN config belum digenerate oleh panitia. Hubungi panitia.",
        )

    configs = json.loads(row.value)
    team_cfg = configs.get(str(team.id))
    if not team_cfg:
        raise HTTPException(
            status_code=404,
            detail="Config VPN untuk team Anda belum tersedia. Hubungi panitia.",
        )

    safe_name = team.name.replace(" ", "-").lower()
    return PlainTextResponse(
        content=team_cfg["config"],
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="wg-{safe_name}.conf"'},
    )


# ─── Admin: Sync server config (rebuild from all peers) ─────────────────────

@router.post("/api/admin/vpn/sync-server")
async def sync_vpn_server_config(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """
    Rebuild the full WireGuard server config from all stored peer data.
    Use this after adding teams to regenerate wg0.conf.
    """
    server_conf = await get_full_server_config(db)
    if not server_conf:
        raise HTTPException(status_code=404, detail="No server keypair found. Register a team first.")

    await db.commit()

    return {
        "status": "ok",
        "message": "Server config rebuilt from all registered peers",
        "config_preview": server_conf[:500] + "..." if len(server_conf) > 500 else server_conf,
    }


# ─── Admin: Generate missing VPN configs ─────────────────────────────────────

@router.post("/api/admin/vpn/generate-missing")
async def generate_missing_vpn_configs(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """
    Generate VPN configs for teams that don't have one yet.
    Useful for teams registered before auto-generation was enabled.
    """
    result = await db.execute(
        select(Team).where(Team.is_active == True).order_by(Team.id)
    )
    teams = result.scalars().all()

    generated = []
    skipped = []

    for team in teams:
        # Check if config exists
        existing = await get_team_vpn_config(db, team.id)
        if existing:
            skipped.append({"team_id": team.id, "team_name": team.name, "vpn_ip": team.vpn_ip})
            continue

        try:
            vpn_result = await generate_team_vpn_config(db, team)
            generated.append({
                "team_id": team.id,
                "team_name": team.name,
                "vpn_ip": vpn_result["vpn_ip"],
            })

            # Hot-add to VPN server
            try:
                await apply_peer_to_vpn_server(
                    team_public_key=vpn_result["public_key"],
                    psk=vpn_result["psk"],
                    vpn_ip=vpn_result["vpn_ip"],
                )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Failed to generate VPN for team {team.name}: {e}")

    db.add(AuditLog(
        event_type="vpn_missing_generated",
        actor="admin",
        details={"generated": len(generated), "skipped": len(skipped)},
    ))
    await db.commit()

    return {
        "status": "ok",
        "generated": generated,
        "skipped": skipped,
        "total_generated": len(generated),
        "total_skipped": len(skipped),
    }


# ─── Admin: VPN status overview ──────────────────────────────────────────────

@router.get("/api/admin/vpn/status")
async def vpn_status(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Get an overview of VPN config status for all teams."""
    result = await db.execute(
        select(Team).where(Team.is_active == True).order_by(Team.id)
    )
    teams = result.scalars().all()

    configs_result = await db.execute(
        select(GameConfig).where(GameConfig.key == "wg_team_configs")
    )
    configs_row = configs_result.scalar_one_or_none()
    configs = json.loads(configs_row.value) if configs_row else {}

    team_status = []
    for team in teams:
        has_config = str(team.id) in configs
        team_status.append({
            "team_id": team.id,
            "team_name": team.name,
            "display_name": team.display_name,
            "vpn_ip": team.vpn_ip,
            "config_generated": has_config,
        })

    return {
        "total_teams": len(teams),
        "configs_generated": sum(1 for t in team_status if t["config_generated"]),
        "configs_missing": sum(1 for t in team_status if not t["config_generated"]),
        "vpn_server": VPN_SERVER_PUBLIC_IP,
        "vpn_port": VPN_LISTEN_PORT,
        "teams": team_status,
    }
