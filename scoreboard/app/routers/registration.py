"""
KoTH CTF Platform — Team Self-Registration Router
Allows teams to register themselves with a registration code.
Auto-generates WireGuard VPN config on registration.
"""
import asyncio
import secrets
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Team, TeamScore, AuditLog
from app.schemas import TeamRegisterRequest, TeamRegisterResponse
from app.services.vpn_manager import generate_team_vpn_config, apply_peer_to_vpn_server

logger = logging.getLogger("koth.registration")
router = APIRouter(prefix="/api/register", tags=["registration"])
settings = get_settings()


@router.get("/status")
async def registration_status():
    """Check if registration is open"""
    return {
        "registration_enabled": settings.registration_enabled,
        "categories": ["default"],
        "category_labels": {"default": "Default"},
    }


@router.post("", response_model=TeamRegisterResponse, status_code=201)
async def register_team(
    body: TeamRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Self-registration endpoint for teams.
    Teams must provide a valid registration_code to register.
    Returns team token that can be used for team-specific actions.
    """
    # Check if registration is enabled
    if not settings.registration_enabled:
        raise HTTPException(
            status_code=403,
            detail="Registrasi sudah ditutup / Registration is closed"
        )

    # Validate registration code
    if body.registration_code != settings.registration_code:
        raise HTTPException(
            status_code=403,
            detail="Kode registrasi salah / Invalid registration code"
        )

    # Check max teams (20 teams max)
    team_count = await db.execute(
        select(func.count(Team.id)).where(Team.is_active == True)
    )
    if team_count.scalar() >= 20:
        raise HTTPException(
            status_code=400,
            detail="Kuota team sudah penuh (max 20) / Team quota full"
        )

    # Check duplicate team name (case insensitive)
    existing = await db.execute(
        select(Team).where(func.lower(Team.name) == func.lower(body.name))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Nama team '{body.name}' sudah digunakan / Team name already taken"
        )

    # Create team
    token = secrets.token_hex(32)
    team = Team(
        name=body.name,
        display_name=body.display_name,
        category=body.category,
        token=token,
    )
    db.add(team)
    await db.flush()

    # Init team score record
    db.add(TeamScore(team_id=team.id))

    # ── Auto-generate WireGuard VPN config ──
    vpn_ip = None
    vpn_ready = False
    try:
        vpn_result = await generate_team_vpn_config(db, team)
        vpn_ip = vpn_result["vpn_ip"]
        vpn_ready = True
        logger.info(f"VPN config auto-generated for {body.name} → {vpn_ip}")

        # Try to hot-add peer to live WireGuard server (non-blocking)
        try:
            added = await apply_peer_to_vpn_server(
                team_public_key=vpn_result["public_key"],
                psk=vpn_result["psk"],
                vpn_ip=vpn_ip,
            )
            if added:
                logger.info(f"VPN peer hot-added for {body.name}")
            else:
                logger.warning(f"VPN peer hot-add failed for {body.name} — manual sync needed")
        except Exception as e:
            logger.warning(f"VPN peer hot-add error for {body.name}: {e} — manual sync needed")

    except Exception as e:
        logger.error(f"Failed to generate VPN config for {body.name}: {e}")
        # Registration still succeeds even if VPN generation fails

    # Audit log
    db.add(AuditLog(
        event_type="team_self_registered",
        actor=body.name,
        details={
            "team_name": body.name,
            "display_name": body.display_name,
            "category": body.category,
            "vpn_ip": vpn_ip,
            "vpn_config_generated": vpn_ready,
        },
    ))
    await db.commit()
    await db.refresh(team)

    logger.info(f"Team self-registered: {body.name} ({body.category}) VPN={vpn_ip}")

    return TeamRegisterResponse(
        id=team.id,
        name=team.name,
        display_name=team.display_name,
        category=team.category,
        token=token,
        vpn_ip=vpn_ip,
        vpn_config_ready=vpn_ready,
        message=(
            f"Registrasi berhasil! VPN IP: {vpn_ip}. "
            f"Download config WireGuard di halaman Dashboard. "
            f"Simpan token ini: {token}"
        ) if vpn_ready else (
            f"Registrasi berhasil! VPN config akan digenerate oleh panitia. "
            f"Simpan token ini: {token}"
        ),
    )
