"""
KoTH CTF Platform — Authentication Router
Login for teams (by token), individuals (username/password),
organizers (username/password), and admin (by admin token).
All logins are recorded in the audit log with IP and user-agent.
"""
import hashlib
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Team, TeamScore, AuditLog, OrganizerUser, IndividualUser

logger = logging.getLogger("koth.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify password against stored hash."""
    try:
        salt, hashed = password_hash.split(":", 1)
        return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest() == hashed
    except ValueError:
        return False


def _client_ip(request: Request) -> Optional[str]:
    """Extract client IP, checking X-Forwarded-For first."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── Request / Response Models ───────────────────────────────────────────────

class TeamLoginRequest(BaseModel):
    token: str


class AdminLoginRequest(BaseModel):
    admin_token: str


class IndividualLoginRequest(BaseModel):
    username: str
    password: str


class OrganizerLoginRequest(BaseModel):
    username: str
    password: str


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


class IndividualLoginResponse(BaseModel):
    role: str = "individual"
    user_id: int
    username: str
    display_name: Optional[str] = None
    category: str
    vpn_ip: Optional[str] = None


class OrganizerLoginResponse(BaseModel):
    role: str = "organizer"
    user_id: int
    username: str
    display_name: Optional[str] = None
    organizer_role: str


# ─── Event Mode ──────────────────────────────────────────────────────────────

@router.get("/event-mode")
async def get_event_mode():
    """Public endpoint to check event mode (team or individual)."""
    return {"event_mode": settings.event_mode}


# ─── Team Login ──────────────────────────────────────────────────────────────

@router.post("/team", response_model=TeamLoginResponse)
async def team_login(body: TeamLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Team login via their unique token (received during registration)."""
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")

    result = await db.execute(
        select(Team).where(Team.token == body.token, Team.is_active == True)
    )
    team = result.scalar_one_or_none()
    if not team:
        # Log failed attempt
        db.add(AuditLog(
            event_type="auth_failed",
            actor="unknown_team",
            details={"method": "team_token", "reason": "invalid_token"},
            ip_address=ip,
            user_agent=ua,
        ))
        await db.commit()
        raise HTTPException(status_code=401, detail="Token tidak valid / Invalid team token")

    # Log successful login
    db.add(AuditLog(
        event_type="auth_login",
        actor=team.name,
        details={"method": "team_token", "role": "team", "team_id": team.id},
        ip_address=ip,
        user_agent=ua,
    ))
    await db.commit()

    logger.info(f"Team login: {team.name} from {ip}")
    return TeamLoginResponse(
        team_id=team.id,
        team_name=team.name,
        display_name=team.display_name,
        category=team.category,
        vpn_ip=team.vpn_ip,
        token=team.token,
    )


# ─── Admin Token Login ──────────────────────────────────────────────────────

@router.post("/admin", response_model=AdminLoginResponse)
async def admin_login(body: AdminLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Admin login via admin token."""
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")

    if body.admin_token != settings.api_admin_token:
        db.add(AuditLog(
            event_type="auth_failed",
            actor="unknown_admin",
            details={"method": "admin_token", "reason": "invalid_token"},
            ip_address=ip,
            user_agent=ua,
        ))
        await db.commit()
        raise HTTPException(status_code=401, detail="Admin token tidak valid")

    db.add(AuditLog(
        event_type="auth_login",
        actor="admin",
        details={"method": "admin_token", "role": "admin"},
        ip_address=ip,
        user_agent=ua,
    ))
    await db.commit()

    logger.info(f"Admin login from {ip}")
    return AdminLoginResponse()


# ─── Organizer User Login ───────────────────────────────────────────────────

@router.post("/organizer", response_model=OrganizerLoginResponse)
async def organizer_login(body: OrganizerLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Organizer login via username/password."""
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")

    result = await db.execute(
        select(OrganizerUser).where(
            OrganizerUser.username == body.username,
            OrganizerUser.is_active == True,
        )
    )
    user = result.scalar_one_or_none()

    if not user or not _verify_password(body.password, user.password_hash):
        db.add(AuditLog(
            event_type="auth_failed",
            actor=body.username,
            details={"method": "organizer_password", "reason": "invalid_credentials"},
            ip_address=ip,
            user_agent=ua,
        ))
        await db.commit()
        raise HTTPException(status_code=401, detail="Username atau password salah")

    # Update last_login
    user.last_login = datetime.utcnow()

    db.add(AuditLog(
        event_type="auth_login",
        actor=user.username,
        details={"method": "organizer_password", "role": "organizer", "organizer_role": user.role, "user_id": user.id},
        ip_address=ip,
        user_agent=ua,
    ))
    await db.commit()

    logger.info(f"Organizer login: {user.username} ({user.role}) from {ip}")
    return OrganizerLoginResponse(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        organizer_role=user.role,
    )


# ─── Individual User Login ──────────────────────────────────────────────────

@router.post("/individual", response_model=IndividualLoginResponse)
async def individual_login(body: IndividualLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Individual user login (only available when event_mode=individual)."""
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")

    if settings.event_mode != "individual":
        raise HTTPException(
            status_code=403,
            detail="Individual login tidak tersedia. Event mode saat ini: team"
        )

    result = await db.execute(
        select(IndividualUser).where(
            IndividualUser.username == body.username,
            IndividualUser.is_active == True,
        )
    )
    user = result.scalar_one_or_none()

    if not user or not _verify_password(body.password, user.password_hash):
        db.add(AuditLog(
            event_type="auth_failed",
            actor=body.username,
            details={"method": "individual_password", "reason": "invalid_credentials"},
            ip_address=ip,
            user_agent=ua,
        ))
        await db.commit()
        raise HTTPException(status_code=401, detail="Username atau password salah")

    # Update last_login
    user.last_login = datetime.utcnow()

    db.add(AuditLog(
        event_type="auth_login",
        actor=user.username,
        details={"method": "individual_password", "role": "individual", "user_id": user.id},
        ip_address=ip,
        user_agent=ua,
    ))
    await db.commit()

    logger.info(f"Individual login: {user.username} from {ip}")
    return IndividualLoginResponse(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        category=user.category,
        vpn_ip=user.vpn_ip,
    )


# ─── Session Validation ─────────────────────────────────────────────────────

@router.get("/me")
async def get_current_user(
    x_team_token: Optional[str] = Header(None),
    x_admin_token: Optional[str] = Header(None),
    x_organizer_user: Optional[str] = Header(None),
    x_individual_user: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate current session — check token from header.
    Returns user info if valid.
    """
    # Admin token auth
    if x_admin_token and x_admin_token == settings.api_admin_token:
        return {"role": "admin", "message": "Admin authenticated"}

    # Organizer user auth (username stored in header, validated by prior login session)
    if x_organizer_user:
        result = await db.execute(
            select(OrganizerUser).where(
                OrganizerUser.username == x_organizer_user,
                OrganizerUser.is_active == True,
            )
        )
        org = result.scalar_one_or_none()
        if org:
            return {
                "role": "organizer",
                "user_id": org.id,
                "username": org.username,
                "display_name": org.display_name,
                "organizer_role": org.role,
            }

    # Team token auth
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

    # Individual user auth
    if x_individual_user:
        result = await db.execute(
            select(IndividualUser).where(
                IndividualUser.username == x_individual_user,
                IndividualUser.is_active == True,
            )
        )
        user = result.scalar_one_or_none()
        if user:
            return {
                "role": "individual",
                "user_id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "category": user.category,
                "vpn_ip": user.vpn_ip,
            }

    raise HTTPException(status_code=401, detail="Not authenticated")
