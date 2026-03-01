"""
KoTH CTF Platform — Hill Agent Router
Receives heartbeat reports from hill agents for dual-verification scoring.

Each hill runs a lightweight agent that periodically reads king.txt and
reports its content here. This provides a second verification method
alongside the SSH-based scorebot check, so scoring continues even if
participants disable SSH on the hill.
"""
import json
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Hill, AuditLog
from app.schemas import AgentReportRequest, AgentReportResponse, AgentStatusResponse

logger = logging.getLogger("koth.agent")
router = APIRouter(prefix="/api/agent", tags=["agent"])

# Redis key prefix for agent reports
AGENT_REPORT_KEY = "agent:report:{hill_id}"
AGENT_REPORT_TTL = 180  # 3 minutes — if no report in 3 min, agent considered dead


@router.post("/report", response_model=AgentReportResponse)
async def receive_agent_report(
    body: AgentReportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive a heartbeat report from a hill agent.
    Agent sends: hill_id, agent_token, king_name, raw_king_txt, sla_status
    Stored in Redis with TTL for the tick engine to consume.
    """
    # Validate hill exists and agent token matches
    hill_result = await db.execute(
        select(Hill).where(Hill.id == body.hill_id, Hill.is_active == True)
    )
    hill = hill_result.scalar_one_or_none()

    if not hill:
        raise HTTPException(status_code=404, detail="Hill not found or inactive")

    if not hill.agent_token or hill.agent_token != body.agent_token:
        logger.warning(
            f"Invalid agent token for hill {body.hill_id} from {request.client.host}"
        )
        raise HTTPException(status_code=403, detail="Invalid agent token")

    # Store report in Redis
    redis = request.app.state.redis
    if not redis:
        logger.error("Redis not available — cannot store agent report")
        raise HTTPException(status_code=503, detail="Redis unavailable")

    report_data = {
        "hill_id": body.hill_id,
        "king_name": body.king_name or "",
        "raw_king_txt": body.raw_king_txt or "",
        "sla_status": body.sla_status,
        "reported_at": body.timestamp or datetime.utcnow().isoformat(),
        "agent_ip": request.client.host,
    }

    key = AGENT_REPORT_KEY.format(hill_id=body.hill_id)
    await redis.set(key, json.dumps(report_data), ex=AGENT_REPORT_TTL)

    logger.info(
        f"Agent report: Hill {hill.name} (#{body.hill_id}) — "
        f"King: {body.king_name or '(empty)'} | SLA: {body.sla_status}"
    )

    return AgentReportResponse(
        status="ok",
        message=f"Report received for {hill.name}",
        hill_id=body.hill_id,
    )


def _require_admin(x_admin_token: str = Header(...)):
    from app.config import get_settings
    settings = get_settings()
    if x_admin_token != settings.api_admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return True


@router.get("/status", response_model=List[AgentStatusResponse])
async def get_agent_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(_require_admin),
):
    """
    Get agent status for all active hills.
    Shows last report time, king name, and whether agent is alive.
    Used by admin/organizer panel.
    """
    redis = request.app.state.redis
    if not redis:
        raise HTTPException(status_code=503, detail="Redis unavailable")

    # Get all active hills
    hills_result = await db.execute(
        select(Hill).where(Hill.is_active == True).order_by(Hill.id)
    )
    hills = hills_result.scalars().all()

    statuses = []
    now = datetime.utcnow()

    for hill in hills:
        key = AGENT_REPORT_KEY.format(hill_id=hill.id)
        raw = await redis.get(key)

        if raw:
            report = json.loads(raw)
            reported_at = report.get("reported_at", "")
            try:
                report_time = datetime.fromisoformat(reported_at)
                # Strip timezone info so we can compare with utcnow()
                if report_time.tzinfo is not None:
                    report_time = report_time.replace(tzinfo=None)
                seconds_ago = int((now - report_time).total_seconds())
            except (ValueError, TypeError):
                seconds_ago = None

            statuses.append(AgentStatusResponse(
                hill_id=hill.id,
                hill_name=hill.name,
                last_report_at=reported_at,
                last_king_name=report.get("king_name") or None,
                agent_alive=True,
                seconds_since_report=seconds_ago,
            ))
        else:
            statuses.append(AgentStatusResponse(
                hill_id=hill.id,
                hill_name=hill.name,
                agent_alive=False,
            ))

    return statuses


async def get_latest_agent_reports(redis) -> dict:
    """
    Utility function called by tick_engine to get latest agent reports
    for all hills. Returns dict: {hill_id: report_data}
    """
    if not redis:
        return {}

    reports = {}
    # Scan for all agent report keys
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="agent:report:*", count=100)
        for key in keys:
            raw = await redis.get(key)
            if raw:
                report = json.loads(raw)
                hill_id = report.get("hill_id")
                if hill_id:
                    reports[hill_id] = report
        if cursor == 0:
            break

    return reports
