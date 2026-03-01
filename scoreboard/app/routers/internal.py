"""
KoTH CTF Platform — Internal Router
Endpoints called by scorebot to submit tick results
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.schemas import TickResultSubmit

logger = logging.getLogger("koth.internal")
router = APIRouter(prefix="/api/internal", tags=["internal"])
settings = get_settings()


def require_internal(x_internal_token: str = Header(...)):
    """Verify internal service token"""
    if x_internal_token != settings.api_secret_key:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    return True


@router.post("/tick/submit")
async def submit_tick_results(
    results: List[TickResultSubmit],
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_internal),
):
    """
    Submit tick check results from scorebot.
    This is the alternative ingestion path — scorebot can push results
    directly instead of being polled by tick_engine.
    """
    from datetime import datetime
    from app.models import Tick, TickResult, Hill, Team
    from app.services.scoring import ScoringEngine
    from app.services.tick_engine import tick_engine
    from app.services.ws_manager import ws_manager
    from sqlalchemy import select, func

    # Determine tick number
    tick_number = tick_engine.current_tick or 1
    tick_start = datetime.utcnow()

    # Create or get current tick
    existing = await db.execute(
        select(Tick).where(Tick.tick_number == tick_number)
    )
    tick = existing.scalar_one_or_none()

    if not tick:
        tick = Tick(
            tick_number=tick_number,
            started_at=tick_start,
            status="running",
        )
        db.add(tick)
        await db.flush()

    # Convert to dict format expected by scoring engine
    check_results = []
    for r in results:
        check_results.append({
            "hill_id": r.hill_id,
            "king_team_name": r.king_team_name,
            "sla_status": r.sla_status,
            "raw_king_txt": r.raw_king_txt,
            "check_duration_ms": r.check_duration_ms,
            "error_message": r.error_message,
        })

    scoring = ScoringEngine(db)
    summary = await scoring.process_tick_results(tick, check_results)

    # Broadcast via WebSocket
    await ws_manager.broadcast_all({
        "type": "tick_update",
        "data": summary,
        "timestamp": datetime.utcnow().isoformat(),
    })

    logger.info(f"Internal: Received {len(results)} results for tick #{tick_number}")
    return {"detail": "Tick results processed", "summary": summary}


@router.get("/hills")
async def get_hills_for_scorebot(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_internal),
):
    """Get hill configuration for scorebot"""
    from app.models import Hill
    from sqlalchemy import select

    result = await db.execute(
        select(Hill).where(Hill.is_active == True).order_by(Hill.id)
    )
    hills = result.scalars().all()

    return [
        {
            "hill_id": h.id,
            "name": h.name,
            "ip_address": h.ip_address,
            "ssh_port": h.ssh_port,
            "king_file_path": h.king_file_path,
            "sla_check_type": h.sla_check_type,
            "sla_check_url": h.sla_check_url,
            "sla_check_port": h.sla_check_port,
        }
        for h in hills
    ]


@router.get("/status")
async def get_engine_status(_: bool = Depends(require_internal)):
    """Get tick engine status for scorebot"""
    from app.services.tick_engine import tick_engine
    return tick_engine.get_status()
