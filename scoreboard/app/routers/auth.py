"""
KoTH CTF Platform — Authentication Router
Login for teams (by token) and admin (by admin token).
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Team, TeamScore

logger = logging.getLogger("koth.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


class TeamLoginRequest(BaseModel):
    token: str


class AdminLoginRequest(BaseModel):
    admin_token: str


class TeamLoginResponse(BaseModel):
    role: str = "team"
    team_id: int
    team_name: str
    display_name: Optional[str] = None
    category: str
    vpn_ip: Optional[str] = None
    token: str


class AdminLoginResponse(BaseModel):
    role: str = "admin"
    message: str = "Admin authenticated"


@router.post("/team", response_model=TeamLoginResponse)
async def team_login(body: TeamLoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Team login via their unique token (received during registration).
    """
    result = await db.execute(
        select(Team).where(Team.token == body.token, Team.is_active == True)
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=401, detail="Token tidak valid / Invalid team token")

    logger.info(f"Team login: {team.name}")
    return TeamLoginResponse(
        team_id=team.id,
        team_name=team.name,
        display_name=team.display_name,
        category=team.category,
        vpn_ip=team.vpn_ip,
        token=team.token,
    )


@router.post("/admin", response_model=AdminLoginResponse)
async def admin_login(body: AdminLoginRequest):
    """
    Admin login via admin token.
    """
    if body.admin_token != settings.api_admin_token:
        raise HTTPException(status_code=401, detail="Admin token tidak valid")

    logger.info("Admin login successful")
    return AdminLoginResponse()


@router.get("/me")
async def get_current_user(
    x_team_token: Optional[str] = Header(None),
    x_admin_token: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate current session — check token from header.
    Returns user info if valid.
    """
    if x_admin_token and x_admin_token == settings.api_admin_token:
        return {"role": "admin", "message": "Admin authenticated"}

    if x_team_token:
        result = await db.execute(
            select(Team).where(Team.token == x_team_token, Team.is_active == True)
        )
        team = result.scalar_one_or_none()
        if team:
            return {
                "role": "team",
                "team_id": team.id,
                "team_name": team.name,
                "display_name": team.display_name,
                "category": team.category,
                "vpn_ip": team.vpn_ip,
            }

    raise HTTPException(status_code=401, detail="Not authenticated")
