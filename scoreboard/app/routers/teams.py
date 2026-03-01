"""
KoTH CTF Platform — Team Management Router
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Team, TeamScore, AuditLog
from app.schemas import TeamCreate, TeamResponse

router = APIRouter(prefix="/api/teams", tags=["teams"])
settings = get_settings()


def require_admin(x_admin_token: str = Header(...)):
    """Verify admin token from header"""
    if x_admin_token != settings.api_admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return True


@router.get("", response_model=list[TeamResponse])
async def list_teams(db: AsyncSession = Depends(get_db)):
    """List all active teams"""
    result = await db.execute(
        select(Team).where(Team.is_active == True).order_by(Team.id)
    )
    return result.scalars().all()


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(team_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single team by ID"""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.post("", response_model=TeamResponse, status_code=201)
async def create_team(
    body: TeamCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Register a new team (admin only)"""
    import secrets

    # Check duplicate (case insensitive)
    from sqlalchemy import func as sqlfunc
    existing = await db.execute(
        select(Team).where(sqlfunc.lower(Team.name) == sqlfunc.lower(body.name))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Team name already exists")

    team = Team(
        name=body.name,
        display_name=body.display_name or body.name,
        category=body.category,
        vpn_ip=body.vpn_ip,
        token=secrets.token_hex(32),
    )
    db.add(team)
    await db.flush()

    # Init team score
    db.add(TeamScore(team_id=team.id))

    db.add(AuditLog(
        event_type="team_created",
        actor="admin",
        details={"team_name": body.name, "category": body.category},
    ))
    await db.commit()
    await db.refresh(team)
    return team


@router.post("/bulk", response_model=list[TeamResponse], status_code=201)
async def create_teams_bulk(
    teams_data: list[TeamCreate],
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Register multiple teams at once (admin only)"""
    import secrets

    created = []
    for body in teams_data:
        from sqlalchemy import func as sqlfunc
        existing = await db.execute(
            select(Team).where(sqlfunc.lower(Team.name) == sqlfunc.lower(body.name))
        )
        if existing.scalar_one_or_none():
            continue  # Skip duplicates

        team = Team(
            name=body.name,
            display_name=body.display_name or body.name,
            category=body.category,
            vpn_ip=body.vpn_ip,
            token=secrets.token_hex(32),
        )
        db.add(team)
        await db.flush()
        db.add(TeamScore(team_id=team.id))
        created.append(team)

    db.add(AuditLog(
        event_type="teams_bulk_created",
        actor="admin",
        details={"count": len(created)},
    ))
    await db.commit()
    return created


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: int,
    body: TeamCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Update a team (admin only)"""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    team.name = body.name
    team.display_name = body.display_name or body.name
    team.category = body.category
    if body.vpn_ip:
        team.vpn_ip = body.vpn_ip

    db.add(AuditLog(
        event_type="team_updated",
        actor="admin",
        details={"team_id": team_id, "team_name": body.name},
    ))
    await db.commit()
    await db.refresh(team)
    return team


@router.delete("/{team_id}")
async def deactivate_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Deactivate a team (soft delete, admin only)"""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    team.is_active = False

    db.add(AuditLog(
        event_type="team_deactivated",
        actor="admin",
        details={"team_id": team_id, "team_name": team.name},
    ))
    await db.commit()
    return {"detail": f"Team {team.name} deactivated"}
