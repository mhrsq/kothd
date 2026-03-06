"""
KoTH CTF Platform — Public Scoreboard Router
"""
import logging
from datetime import datetime
from typing import Optional, Tuple
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Team, Hill, Score, TeamScore, FirstBlood, Tick, TickResult, GameConfig, AuditLog, Announcement
from app.schemas import (
    ScoreboardResponse, TeamScoreResponse, HillStatusResponse,
    TickResponse, TickResultResponse, FirstBloodResponse,
    ScoreDetailResponse, TeamPointHistory, TeamPointHistoryEntry,
    AllTeamsPointTimeline,
)
from app.services.tick_engine import tick_engine

logger = logging.getLogger("koth.scoreboard")

router = APIRouter(prefix="/api/scoreboard", tags=["scoreboard"])


async def get_freeze_state(db: AsyncSession) -> Tuple[bool, int]:
    """
    Read freeze state from the database (game_config table) so it's consistent
    across all uvicorn workers.  Falls back to tick_engine in-memory state
    ONLY for the auto-freeze (time-based) case.
    Returns (is_frozen, frozen_at_tick).
    """
    # Check DB-persisted manual_freeze first (shared across workers)
    mf_row = await db.execute(
        select(GameConfig.value).where(GameConfig.key == "manual_freeze")
    )
    manual_freeze_db = mf_row.scalar_one_or_none()

    if manual_freeze_db == "true":
        # DB says frozen — read frozen_at_tick from DB
        fat_row = await db.execute(
            select(GameConfig.value).where(GameConfig.key == "frozen_at_tick")
        )
        fat_val = fat_row.scalar_one_or_none()
        frozen_tick = int(fat_val) if fat_val else 0
        if frozen_tick > 0:
            return True, frozen_tick

    if manual_freeze_db == "false":
        # DB explicitly says NOT frozen — only check auto-freeze (time-based)
        status = tick_engine.get_status()
        # Auto-freeze kicks in when remaining_seconds <= freeze_before_end
        remaining = status.get("remaining_seconds", 0)
        if status.get("status") == "running" and remaining <= tick_engine.freeze_before_end:
            frozen_tick = tick_engine.frozen_at_tick
            if frozen_tick > 0:
                return True, frozen_tick
            return True, status.get("current_tick", 0)
        return False, 0

    # No DB entry yet — fall back entirely to tick_engine in-memory state
    status = tick_engine.get_status()
    is_frozen = status.get("is_frozen", False)
    if is_frozen:
        frozen_tick = tick_engine.frozen_at_tick
        if frozen_tick > 0:
            return True, frozen_tick
        return True, status.get("current_tick", 0)

    return False, 0


@router.get("", response_model=ScoreboardResponse)
async def get_scoreboard(db: AsyncSession = Depends(get_db)):
    """Get the full live scoreboard (respects freeze)"""
    status = tick_engine.get_status()
    is_frozen, frozen_tick = await get_freeze_state(db)

    if is_frozen and frozen_tick > 0:
        # ── FROZEN: compute scores as-of frozen_at_tick ──────────────────
        # Sum points from tick_results up to the frozen tick only
        frozen_scores_q = await db.execute(
            select(
                Team.id,
                Team.name,
                Team.display_name,
                Team.category,
                func.coalesce(func.sum(TickResult.points_awarded), 0).label("total_points"),
                func.count(TickResult.id).label("ticks_as_king"),
            )
            .outerjoin(TickResult, and_(
                TickResult.king_team_id == Team.id,
                TickResult.tick_id.in_(
                    select(Tick.id).where(Tick.tick_number <= frozen_tick)
                ),
            ))
            .where(Team.is_active == True)
            .group_by(Team.id, Team.name, Team.display_name, Team.category)
            .order_by(desc("total_points"))
        )
        frozen_rows = frozen_scores_q.all()

        # Count first bloods up to frozen tick
        fb_counts = {}
        fb_q = await db.execute(
            select(FirstBlood.team_id, func.count(FirstBlood.hill_id))
            .where(FirstBlood.tick_number <= frozen_tick)
            .group_by(FirstBlood.team_id)
        )
        for tid, cnt in fb_q.all():
            fb_counts[tid] = cnt

        # Count hills owned at frozen tick (last tick result per hill)
        hills_owned_q = await db.execute(
            select(TickResult.king_team_id, func.count(func.distinct(TickResult.hill_id)))
            .join(Tick, TickResult.tick_id == Tick.id)
            .where(and_(Tick.tick_number == frozen_tick, TickResult.king_team_id.isnot(None)))
            .group_by(TickResult.king_team_id)
        )
        hills_owned = {tid: cnt for tid, cnt in hills_owned_q.all()}

        team_scores = []
        for rank, row in enumerate(frozen_rows, 1):
            team_scores.append(TeamScoreResponse(
                team_id=row.id,
                team_name=row.name,
                display_name=row.display_name,
                category=row.category,
                total_points=row.total_points,
                hills_owned=hills_owned.get(row.id, 0),
                total_ticks_as_king=row.ticks_as_king,
                first_bloods=fb_counts.get(row.id, 0),
                rank=rank,
            ))

        # Hill statuses at frozen tick
        hills_q = await db.execute(
            select(Hill).where(Hill.is_active == True).order_by(Hill.id)
        )
        hills = hills_q.scalars().all()

        hill_statuses = []
        for hill in hills:
            # King at the frozen tick
            king_at_freeze = await db.execute(
                select(TickResult, Team)
                .join(Tick, TickResult.tick_id == Tick.id)
                .outerjoin(Team, TickResult.king_team_id == Team.id)
                .where(and_(
                    Tick.tick_number == frozen_tick,
                    TickResult.hill_id == hill.id,
                ))
            )
            king_row = king_at_freeze.first()

            hill_statuses.append(HillStatusResponse(
                hill_id=hill.id,
                hill_name=hill.name,
                current_king=king_row[1].name if king_row and king_row[1] else None,
                current_king_team_id=king_row[1].id if king_row and king_row[1] else None,
                sla_status=king_row[0].sla_status if king_row else False,
                multiplier=hill.multiplier,
                is_behind_pivot=hill.is_behind_pivot,
            ))
    else:
        # ── LIVE: real-time scores ───────────────────────────────────────
        teams_q = await db.execute(
            select(Team, TeamScore)
            .outerjoin(TeamScore, Team.id == TeamScore.team_id)
            .where(Team.is_active == True)
            .order_by(desc(TeamScore.total_points))
        )
        teams_rows = teams_q.all()

        team_scores = []
        for rank, (team, ts) in enumerate(teams_rows, 1):
            team_scores.append(TeamScoreResponse(
                team_id=team.id,
                team_name=team.name,
                display_name=team.display_name,
                category=team.category,
                total_points=ts.total_points if ts else 0,
                hills_owned=ts.hills_owned if ts else 0,
                total_ticks_as_king=ts.total_ticks_as_king if ts else 0,
                first_bloods=ts.first_bloods if ts else 0,
                rank=rank,
            ))

        hills_q = await db.execute(
            select(Hill).where(Hill.is_active == True).order_by(Hill.id)
        )
        hills = hills_q.scalars().all()

        hill_statuses = []
        for hill in hills:
            king_q = await db.execute(
                select(Score, Team)
                .join(Team, Score.team_id == Team.id)
                .where(and_(Score.hill_id == hill.id, Score.current_king == True))
            )
            king_row = king_q.first()

            hill_statuses.append(HillStatusResponse(
                hill_id=hill.id,
                hill_name=hill.name,
                current_king=king_row[1].name if king_row else None,
                current_king_team_id=king_row[1].id if king_row else None,
                sla_status=True,
                multiplier=hill.multiplier,
                is_behind_pivot=hill.is_behind_pivot,
            ))

    return ScoreboardResponse(
        game_status="frozen" if is_frozen else status["status"],
        current_tick=frozen_tick if is_frozen and frozen_tick else status["current_tick"],
        total_ticks=status.get("elapsed_seconds", 0) // max(status.get("tick_interval", 60), 1),
        elapsed_seconds=status.get("elapsed_seconds", 0),
        remaining_seconds=status.get("remaining_seconds", 0),
        teams=team_scores,
        hills=hill_statuses,
        last_updated=datetime.utcnow(),
        is_frozen=is_frozen,
    )


@router.get("/leaderboard", response_model=list[TeamScoreResponse])
async def get_leaderboard(
    category: Optional[str] = Query(None, max_length=32),
    db: AsyncSession = Depends(get_db),
):
    """Get leaderboard, optionally filtered by category (respects freeze)"""
    is_frozen, frozen_tick = await get_freeze_state(db)

    if is_frozen and frozen_tick > 0:
        # Frozen: compute scores up to frozen tick
        base_q = (
            select(
                Team.id,
                Team.name,
                Team.display_name,
                Team.category,
                func.coalesce(func.sum(TickResult.points_awarded), 0).label("total_points"),
                func.count(TickResult.id).label("ticks_as_king"),
            )
            .outerjoin(TickResult, and_(
                TickResult.king_team_id == Team.id,
                TickResult.tick_id.in_(
                    select(Tick.id).where(Tick.tick_number <= frozen_tick)
                ),
            ))
            .where(Team.is_active == True)
        )
        if category:
            base_q = base_q.where(Team.category == category)
        base_q = base_q.group_by(Team.id, Team.name, Team.display_name, Team.category)
        base_q = base_q.order_by(desc("total_points"))

        result = await db.execute(base_q)
        rows = result.all()

        return [
            TeamScoreResponse(
                team_id=row.id,
                team_name=row.name,
                display_name=row.display_name,
                category=row.category,
                total_points=row.total_points,
                hills_owned=0,
                total_ticks_as_king=row.ticks_as_king,
                first_bloods=0,
                rank=rank,
            )
            for rank, row in enumerate(rows, 1)
        ]

    # Live mode
    query = (
        select(Team, TeamScore)
        .outerjoin(TeamScore, Team.id == TeamScore.team_id)
        .where(Team.is_active == True)
    )
    if category:
        query = query.where(Team.category == category)
    query = query.order_by(desc(TeamScore.total_points))

    result = await db.execute(query)
    rows = result.all()

    return [
        TeamScoreResponse(
            team_id=team.id,
            team_name=team.name,
            display_name=team.display_name,
            category=team.category,
            total_points=ts.total_points if ts else 0,
            hills_owned=ts.hills_owned if ts else 0,
            total_ticks_as_king=ts.total_ticks_as_king if ts else 0,
            first_bloods=ts.first_bloods if ts else 0,
            rank=rank,
        )
        for rank, (team, ts) in enumerate(rows, 1)
    ]


@router.get("/team/{team_id}/details", response_model=list[ScoreDetailResponse])
async def get_team_score_details(team_id: int, db: AsyncSession = Depends(get_db)):
    """Get per-hill score breakdown for a specific team (respects freeze)"""
    is_frozen, frozen_tick = await get_freeze_state(db)

    if is_frozen and frozen_tick > 0:
        # Compute from tick_results up to frozen tick
        detail_q = await db.execute(
            select(
                TickResult.hill_id,
                Hill.name.label("hill_name"),
                func.coalesce(func.sum(TickResult.points_awarded), 0).label("total_points"),
                func.count(TickResult.id).label("ticks_as_king"),
            )
            .join(Tick, TickResult.tick_id == Tick.id)
            .join(Hill, TickResult.hill_id == Hill.id)
            .where(and_(
                TickResult.king_team_id == team_id,
                Tick.tick_number <= frozen_tick,
            ))
            .group_by(TickResult.hill_id, Hill.name)
            .order_by(TickResult.hill_id)
        )
        rows = detail_q.all()
        return [
            ScoreDetailResponse(
                team_id=team_id,
                hill_id=row.hill_id,
                hill_name=row.hill_name,
                total_points=row.total_points,
                ticks_as_king=row.ticks_as_king,
                current_king=False,
                consecutive_ticks=0,
            )
            for row in rows
        ]

    result = await db.execute(
        select(Score, Hill)
        .join(Hill, Score.hill_id == Hill.id)
        .where(Score.team_id == team_id)
        .order_by(Hill.id)
    )
    rows = result.all()

    return [
        ScoreDetailResponse(
            team_id=team_id,
            hill_id=hill.id,
            hill_name=hill.name,
            total_points=score.total_points,
            ticks_as_king=score.ticks_as_king,
            current_king=score.current_king,
            consecutive_ticks=score.consecutive_ticks,
        )
        for score, hill in rows
    ]


@router.get("/ticks", response_model=list[TickResponse])
async def get_recent_ticks(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get recent tick results (respects freeze — hides post-freeze ticks)"""
    is_frozen, frozen_tick = await get_freeze_state(db)

    query = select(Tick).options(
        selectinload(Tick.results).selectinload(TickResult.hill),
        selectinload(Tick.results).selectinload(TickResult.king_team),
    )
    if is_frozen and frozen_tick > 0:
        query = query.where(Tick.tick_number <= frozen_tick)
    result = await db.execute(query.order_by(desc(Tick.tick_number)).limit(limit))
    ticks = result.scalars().unique().all()

    # Manually build response to populate hill_name / king_team_name
    return [
        TickResponse(
            id=t.id,
            tick_number=t.tick_number,
            started_at=t.started_at,
            completed_at=t.completed_at,
            status=t.status,
            results=[
                TickResultResponse(
                    hill_id=r.hill_id,
                    hill_name=r.hill.name if r.hill else None,
                    king_team_id=r.king_team_id,
                    king_team_name=r.king_team.name if r.king_team else None,
                    sla_status=r.sla_status,
                    points_awarded=r.points_awarded,
                    check_duration_ms=r.check_duration_ms,
                    ssh_verified=r.ssh_verified,
                    agent_verified=r.agent_verified,
                    ssh_king_name=r.ssh_king_name,
                    agent_king_name=r.agent_king_name,
                    verification_count=r.verification_count,
                )
                for r in t.results
            ],
        )
        for t in ticks
    ]


@router.get("/ticks/{tick_number}", response_model=TickResponse)
async def get_tick_detail(tick_number: int, db: AsyncSession = Depends(get_db)):
    """Get details for a specific tick (blocked if past freeze point)"""
    is_frozen, frozen_tick = await get_freeze_state(db)

    if is_frozen and frozen_tick > 0 and tick_number > frozen_tick:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tick not found")

    result = await db.execute(
        select(Tick)
        .options(
            selectinload(Tick.results).selectinload(TickResult.hill),
            selectinload(Tick.results).selectinload(TickResult.king_team),
        )
        .where(Tick.tick_number == tick_number)
    )
    tick = result.scalars().unique().first()
    if not tick:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tick not found")

    return TickResponse(
        id=tick.id,
        tick_number=tick.tick_number,
        started_at=tick.started_at,
        completed_at=tick.completed_at,
        status=tick.status,
        results=[
            TickResultResponse(
                hill_id=r.hill_id,
                hill_name=r.hill.name if r.hill else None,
                king_team_id=r.king_team_id,
                king_team_name=r.king_team.name if r.king_team else None,
                sla_status=r.sla_status,
                points_awarded=r.points_awarded,
                check_duration_ms=r.check_duration_ms,
                ssh_verified=r.ssh_verified,
                agent_verified=r.agent_verified,
                ssh_king_name=r.ssh_king_name,
                agent_king_name=r.agent_king_name,
                verification_count=r.verification_count,
            )
            for r in tick.results
        ],
    )


@router.get("/first-bloods", response_model=list[FirstBloodResponse])
async def get_first_bloods(db: AsyncSession = Depends(get_db)):
    """Get all first blood captures (respects freeze)"""
    is_frozen, frozen_tick = await get_freeze_state(db)

    query = (
        select(FirstBlood, Hill, Team)
        .join(Hill, FirstBlood.hill_id == Hill.id)
        .join(Team, FirstBlood.team_id == Team.id)
    )
    if is_frozen and frozen_tick > 0:
        query = query.where(FirstBlood.tick_number <= frozen_tick)
    query = query.order_by(FirstBlood.captured_at)

    result = await db.execute(query)
    rows = result.all()

    return [
        FirstBloodResponse(
            hill_id=fb.hill_id,
            hill_name=hill.name,
            team_id=fb.team_id,
            team_name=team.name,
            tick_number=fb.tick_number,
            bonus_points=fb.bonus_points,
            captured_at=fb.captured_at,
        )
        for fb, hill, team in rows
    ]


@router.get("/timeline")
async def get_score_timeline(db: AsyncSession = Depends(get_db)):
    """Get score progression over time (for charts, respects freeze)"""
    is_frozen, frozen_tick = await get_freeze_state(db)

    query = (
        select(TickResult, Tick, Team, Hill)
        .join(Tick, TickResult.tick_id == Tick.id)
        .outerjoin(Team, TickResult.king_team_id == Team.id)
        .join(Hill, TickResult.hill_id == Hill.id)
    )
    if is_frozen and frozen_tick > 0:
        query = query.where(Tick.tick_number <= frozen_tick)
    query = query.order_by(Tick.tick_number)

    result = await db.execute(query)
    rows = result.all()

    timeline = []
    for tr, tick, team, hill in rows:
        timeline.append({
            "tick": tick.tick_number,
            "hill_id": hill.id,
            "hill_name": hill.name,
            "king_team": team.name if team else None,
            "king_team_id": team.id if team else None,
            "sla_status": tr.sla_status,
            "points": tr.points_awarded,
            "timestamp": tick.started_at.isoformat() if tick.started_at else None,
        })

    return timeline


@router.get("/history/team/{team_id}", response_model=TeamPointHistory)
async def get_team_point_history(
    team_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the full point history for a specific team.
    Shows per-tick breakdown: which hills were held, points earned each tick,
    and cumulative total over time.
    """
    from fastapi import HTTPException

    # Validate team
    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Get team's total score
    ts_result = await db.execute(
        select(TeamScore).where(TeamScore.team_id == team_id)
    )
    ts = ts_result.scalar_one_or_none()

    # Freeze-aware: only show ticks up to frozen point
    is_frozen, frozen_tick = await get_freeze_state(db)

    # Get all tick results where this team was king
    history_q = (
        select(TickResult, Tick, Hill)
        .join(Tick, TickResult.tick_id == Tick.id)
        .join(Hill, TickResult.hill_id == Hill.id)
        .where(TickResult.king_team_id == team_id)
    )
    if is_frozen and frozen_tick > 0:
        history_q = history_q.where(Tick.tick_number <= frozen_tick)
    history_q = history_q.order_by(Tick.tick_number, Hill.id)

    result = await db.execute(history_q)
    rows = result.all()

    history = []
    cumulative = 0
    for tr, tick, hill in rows:
        cumulative += tr.points_awarded
        history.append(TeamPointHistoryEntry(
            tick_number=tick.tick_number,
            timestamp=tick.started_at,
            points_this_tick=tr.points_awarded,
            cumulative_points=cumulative,
            hill_id=hill.id,
            hill_name=hill.name,
            was_king=True,
        ))

    # When frozen, use the cumulative total from filtered history (not live TeamScore)
    total = cumulative if (is_frozen and frozen_tick > 0) else (ts.total_points if ts else 0)

    return TeamPointHistory(
        team_id=team.id,
        team_name=team.name,
        display_name=team.display_name,
        total_points=total,
        history=history,
    )


@router.get("/history/all", response_model=AllTeamsPointTimeline)
async def get_all_teams_point_timeline(
    db: AsyncSession = Depends(get_db),
):
    """
    Get cumulative point progression for ALL teams over time.
    Optimized for rendering a multi-line chart (x = tick, y = points per team).
    Respects freeze — only shows data up to frozen tick.
    """
    is_frozen, frozen_tick = await get_freeze_state(db)

    # Get all active teams
    teams_result = await db.execute(
        select(Team).where(Team.is_active == True).order_by(Team.id)
    )
    teams = teams_result.scalars().all()
    if not teams:
        return AllTeamsPointTimeline(ticks=[], teams=[])

    # Get all ticks (filtered by freeze)
    ticks_q = select(Tick)
    if is_frozen and frozen_tick > 0:
        ticks_q = ticks_q.where(Tick.tick_number <= frozen_tick)
    ticks_result = await db.execute(ticks_q.order_by(Tick.tick_number))
    ticks = ticks_result.scalars().all()
    if not ticks:
        return AllTeamsPointTimeline(ticks=[], teams=[
            {"team_id": t.id, "team_name": t.name, "display_name": t.display_name, "points": []}
            for t in teams
        ])

    tick_numbers = [t.tick_number for t in ticks]

    # Get ALL tick results in one query (filtered by freeze)
    all_q = (
        select(TickResult, Tick)
        .join(Tick, TickResult.tick_id == Tick.id)
        .where(TickResult.king_team_id.isnot(None))
    )
    if is_frozen and frozen_tick > 0:
        all_q = all_q.where(Tick.tick_number <= frozen_tick)
    all_q = all_q.order_by(Tick.tick_number)
    results = await db.execute(all_q)
    all_rows = results.all()

    # Build per-tick-per-team points map
    # {team_id: {tick_number: points_in_that_tick}}
    team_tick_points = {t.id: {} for t in teams}
    for tr, tick in all_rows:
        tid = tr.king_team_id
        if tid in team_tick_points:
            team_tick_points[tid][tick.tick_number] = \
                team_tick_points[tid].get(tick.tick_number, 0) + tr.points_awarded

    # Build cumulative arrays
    team_data = []
    for team in teams:
        cumulative = 0
        points_over_time = []
        for tn in tick_numbers:
            cumulative += team_tick_points[team.id].get(tn, 0)
            points_over_time.append(cumulative)
        team_data.append({
            "team_id": team.id,
            "team_name": team.name,
            "display_name": team.display_name,
            "category": team.category,
            "points": points_over_time,
        })

    return AllTeamsPointTimeline(
        ticks=tick_numbers,
        teams=team_data,
    )


# ─── Public Topology Config ──────────────────────────────────────────────────

@router.get("/topology-config")
async def get_topology_config(db: AsyncSession = Depends(get_db)):
    """Get topology configuration for participant dashboard (legacy: icon+label only)"""
    result = await db.execute(
        select(GameConfig).where(GameConfig.key == "topology_config")
    )
    config = result.scalar_one_or_none()
    if config and config.value:
        import json
        try:
            return json.loads(config.value)
        except Exception:
            return {}
    return {}


@router.get("/topology-canvas")
async def get_topology_canvas(db: AsyncSession = Depends(get_db)):
    """Get full topology canvas state (nodes, links, labels) for participant dashboard"""
    result = await db.execute(
        select(GameConfig).where(GameConfig.key == "topology_canvas")
    )
    config = result.scalar_one_or_none()
    if config and config.value:
        import json
        try:
            return json.loads(config.value)
        except Exception:
            return {}
    return {}


# ─── Public Announcements ────────────────────────────────────────────────────

@router.get("/announcements")
async def get_announcements(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get recent announcements for participants (from Announcement table)"""
    result = await db.execute(
        select(Announcement)
        .where(Announcement.is_active == True)
        .order_by(desc(Announcement.created_at))
        .limit(limit)
    )
    return [
        {
            "id": a.id,
            "message": a.message,
            "type": a.type or "info",
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in result.scalars().all()
    ]


# ─── Public Event Details ────────────────────────────────────────────────────

@router.get("/event-info")
async def get_public_event_info(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns event details for dashboard / login page"""
    from app.config import get_settings
    _settings = get_settings()
    _keys = [
        "event_name", "event_subtitle", "event_description",
        "event_date", "event_location", "event_rules",
        "event_organizer", "event_contact",
    ]
    result = await db.execute(select(GameConfig).where(GameConfig.key.in_(_keys)))
    configs = {c.key: c.value for c in result.scalars().all()}
    return {
        "event_name": configs.get("event_name", _settings.event_name),
        "event_subtitle": configs.get("event_subtitle", _settings.event_subtitle),
        "event_description": configs.get("event_description", ""),
        "event_date": configs.get("event_date", ""),
        "event_location": configs.get("event_location", ""),
        "event_rules": configs.get("event_rules", ""),
        "event_organizer": configs.get("event_organizer", ""),
        "event_contact": configs.get("event_contact", ""),
    }


# ─── Public Categories ──────────────────────────────────────────────────────

@router.get("/categories")
async def get_public_categories(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns available team categories for registration"""
    import json as _json
    result = await db.execute(select(GameConfig).where(GameConfig.key == "team_categories"))
    config = result.scalar_one_or_none()
    if config and config.value:
        try:
            categories = _json.loads(config.value)
        except _json.JSONDecodeError:
            categories = [{"id": "default", "label": "Default"}]
    else:
        categories = [{"id": "default", "label": "Default"}]
    return {"categories": categories}
