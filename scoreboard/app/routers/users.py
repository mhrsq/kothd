"""
KoTH CTF Platform — User Management Router
Manages organizer accounts and individual user accounts.
"""
import secrets
import hashlib
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import OrganizerUser, IndividualUser, AuditLog, TeamScore

logger = logging.getLogger("koth.users")
router = APIRouter(prefix="/api/admin/users", tags=["users"])
settings = get_settings()


def _hash_password(password: str) -> str:
    """Hash password with SHA-256 + salt."""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify password against stored hash."""
    try:
        salt, hashed = password_hash.split(":", 1)
        return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest() == hashed
    except ValueError:
        return False


def require_admin(x_admin_token: str = Header(...)):
    if x_admin_token != settings.api_admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return True


# ─── Schemas ─────────────────────────────────────────────────────────────────

class CreateOrganizerRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern="^[a-zA-Z0-9_-]+$")
    display_name: Optional[str] = None
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default="organizer", pattern="^(superadmin|organizer)$")


class UpdateOrganizerRequest(BaseModel):
    display_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=6, max_length=128)
    role: Optional[str] = Field(None, pattern="^(superadmin|organizer)$")
    is_active: Optional[bool] = None


class CreateIndividualRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern="^[a-zA-Z0-9_-]+$")
    display_name: Optional[str] = None
    password: str = Field(..., min_length=6, max_length=128)
    category: str = Field(default="default", max_length=32)


class BulkCreateIndividualRequest(BaseModel):
    users: List[CreateIndividualRequest]


class UpdateIndividualRequest(BaseModel):
    display_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=6, max_length=128)
    category: Optional[str] = None
    is_active: Optional[bool] = None


# ─── Event Mode ──────────────────────────────────────────────────────────────

@router.get("/event-mode")
async def get_event_mode(_: bool = Depends(require_admin)):
    """Get current event mode (team or individual)."""
    return {"event_mode": settings.event_mode}


@router.post("/event-mode")
async def set_event_mode(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Switch event mode between 'team' and 'individual'."""
    body = await request.json()
    mode = body.get("event_mode", "").lower()
    if mode not in ("team", "individual"):
        raise HTTPException(status_code=400, detail="event_mode must be 'team' or 'individual'")

    old_mode = settings.event_mode
    settings.event_mode = mode

    db.add(AuditLog(
        event_type="event_mode_changed",
        actor="admin",
        details={"old_mode": old_mode, "new_mode": mode},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))
    await db.commit()

    logger.info(f"ADMIN: Event mode changed: {old_mode} → {mode}")
    return {"detail": f"Event mode set to '{mode}'", "event_mode": mode}


# ─── Organizer User Management ──────────────────────────────────────────────

@router.get("/organizers")
async def list_organizers(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """List all organizer user accounts."""
    result = await db.execute(
        select(OrganizerUser).order_by(OrganizerUser.id)
    )
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]


@router.post("/organizers")
async def create_organizer(
    body: CreateOrganizerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Create a new organizer user account."""
    # Check duplicate
    existing = await db.execute(
        select(OrganizerUser).where(func.lower(OrganizerUser.username) == func.lower(body.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Username '{body.username}' already exists")

    user = OrganizerUser(
        username=body.username,
        display_name=body.display_name or body.username,
        password_hash=_hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()

    db.add(AuditLog(
        event_type="organizer_created",
        actor="admin",
        details={"username": body.username, "role": body.role},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))
    await db.commit()

    logger.info(f"ADMIN: Organizer created: {body.username} ({body.role})")
    return {"detail": f"Organizer '{body.username}' created", "id": user.id, "username": user.username}


@router.put("/organizers/{user_id}")
async def update_organizer(
    user_id: int,
    body: UpdateOrganizerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Update an organizer user account."""
    result = await db.execute(select(OrganizerUser).where(OrganizerUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Organizer not found")

    changes = {}
    if body.display_name is not None:
        user.display_name = body.display_name
        changes["display_name"] = body.display_name
    if body.password is not None:
        user.password_hash = _hash_password(body.password)
        changes["password"] = "changed"
    if body.role is not None:
        changes["role"] = {"old": user.role, "new": body.role}
        user.role = body.role
    if body.is_active is not None:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active

    db.add(AuditLog(
        event_type="organizer_updated",
        actor="admin",
        details={"user_id": user_id, "username": user.username, "changes": changes},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))
    await db.commit()
    return {"detail": f"Organizer '{user.username}' updated", "changes": changes}


@router.delete("/organizers/{user_id}")
async def delete_organizer(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Delete an organizer user account."""
    result = await db.execute(select(OrganizerUser).where(OrganizerUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Organizer not found")

    username = user.username
    await db.delete(user)

    db.add(AuditLog(
        event_type="organizer_deleted",
        actor="admin",
        details={"user_id": user_id, "username": username},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))
    await db.commit()

    logger.info(f"ADMIN: Organizer deleted: {username}")
    return {"detail": f"Organizer '{username}' deleted"}


# ─── Individual User Management ─────────────────────────────────────────────

@router.get("/individuals")
async def list_individuals(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """List all individual user accounts."""
    result = await db.execute(
        select(IndividualUser).order_by(IndividualUser.id)
    )
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "vpn_ip": u.vpn_ip,
            "category": u.category,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]


@router.post("/individuals")
async def create_individual(
    body: CreateIndividualRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Create a new individual user account."""
    # Check duplicate
    existing = await db.execute(
        select(IndividualUser).where(func.lower(IndividualUser.username) == func.lower(body.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Username '{body.username}' already exists")

    user = IndividualUser(
        username=body.username,
        display_name=body.display_name or body.username,
        password_hash=_hash_password(body.password),
        category=body.category,
    )
    db.add(user)
    await db.flush()

    db.add(AuditLog(
        event_type="individual_created",
        actor="admin",
        details={"username": body.username, "category": body.category},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))
    await db.commit()

    logger.info(f"ADMIN: Individual user created: {body.username}")
    return {"detail": f"Individual user '{body.username}' created", "id": user.id, "username": user.username}


@router.post("/individuals/bulk")
async def bulk_create_individuals(
    body: BulkCreateIndividualRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Bulk create individual user accounts."""
    created = []
    errors = []

    for u in body.users:
        existing = await db.execute(
            select(IndividualUser).where(func.lower(IndividualUser.username) == func.lower(u.username))
        )
        if existing.scalar_one_or_none():
            errors.append(f"Username '{u.username}' already exists")
            continue

        user = IndividualUser(
            username=u.username,
            display_name=u.display_name or u.username,
            password_hash=_hash_password(u.password),
            category=u.category,
        )
        db.add(user)
        created.append(u.username)

    if created:
        db.add(AuditLog(
            event_type="individuals_bulk_created",
            actor="admin",
            details={"count": len(created), "usernames": created},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        ))
        await db.commit()

    return {"detail": f"Created {len(created)} users", "created": created, "errors": errors}


@router.put("/individuals/{user_id}")
async def update_individual(
    user_id: int,
    body: UpdateIndividualRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Update an individual user account."""
    result = await db.execute(select(IndividualUser).where(IndividualUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Individual user not found")

    changes = {}
    if body.display_name is not None:
        user.display_name = body.display_name
        changes["display_name"] = body.display_name
    if body.password is not None:
        user.password_hash = _hash_password(body.password)
        changes["password"] = "changed"
    if body.category is not None:
        changes["category"] = {"old": user.category, "new": body.category}
        user.category = body.category
    if body.is_active is not None:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active

    db.add(AuditLog(
        event_type="individual_updated",
        actor="admin",
        details={"user_id": user_id, "username": user.username, "changes": changes},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))
    await db.commit()
    return {"detail": f"Individual user '{user.username}' updated", "changes": changes}


@router.delete("/individuals/{user_id}")
async def delete_individual(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Delete an individual user account."""
    result = await db.execute(select(IndividualUser).where(IndividualUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Individual user not found")

    username = user.username
    await db.delete(user)

    db.add(AuditLog(
        event_type="individual_deleted",
        actor="admin",
        details={"user_id": user_id, "username": username},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))
    await db.commit()

    logger.info(f"ADMIN: Individual user deleted: {username}")
    return {"detail": f"Individual user '{username}' deleted"}
