"""
KoTH CTF Platform — Hill Management Router
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Hill, Score, Team, TickResult, Tick
from app.schemas import HillCreate, HillResponse, HillStatusResponse

router = APIRouter(prefix="/api/hills", tags=["hills"])
settings = get_settings()


def require_admin(x_admin_token: str = Header(...)):
    if x_admin_token != settings.api_admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return True


@router.get("", response_model=list[HillResponse])
async def list_hills(db: AsyncSession = Depends(get_db)):
    """List all active hills"""
    result = await db.execute(
        select(Hill).where(Hill.is_active == True).order_by(Hill.id)
    )
    hills = result.scalars().all()

    responses = []
    for hill in hills:
        king_q = await db.execute(
            select(Score, Team)
            .join(Team, Score.team_id == Team.id)
            .where(and_(Score.hill_id == hill.id, Score.current_king == True))
        )
        king_row = king_q.first()

        resp = HillResponse(
            id=hill.id,
            name=hill.name,
            description=hill.description,
            ip_address=hill.ip_address,
            sla_check_type=hill.sla_check_type,
            base_points=hill.base_points,
            multiplier=hill.multiplier,
            is_behind_pivot=hill.is_behind_pivot,
            is_active=hill.is_active,
            current_king=king_row[1].name if king_row else None,
            current_king_team_id=king_row[1].id if king_row else None,
            sla_status=True,
            created_at=hill.created_at,
        )
        responses.append(resp)

    return responses


@router.get("/{hill_id}", response_model=HillResponse)
async def get_hill(hill_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Hill).where(Hill.id == hill_id))
    hill = result.scalar_one_or_none()
    if not hill:
        raise HTTPException(status_code=404, detail="Hill not found")

    king_q = await db.execute(
        select(Score, Team)
        .join(Team, Score.team_id == Team.id)
        .where(and_(Score.hill_id == hill.id, Score.current_king == True))
    )
    king_row = king_q.first()

    return HillResponse(
        id=hill.id,
        name=hill.name,
        description=hill.description,
        ip_address=hill.ip_address,
        sla_check_type=hill.sla_check_type,
        base_points=hill.base_points,
        multiplier=hill.multiplier,
        is_behind_pivot=hill.is_behind_pivot,
        is_active=hill.is_active,
        current_king=king_row[1].name if king_row else None,
        current_king_team_id=king_row[1].id if king_row else None,
        sla_status=True,
        created_at=hill.created_at,
    )


@router.get("/{hill_id}/history")
async def get_hill_history(
    hill_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Get king ownership history for a hill"""
    result = await db.execute(
        select(TickResult, Tick, Team)
        .join(Tick, TickResult.tick_id == Tick.id)
        .outerjoin(Team, TickResult.king_team_id == Team.id)
        .where(TickResult.hill_id == hill_id)
        .order_by(desc(Tick.tick_number))
        .limit(limit)
    )
    rows = result.all()

    return [
        {
            "tick_number": tick.tick_number,
            "king_team": team.name if team else None,
            "king_team_id": team.id if team else None,
            "sla_status": tr.sla_status,
            "points_awarded": tr.points_awarded,
            "check_duration_ms": tr.check_duration_ms,
            "timestamp": tick.started_at.isoformat() if tick.started_at else None,
        }
        for tr, tick, team in rows
    ]


@router.get("/{hill_id}/scores")
async def get_hill_scores(hill_id: int, db: AsyncSession = Depends(get_db)):
    """Get all teams' scores on a specific hill"""
    result = await db.execute(
        select(Score, Team)
        .join(Team, Score.team_id == Team.id)
        .where(Score.hill_id == hill_id)
        .order_by(desc(Score.total_points))
    )
    rows = result.all()

    return [
        {
            "team_id": team.id,
            "team_name": team.name,
            "total_points": score.total_points,
            "ticks_as_king": score.ticks_as_king,
            "current_king": score.current_king,
            "consecutive_ticks": score.consecutive_ticks,
        }
        for score, team in rows
    ]


@router.post("", response_model=HillResponse, status_code=201)
async def create_hill(
    body: HillCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Create a new hill (admin only)"""
    from app.models import AuditLog

    hill = Hill(
        name=body.name,
        description=body.description,
        ip_address=body.ip_address,
        ssh_port=body.ssh_port,
        ssh_user=body.ssh_user,
        ssh_pass=body.ssh_pass,
        sla_check_url=body.sla_check_url,
        sla_check_port=body.sla_check_port,
        sla_check_type=body.sla_check_type,
        king_file_path=body.king_file_path,
        base_points=body.base_points,
        multiplier=body.multiplier,
        is_behind_pivot=body.is_behind_pivot,
    )
    db.add(hill)

    db.add(AuditLog(
        event_type="hill_created",
        actor="admin",
        details={"hill_name": body.name},
    ))
    await db.commit()
    await db.refresh(hill)

    return HillResponse(
        id=hill.id,
        name=hill.name,
        description=hill.description,
        ip_address=hill.ip_address,
        sla_check_type=hill.sla_check_type,
        base_points=hill.base_points,
        multiplier=hill.multiplier,
        is_behind_pivot=hill.is_behind_pivot,
        is_active=hill.is_active,
        created_at=hill.created_at,
    )
