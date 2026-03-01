"""
KoTH CTF Platform — Admin Router
Game control, score adjustments, audit log
"""
import json
import logging
from datetime import datetime
import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from sqlalchemy import select, update, desc, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import (
    GameConfig, Team, TeamScore, Score, Hill, Tick, TickResult,
    FirstBlood, AuditLog, Announcement
)
from pydantic import BaseModel, Field
from app.schemas import (
    GameControlRequest, GameStatusResponse, ScoreAdjustRequest, HillUpdate
)
from app.services.tick_engine import tick_engine
from app.services.ws_manager import ws_manager

logger = logging.getLogger("koth.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])
settings = get_settings()


def require_admin(x_admin_token: str = Header(...)):
    if x_admin_token != settings.api_admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return True


# ─── Game Control ────────────────────────────────────────────────────────────

@router.post("/game/control")
async def control_game(
    body: GameControlRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Start, pause, resume, or stop the game"""
    action = body.action

    if action == "start":
        if tick_engine.is_running:
            raise HTTPException(status_code=400, detail="Game already running")
        await tick_engine.start()
        await ws_manager.broadcast_game_event("game_started")
        logger.info("ADMIN: Game started")

    elif action == "pause":
        if not tick_engine.is_running:
            raise HTTPException(status_code=400, detail="Game not running")
        await tick_engine.pause()
        await ws_manager.broadcast_game_event("game_paused")
        logger.info("ADMIN: Game paused")

    elif action == "resume":
        if not tick_engine.is_paused:
            raise HTTPException(status_code=400, detail="Game not paused")
        await tick_engine.resume()
        await ws_manager.broadcast_game_event("game_resumed")
        logger.info("ADMIN: Game resumed")

    elif action == "stop":
        if not tick_engine.is_running:
            raise HTTPException(status_code=400, detail="Game not running")
        await tick_engine.stop()
        await ws_manager.broadcast_game_event("game_stopped")
        logger.info("ADMIN: Game stopped")

    db.add(AuditLog(
        event_type="game_control",
        actor="admin",
        details={"action": action},
    ))
    await db.commit()

    return {"detail": f"Game {action} executed", "status": tick_engine.get_status()}


@router.get("/game/preflight")
async def game_preflight(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """
    Pre-flight check before starting the game.
    Checks all critical components: DB, Redis, Hills, Scorebot, Agents, Teams, Config.
    Returns a list of check results with pass/fail/warning status.
    """
    from sqlalchemy import func, text

    checks = []

    # ── 1. Database ──
    try:
        await db.execute(text("SELECT 1"))
        checks.append({"id": "database", "label": "PostgreSQL Database", "status": "pass", "detail": "Connected"})
    except Exception as e:
        checks.append({"id": "database", "label": "PostgreSQL Database", "status": "fail", "detail": str(e)[:100]})

    # ── 2. Redis ──
    try:
        redis = request.app.state.redis
        if redis:
            await redis.ping()
            checks.append({"id": "redis", "label": "Redis Cache", "status": "pass", "detail": "Connected"})
        else:
            checks.append({"id": "redis", "label": "Redis Cache", "status": "fail", "detail": "Not initialized"})
    except Exception as e:
        checks.append({"id": "redis", "label": "Redis Cache", "status": "fail", "detail": str(e)[:100]})

    # ── 3. Active Hills ──
    try:
        hills_result = await db.execute(
            select(Hill).where(Hill.is_active == True).order_by(Hill.id)
        )
        hills = hills_result.scalars().all()
        if len(hills) == 0:
            checks.append({"id": "hills", "label": "Active Hills", "status": "fail", "detail": "No active hills configured"})
        else:
            misconfigured = []
            for h in hills:
                issues = []
                if not h.ip_address:
                    issues.append("no IP")
                if not h.king_file_path:
                    issues.append("no king.txt path")
                if issues:
                    misconfigured.append(f"{h.name}: {', '.join(issues)}")
            if misconfigured:
                checks.append({
                    "id": "hills", "label": f"Active Hills ({len(hills)})",
                    "status": "warning", "detail": f"Issues: {'; '.join(misconfigured)}"
                })
            else:
                checks.append({
                    "id": "hills", "label": f"Active Hills ({len(hills)})",
                    "status": "pass",
                    "detail": ", ".join(h.name for h in hills)
                })
    except Exception as e:
        checks.append({"id": "hills", "label": "Active Hills", "status": "fail", "detail": str(e)[:100]})

    # ── 4. Scorebot Connectivity ──
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{tick_engine.scorebot_url}/health")
            if resp.status_code == 200:
                checks.append({"id": "scorebot", "label": "Scorebot Service", "status": "pass", "detail": "Healthy"})
            else:
                checks.append({"id": "scorebot", "label": "Scorebot Service", "status": "warning", "detail": f"HTTP {resp.status_code}"})
    except Exception as e:
        checks.append({"id": "scorebot", "label": "Scorebot Service", "status": "fail", "detail": f"Unreachable: {str(e)[:80]}"})

    # ── 5. Agent Status per Hill ──
    agent_checks = []
    try:
        redis = request.app.state.redis
        if redis and hills:
            alive_count = 0
            dead_hills = []
            for h in hills:
                key = f"agent:report:{h.id}"
                raw = await redis.get(key)
                if raw:
                    alive_count += 1
                else:
                    dead_hills.append(h.name)
            if alive_count == len(hills):
                agent_checks.append({
                    "id": "agents", "label": f"Hill Agents ({alive_count}/{len(hills)})",
                    "status": "pass", "detail": "All agents reporting"
                })
            elif alive_count > 0:
                agent_checks.append({
                    "id": "agents", "label": f"Hill Agents ({alive_count}/{len(hills)})",
                    "status": "warning", "detail": f"Dead: {', '.join(dead_hills)}"
                })
            else:
                agent_checks.append({
                    "id": "agents", "label": f"Hill Agents (0/{len(hills)})",
                    "status": "warning", "detail": "No agents reporting (game can still run via SSH)"
                })
        else:
            agent_checks.append({"id": "agents", "label": "Hill Agents", "status": "warning", "detail": "Redis unavailable — cannot check"})
    except Exception as e:
        agent_checks.append({"id": "agents", "label": "Hill Agents", "status": "warning", "detail": str(e)[:100]})
    checks.extend(agent_checks)

    # ── 6. Registered Teams ──
    try:
        count_result = await db.execute(
            select(func.count(Team.id)).where(Team.is_active == True)
        )
        team_count = count_result.scalar() or 0
        if team_count == 0:
            checks.append({"id": "teams", "label": "Registered Teams", "status": "fail", "detail": "No teams registered"})
        elif team_count < 2:
            checks.append({"id": "teams", "label": f"Registered Teams ({team_count})", "status": "warning", "detail": "Only 1 team — game needs at least 2"})
        else:
            checks.append({"id": "teams", "label": f"Registered Teams ({team_count})", "status": "pass", "detail": f"{team_count} teams ready"})
    except Exception as e:
        checks.append({"id": "teams", "label": "Registered Teams", "status": "fail", "detail": str(e)[:100]})

    # ── 7. Game Config Sanity ──
    try:
        cfg = tick_engine.get_status()
        issues = []
        if tick_engine.game_duration <= 0:
            issues.append("Invalid game duration")
        if tick_engine.tick_interval <= 0:
            issues.append("Invalid tick interval")
        if cfg["status"] == "running":
            issues.append("Game is already running!")
        if cfg["status"] == "finished" and cfg["current_tick"] > 0:
            issues.append("Game already finished — reset first")

        if issues:
            checks.append({
                "id": "config", "label": "Game Configuration",
                "status": "fail" if "already running" in str(issues) else "warning",
                "detail": "; ".join(issues)
            })
        else:
            dur_h = tick_engine.game_duration // 3600
            dur_m = (tick_engine.game_duration % 3600) // 60
            checks.append({
                "id": "config", "label": "Game Configuration",
                "status": "pass",
                "detail": f"Duration: {dur_h}h{dur_m}m, Tick: {tick_engine.tick_interval}s, Grace: {tick_engine.grace_period}s"
            })
    except Exception as e:
        checks.append({"id": "config", "label": "Game Configuration", "status": "fail", "detail": str(e)[:100]})

    # ── Summary ──
    fail_count = sum(1 for c in checks if c["status"] == "fail")
    warn_count = sum(1 for c in checks if c["status"] == "warning")
    all_pass = fail_count == 0

    return {
        "checks": checks,
        "can_start": all_pass,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "summary": "All systems ready" if all_pass and warn_count == 0
                   else f"Ready with {warn_count} warning(s)" if all_pass
                   else f"{fail_count} critical issue(s) found"
    }


@router.get("/game/status", response_model=GameStatusResponse)
async def get_game_status(_: bool = Depends(require_admin)):
    """Get current game status"""
    status = tick_engine.get_status()
    return GameStatusResponse(
        status=status["status"],
        current_tick=status["current_tick"],
        start_time=status.get("game_start_time"),
        elapsed_seconds=status["elapsed_seconds"],
        remaining_seconds=status["remaining_seconds"],
        is_frozen=status["is_frozen"],
    )


# ─── Score Adjustment ────────────────────────────────────────────────────────

@router.post("/score/adjust")
async def adjust_score(
    body: ScoreAdjustRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Manually adjust a team's score"""
    team_result = await db.execute(select(Team).where(Team.id == body.team_id))
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Update team aggregate score
    ts_result = await db.execute(
        select(TeamScore).where(TeamScore.team_id == body.team_id)
    )
    ts = ts_result.scalar_one_or_none()
    if ts:
        ts.total_points += body.points
        ts.last_updated = datetime.utcnow()
    else:
        db.add(TeamScore(
            team_id=body.team_id,
            total_points=body.points,
        ))

    db.add(AuditLog(
        event_type="score_adjust",
        actor="admin",
        details={
            "team_id": body.team_id,
            "team_name": team.name,
            "points": body.points,
            "reason": body.reason,
        },
    ))
    await db.commit()

    await ws_manager.broadcast_game_event("score_adjusted", {
        "team_id": body.team_id,
        "team_name": team.name,
        "points": body.points,
        "reason": body.reason,
    })

    logger.info(f"ADMIN: Score adjusted: {team.name} {body.points:+d} ({body.reason})")
    return {"detail": f"Adjusted {team.name} by {body.points:+d} points"}


# ─── Game Reset ──────────────────────────────────────────────────────────────

@router.post("/game/reset")
async def reset_game(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Reset all game data (DESTRUCTIVE)"""
    if tick_engine.is_running:
        raise HTTPException(
            status_code=400, detail="Stop the game first before resetting"
        )

    # Clear all tick data
    await db.execute(delete(TickResult))
    await db.execute(delete(Tick))
    await db.execute(delete(FirstBlood))
    await db.execute(delete(Score))
    await db.execute(delete(TeamScore))

    # Re-init team scores
    teams_q = await db.execute(select(Team).where(Team.is_active == True))
    for team in teams_q.scalars().all():
        db.add(TeamScore(team_id=team.id))

    # Reset config
    await db.execute(
        update(GameConfig)
        .where(GameConfig.key == "game_status")
        .values(value="not_started")
    )
    await db.execute(
        update(GameConfig)
        .where(GameConfig.key == "current_tick")
        .values(value="0")
    )
    await db.execute(
        update(GameConfig)
        .where(GameConfig.key == "game_start_time")
        .values(value="")
    )

    tick_engine.current_tick = 0
    tick_engine.game_start_time = None

    db.add(AuditLog(
        event_type="game_reset",
        actor="admin",
        details={"message": "Full game reset"},
    ))
    await db.commit()

    await ws_manager.broadcast_game_event("game_reset")
    logger.info("ADMIN: Game data reset")
    return {"detail": "Game data reset successfully"}


# ─── Config Management ───────────────────────────────────────────────────────

@router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Get all game configuration values"""
    result = await db.execute(select(GameConfig).order_by(GameConfig.key))
    configs = result.scalars().all()
    return [
        {
            "key": c.key,
            "value": c.value,
            "description": c.description,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in configs
    ]


@router.put("/config/{key}")
async def update_config(
    key: str,
    value: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Update or create a game configuration value (upsert)"""
    result = await db.execute(select(GameConfig).where(GameConfig.key == key))
    config = result.scalar_one_or_none()
    if config:
        old_value = config.value
        config.value = value
        config.updated_at = datetime.utcnow()
    else:
        old_value = None
        config = GameConfig(key=key, value=value, description=f"Auto-created: {key}")
        db.add(config)

    db.add(AuditLog(
        event_type="config_updated",
        actor="admin",
        details={"key": key, "old_value": old_value, "new_value": value},
    ))
    await db.commit()
    return {"detail": f"Config '{key}' updated", "key": key, "value": value}


# ─── Audit Log ───────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit_log(
    limit: int = Query(50, le=500),
    event_type: str = Query(None),
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Get audit log entries"""
    query = select(AuditLog).order_by(desc(AuditLog.created_at))
    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    query = query.limit(limit)

    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "event_type": log.event_type,
            "actor": log.actor,
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# ─── Hill Management ─────────────────────────────────────────────────────────

@router.get("/hills/all")
async def list_all_hills(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """List ALL hills including inactive ones (admin only)"""
    result = await db.execute(select(Hill).order_by(Hill.id))
    hills = result.scalars().all()

    responses = []
    for hill in hills:
        king_q = await db.execute(
            select(Score, Team)
            .join(Team, Score.team_id == Team.id)
            .where(and_(Score.hill_id == hill.id, Score.current_king == True))
        )
        king_row = king_q.first()
        responses.append({
            "id": hill.id,
            "name": hill.name,
            "description": hill.description,
            "ip_address": hill.ip_address,
            "ssh_port": hill.ssh_port,
            "ssh_user": hill.ssh_user,
            "ssh_pass": hill.ssh_pass,
            "sla_check_type": hill.sla_check_type,
            "sla_check_url": hill.sla_check_url,
            "sla_check_port": hill.sla_check_port,
            "king_file_path": hill.king_file_path,
            "base_points": hill.base_points,
            "multiplier": hill.multiplier,
            "is_behind_pivot": hill.is_behind_pivot,
            "is_active": hill.is_active,
            "current_king": king_row[1].name if king_row else None,
        })
    return responses


@router.put("/hill/{hill_id}")
async def update_hill(
    hill_id: int,
    body: HillUpdate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Update hill configuration (partial update — only provided fields)"""
    result = await db.execute(select(Hill).where(Hill.id == hill_id))
    hill = result.scalar_one_or_none()
    if not hill:
        raise HTTPException(status_code=404, detail="Hill not found")

    changes = {}
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        old_value = getattr(hill, field)
        if old_value != value:
            setattr(hill, field, value)
            changes[field] = {"old": str(old_value), "new": str(value)}

    if not changes:
        return {"detail": "No changes detected", "hill_id": hill_id}

    db.add(AuditLog(
        event_type="hill_updated",
        actor="admin",
        details={"hill_id": hill_id, "hill_name": hill.name, "changes": changes},
    ))
    await db.commit()
    logger.info(f"ADMIN: Hill {hill.name} updated: {list(changes.keys())}")
    return {
        "detail": f"Hill '{hill.name}' updated ({', '.join(changes.keys())})",
        "hill_id": hill_id,
        "changes": changes,
    }


@router.put("/hill/{hill_id}/toggle")
async def toggle_hill(
    hill_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Enable or disable a hill"""
    result = await db.execute(select(Hill).where(Hill.id == hill_id))
    hill = result.scalar_one_or_none()
    if not hill:
        raise HTTPException(status_code=404, detail="Hill not found")

    hill.is_active = not hill.is_active
    db.add(AuditLog(
        event_type="hill_toggled",
        actor="admin",
        details={"hill_id": hill_id, "hill_name": hill.name, "is_active": hill.is_active},
    ))
    await db.commit()
    state = "enabled" if hill.is_active else "disabled"
    logger.info(f"ADMIN: Hill {hill.name} {state}")
    return {"detail": f"Hill '{hill.name}' {state}", "is_active": hill.is_active}


@router.delete("/hill/{hill_id}")
async def delete_hill(
    hill_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Permanently delete a hill and its scores"""
    result = await db.execute(select(Hill).where(Hill.id == hill_id))
    hill = result.scalar_one_or_none()
    if not hill:
        raise HTTPException(status_code=404, detail="Hill not found")

    hill_name = hill.name
    await db.execute(delete(TickResult).where(TickResult.hill_id == hill_id))
    await db.execute(delete(Score).where(Score.hill_id == hill_id))
    await db.execute(delete(FirstBlood).where(FirstBlood.hill_id == hill_id))
    await db.execute(delete(Hill).where(Hill.id == hill_id))

    db.add(AuditLog(
        event_type="hill_deleted",
        actor="admin",
        details={"hill_id": hill_id, "hill_name": hill_name},
    ))
    await db.commit()
    logger.info(f"ADMIN: Hill {hill_name} deleted")
    return {"detail": f"Hill '{hill_name}' deleted permanently"}


# ─── Reset King ──────────────────────────────────────────────────────────────

@router.post("/hill/{hill_id}/reset-king")
async def reset_hill_king(
    hill_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Reset the current king of a hill (set to nobody)"""
    result = await db.execute(select(Hill).where(Hill.id == hill_id))
    hill = result.scalar_one_or_none()
    if not hill:
        raise HTTPException(status_code=404, detail="Hill not found")

    # Clear current_king flag on all score rows for this hill
    await db.execute(
        update(Score)
        .where(Score.hill_id == hill_id)
        .values(current_king=False, consecutive_ticks=0)
    )

    # Update TeamScore hills_owned counts
    # Get all teams and recount their owned hills
    teams_result = await db.execute(select(Team).where(Team.is_active == True))
    for team in teams_result.scalars().all():
        owned = await db.execute(
            select(Score).where(
                and_(Score.team_id == team.id, Score.current_king == True)
            )
        )
        count = len(owned.scalars().all())
        await db.execute(
            update(TeamScore)
            .where(TeamScore.team_id == team.id)
            .values(hills_owned=count)
        )

    db.add(AuditLog(
        event_type="king_reset",
        actor="admin",
        details={"hill_id": hill_id, "hill_name": hill.name},
    ))
    await db.commit()

    # SSH into the hill server and write "nobody" to king.txt via scorebot
    ssh_reset_ok = False
    ssh_error = ""
    try:
        payload = {
            "ip_address": hill.ip_address,
            "ssh_port": hill.ssh_port or 22,
            "king_file_path": hill.king_file_path or "/root/king.txt",
        }
        if hill.ssh_user:
            payload["ssh_user"] = hill.ssh_user
        if hill.ssh_pass:
            payload["ssh_pass"] = hill.ssh_pass

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{tick_engine.scorebot_url}/reset-king",
                json=payload,
            )
            if resp.status_code == 200:
                ssh_reset_ok = True
                logger.info(f"ADMIN: king.txt on {hill.name} ({hill.ip_address}) reset to 'nobody' via scorebot")
            else:
                ssh_error = resp.text
                logger.warning(f"ADMIN: Scorebot reset-king failed for {hill.name}: {resp.status_code} {resp.text}")
    except Exception as e:
        ssh_error = str(e)
        logger.warning(f"ADMIN: Failed to reset king.txt on {hill.name} via scorebot: {e}")

    # Broadcast via WebSocket
    try:
        await ws_manager.broadcast_game_event("king_reset", {"hill_id": hill_id, "hill_name": hill.name})
    except Exception:
        pass

    logger.info(f"ADMIN: King reset for hill {hill.name}")

    if ssh_reset_ok:
        return {"detail": f"King of '{hill.name}' has been reset to nobody (DB + king.txt)"}
    else:
        return {"detail": f"King of '{hill.name}' reset in DB, but king.txt SSH write failed: {ssh_error}. The hill file may still have the old king."}


# ─── Registration Management ────────────────────────────────────────────────

@router.put("/registration/toggle")
async def toggle_registration(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Toggle team self-registration on/off"""
    settings.registration_enabled = not settings.registration_enabled
    state = "enabled" if settings.registration_enabled else "disabled"
    db.add(AuditLog(
        event_type="registration_toggled",
        actor="admin",
        details={"registration_enabled": settings.registration_enabled},
    ))
    await db.commit()
    logger.info(f"ADMIN: Registration {state}")
    return {"detail": f"Registration {state}", "registration_enabled": settings.registration_enabled}


@router.get("/registration/status")
async def admin_registration_status(_: bool = Depends(require_admin)):
    """Get registration status"""
    return {
        "registration_enabled": settings.registration_enabled,
        "registration_code": settings.registration_code,
    }


@router.post("/registration/rotate-code")
async def rotate_registration_code(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Generate a new random registration code"""
    import secrets
    old_code = settings.registration_code
    new_code = f"KOTH-{secrets.token_hex(4).upper()}"
    settings.registration_code = new_code

    db.add(AuditLog(
        event_type="registration_code_rotated",
        actor="admin",
        details={"old_code": old_code, "new_code": new_code},
    ))
    await db.commit()

    logger.info(f"ADMIN: Registration code rotated: {old_code} → {new_code}")
    return {
        "detail": "Registration code rotated",
        "new_code": new_code,
    }


# ─── Force Tick ──────────────────────────────────────────────────────────────

@router.post("/game/tick")
async def force_tick(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Force an immediate tick execution (works even if game not started for testing)"""

    try:
        await tick_engine.run_single_tick()
    except Exception as e:
        logger.error(f"Force tick failed: {e}")
        raise HTTPException(status_code=500, detail=f"Tick failed: {str(e)}")

    db.add(AuditLog(
        event_type="force_tick",
        actor="admin",
        details={"tick": tick_engine.current_tick},
    ))
    await db.commit()
    logger.info(f"ADMIN: Forced tick #{tick_engine.current_tick}")
    return {"detail": f"Tick #{tick_engine.current_tick} executed", "current_tick": tick_engine.current_tick}


# ─── Announcement Broadcast ──────────────────────────────────────────────────

class AnnouncementRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    type: str = Field(default="info", pattern="^(info|warning|danger)$")


@router.post("/announcement")
async def broadcast_announcement(
    body: AnnouncementRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Broadcast an announcement to all WebSocket clients and save to DB"""
    message = body.message
    msg_type = body.type

    # Save to announcements table
    ann = Announcement(message=message, type=msg_type)
    db.add(ann)
    await db.flush()  # get the id

    await ws_manager.broadcast_game_event("announcement", {
        "message": message,
        "type": msg_type,
        "timestamp": datetime.utcnow().isoformat(),
        "id": ann.id,
    })

    db.add(AuditLog(
        event_type="announcement",
        actor="admin",
        details={"message": message, "type": msg_type, "announcement_id": ann.id},
    ))
    await db.commit()
    logger.info(f"ADMIN: Announcement broadcast #{ann.id}: {message}")
    return {"detail": "Announcement sent", "id": ann.id}


@router.get("/announcements")
async def list_announcements(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """List all announcements (newest first)"""
    result = await db.execute(
        select(Announcement).order_by(desc(Announcement.created_at))
    )
    return [
        {
            "id": a.id,
            "message": a.message,
            "type": a.type,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }
        for a in result.scalars().all()
    ]


class AnnouncementUpdate(BaseModel):
    message: str = Field(None, min_length=1, max_length=1000)
    type: str = Field(None, pattern="^(info|warning|danger)$")


@router.put("/announcement/{ann_id}")
async def update_announcement(
    ann_id: int,
    body: AnnouncementUpdate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Edit an existing announcement"""
    result = await db.execute(select(Announcement).where(Announcement.id == ann_id))
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(404, "Announcement not found")

    changes = {}
    if body.message is not None and body.message != ann.message:
        changes["message"] = {"old": ann.message, "new": body.message}
        ann.message = body.message
    if body.type is not None and body.type != ann.type:
        changes["type"] = {"old": ann.type, "new": body.type}
        ann.type = body.type

    if not changes:
        return {"detail": "No changes"}

    # Broadcast updated announcement
    await ws_manager.broadcast_game_event("announcement_updated", {
        "id": ann.id,
        "message": ann.message,
        "type": ann.type,
        "timestamp": datetime.utcnow().isoformat(),
    })

    db.add(AuditLog(
        event_type="announcement_edited",
        actor="admin",
        details={"announcement_id": ann.id, "changes": changes},
    ))
    await db.commit()
    logger.info(f"ADMIN: Announcement #{ann.id} edited")
    return {"detail": "Announcement updated", "changes": changes}


@router.delete("/announcement/{ann_id}")
async def delete_announcement(
    ann_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Delete an announcement"""
    result = await db.execute(select(Announcement).where(Announcement.id == ann_id))
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(404, "Announcement not found")

    old_msg = ann.message
    await db.delete(ann)

    db.add(AuditLog(
        event_type="announcement_deleted",
        actor="admin",
        details={"announcement_id": ann_id, "message": old_msg},
    ))
    await db.commit()
    logger.info(f"ADMIN: Announcement #{ann_id} deleted")
    return {"detail": "Announcement deleted"}


@router.delete("/announcements/bulk")
async def bulk_delete_announcements(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Delete multiple announcements by IDs, or all if ids=[]"""
    body = await request.json()
    ids = body.get("ids", [])

    if ids:
        result = await db.execute(
            select(Announcement).where(Announcement.id.in_(ids))
        )
        anns = result.scalars().all()
        count = len(anns)
        for a in anns:
            await db.delete(a)
    else:
        # Delete ALL announcements
        result = await db.execute(select(Announcement))
        anns = result.scalars().all()
        count = len(anns)
        for a in anns:
            await db.delete(a)

    db.add(AuditLog(
        event_type="announcements_bulk_deleted",
        actor="admin",
        details={"count": count, "ids": ids if ids else "all"},
    ))
    await db.commit()
    logger.info(f"ADMIN: Bulk deleted {count} announcements")
    return {"detail": f"{count} announcement(s) deleted", "count": count}


# ─── Admin Token Rotation ────────────────────────────────────────────────────

@router.post("/rotate-token")
async def rotate_admin_token(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Rotate the admin API token. Returns the new token (save it!)"""
    import secrets
    new_token = f"admin-{secrets.token_hex(24)}"
    old_token_prefix = settings.api_admin_token[:8] + "..."

    # Update the runtime settings
    settings.api_admin_token = new_token

    db.add(AuditLog(
        event_type="admin_token_rotated",
        actor="admin",
        details={"old_token_prefix": old_token_prefix},
    ))
    await db.commit()

    logger.info(f"ADMIN: Admin token rotated (old prefix: {old_token_prefix})")
    return {
        "detail": "Admin token rotated successfully. Save the new token!",
        "new_token": new_token,
    }


# ─── Team Export ─────────────────────────────────────────────────────────────

@router.get("/teams/export")
async def export_teams(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Export all teams with scores for CSV download"""
    result = await db.execute(
        select(Team, TeamScore)
        .outerjoin(TeamScore, Team.id == TeamScore.team_id)
        .order_by(Team.id)
    )
    rows = result.all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "display_name": t.display_name,
            "category": t.category,
            "vpn_ip": t.vpn_ip,
            "token": t.token,
            "is_active": t.is_active,
            "total_points": ts.total_points if ts else 0,
            "hills_owned": ts.hills_owned if ts else 0,
            "total_ticks_as_king": ts.total_ticks_as_king if ts else 0,
            "first_bloods": ts.first_bloods if ts else 0,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t, ts in rows
    ]


# ─── Scoreboard Freeze Control ───────────────────────────────────────────────

@router.post("/scoreboard/freeze")
async def freeze_scoreboard(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Manually freeze the public scoreboard"""
    frozen_tick = tick_engine.current_tick

    # Set in-memory state (for this worker)
    tick_engine.manual_freeze = True
    tick_engine.frozen_at_tick = frozen_tick

    # Persist to DB so ALL workers see the freeze
    for cfg_key, cfg_val in [("manual_freeze", "true"), ("frozen_at_tick", str(frozen_tick))]:
        result = await db.execute(select(GameConfig).where(GameConfig.key == cfg_key))
        cfg = result.scalar_one_or_none()
        if cfg:
            cfg.value = cfg_val
            cfg.updated_at = datetime.utcnow()
        else:
            db.add(GameConfig(key=cfg_key, value=cfg_val, description=f"Freeze control: {cfg_key}"))

    db.add(AuditLog(
        event_type="scoreboard_frozen",
        actor="admin",
        details={"manual": True, "frozen_at_tick": frozen_tick},
    ))
    await db.commit()
    await ws_manager.broadcast_game_event("scoreboard_frozen")
    logger.info(f"ADMIN: Scoreboard manually frozen at tick {frozen_tick}")
    return {"detail": "Scoreboard frozen", "frozen_at_tick": frozen_tick}


@router.post("/scoreboard/unfreeze")
async def unfreeze_scoreboard(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Manually unfreeze the public scoreboard"""
    # Set in-memory state (for this worker)
    tick_engine.manual_freeze = False
    tick_engine.frozen_at_tick = 0

    # Persist to DB so ALL workers see the unfreeze
    for cfg_key, cfg_val in [("manual_freeze", "false"), ("frozen_at_tick", "0")]:
        result = await db.execute(select(GameConfig).where(GameConfig.key == cfg_key))
        cfg = result.scalar_one_or_none()
        if cfg:
            cfg.value = cfg_val
            cfg.updated_at = datetime.utcnow()
        else:
            db.add(GameConfig(key=cfg_key, value=cfg_val, description=f"Freeze control: {cfg_key}"))

    db.add(AuditLog(
        event_type="scoreboard_unfrozen",
        actor="admin",
        details={"manual": True},
    ))
    await db.commit()
    await ws_manager.broadcast_game_event("scoreboard_unfrozen")
    logger.info("ADMIN: Scoreboard unfrozen")
    return {"detail": "Scoreboard unfrozen"}


# ─── Dashboard Stats ─────────────────────────────────────────────────────────

@router.get("/stats")
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Get admin dashboard statistics"""
    from sqlalchemy import func

    teams_count = await db.execute(
        select(func.count(Team.id)).where(Team.is_active == True)
    )
    hills_count = await db.execute(
        select(func.count(Hill.id)).where(Hill.is_active == True)
    )
    ticks_count = await db.execute(select(func.count(Tick.id)))
    fb_count = await db.execute(select(func.count(FirstBlood.hill_id)))

    status = tick_engine.get_status()

    return {
        "game_status": status["status"],
        "current_tick": status["current_tick"],
        "elapsed_seconds": status["elapsed_seconds"],
        "remaining_seconds": status["remaining_seconds"],
        "is_frozen": status["is_frozen"],
        "teams_count": teams_count.scalar(),
        "hills_count": hills_count.scalar(),
        "total_ticks": ticks_count.scalar(),
        "first_bloods_count": fb_count.scalar(),
        "ws_connections": ws_manager.connection_count,
        "registration_enabled": settings.registration_enabled,
        "is_manually_frozen": getattr(tick_engine, 'manual_freeze', False),
    }


# ─── Dual-Verification Status ───────────────────────────────────────────────

@router.get("/verification/status")
async def get_verification_status(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
    tick_number: int = Query(None, description="Specific tick number (default: latest)"),
    limit: int = Query(10, ge=1, le=100, description="Number of ticks to return"),
):
    """
    Get dual-verification status for tick results.
    Shows SSH vs Agent verification per hill per tick.
    """
    from sqlalchemy import func

    # Get the target tick(s)
    if tick_number:
        ticks_q = await db.execute(
            select(Tick).where(Tick.tick_number == tick_number)
        )
        ticks = [ticks_q.scalar_one_or_none()]
        ticks = [t for t in ticks if t]
    else:
        ticks_q = await db.execute(
            select(Tick)
            .order_by(desc(Tick.tick_number))
            .limit(limit)
        )
        ticks = ticks_q.scalars().all()

    if not ticks:
        return {"ticks": [], "summary": {"total_checks": 0}}

    result_ticks = []
    total_ssh = 0
    total_agent = 0
    total_both = 0
    total_none = 0

    for tick in ticks:
        results_q = await db.execute(
            select(TickResult, Hill.name)
            .join(Hill, TickResult.hill_id == Hill.id)
            .where(TickResult.tick_id == tick.id)
            .order_by(TickResult.hill_id)
        )
        rows = results_q.all()

        tick_results = []
        for tr, hill_name in rows:
            ssh_v = getattr(tr, 'ssh_verified', False) or False
            agent_v = getattr(tr, 'agent_verified', False) or False
            v_count = getattr(tr, 'verification_count', 0) or 0

            if ssh_v:
                total_ssh += 1
            if agent_v:
                total_agent += 1
            if ssh_v and agent_v:
                total_both += 1
            if not ssh_v and not agent_v:
                total_none += 1

            # Get king team name
            king_name = None
            if tr.king_team_id:
                team_q = await db.execute(
                    select(Team.name).where(Team.id == tr.king_team_id)
                )
                king_name = team_q.scalar_one_or_none()

            tick_results.append({
                "hill_id": tr.hill_id,
                "hill_name": hill_name,
                "king_team_name": king_name,
                "king_team_id": tr.king_team_id,
                "sla_status": tr.sla_status,
                "points_awarded": tr.points_awarded,
                "ssh_verified": ssh_v,
                "agent_verified": agent_v,
                "ssh_king_name": getattr(tr, 'ssh_king_name', None),
                "agent_king_name": getattr(tr, 'agent_king_name', None),
                "verification_count": v_count,
                "check_duration_ms": tr.check_duration_ms,
                "error_message": tr.error_message,
            })

        result_ticks.append({
            "tick_number": tick.tick_number,
            "started_at": tick.started_at.isoformat() if tick.started_at else None,
            "completed_at": tick.completed_at.isoformat() if tick.completed_at else None,
            "status": tick.status,
            "results": tick_results,
        })

    total_checks = total_ssh + total_agent - total_both + total_none

    return {
        "ticks": result_ticks,
        "summary": {
            "total_checks": len([r for t in result_ticks for r in t["results"]]),
            "ssh_verified_count": total_ssh,
            "agent_verified_count": total_agent,
            "both_verified_count": total_both,
            "none_verified_count": total_none,
        },
    }


@router.get("/hills/agents")
async def get_hill_agent_tokens(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Get agent tokens for all hills (admin only)"""
    hills_q = await db.execute(
        select(Hill).order_by(Hill.id)
    )
    hills = hills_q.scalars().all()

    return [
        {
            "hill_id": h.id,
            "name": h.name,
            "ip_address": h.ip_address,
            "agent_token": h.agent_token,
            "is_active": h.is_active,
        }
        for h in hills
    ]


@router.post("/hills/check-reachability")
async def check_hill_reachability(
    request: Request,
    _: bool = Depends(require_admin),
):
    """Check if a host is reachable from the KoTH server (TCP connect + DNS resolve)"""
    import asyncio
    import socket
    import time

    body = await request.json()
    host = body.get("host", "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="host is required")

    async def _check():
        results = []
        # Resolve DNS first
        try:
            loop = asyncio.get_event_loop()
            addr = await loop.run_in_executor(None, socket.gethostbyname, host)
            results.append(f"DNS resolved: {host} → {addr}")
        except socket.gaierror as e:
            return {"host": host, "reachable": False, "rtt": None, "output": f"DNS resolution failed: {e}"}

        # Try TCP connect on common ports (22, 80, 443, 8000, 8080)
        ports_to_try = [22, 80, 8000, 8080, 443]
        best_rtt = None
        any_reachable = False
        for port in ports_to_try:
            try:
                start = time.monotonic()
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(addr, port), timeout=3
                )
                elapsed = (time.monotonic() - start) * 1000
                writer.close()
                await writer.wait_closed()
                results.append(f"TCP:{port} ✓ ({elapsed:.1f}ms)")
                any_reachable = True
                if best_rtt is None or elapsed < best_rtt:
                    best_rtt = elapsed
            except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
                results.append(f"TCP:{port} ✗")

        # Also try raw socket connect (ICMP-like via TCP SYN to port 7)
        if not any_reachable:
            try:
                start = time.monotonic()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                await asyncio.get_event_loop().run_in_executor(None, lambda: sock.connect_ex((addr, 7)))
                elapsed = (time.monotonic() - start) * 1000
                sock.close()
                results.append(f"TCP:7 connect_ex ({elapsed:.1f}ms)")
                # connect_ex returns 0 or errno, either way host responded
                any_reachable = elapsed < 2900  # if it responded within timeout
                if any_reachable and (best_rtt is None or elapsed < best_rtt):
                    best_rtt = elapsed
            except Exception:
                pass

        rtt_str = f"{best_rtt:.1f} ms" if best_rtt is not None else None
        return {"host": host, "reachable": any_reachable, "rtt": rtt_str, "output": "\n".join(results)}

    try:
        return await asyncio.wait_for(_check(), timeout=20)
    except asyncio.TimeoutError:
        return {"host": host, "reachable": False, "rtt": None, "output": "Check timed out (20s)"}
    except Exception as e:
        return {"host": host, "reachable": False, "rtt": None, "output": str(e)}


@router.post("/hills/{hill_id}/agent-token")
async def set_hill_agent_token(
    hill_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Generate/regenerate agent token for a hill"""
    import secrets

    hill_q = await db.execute(select(Hill).where(Hill.id == hill_id))
    hill = hill_q.scalar_one_or_none()
    if not hill:
        raise HTTPException(status_code=404, detail="Hill not found")

    new_token = f"agent-{hill.name.lower().replace(' ', '-')}-{secrets.token_hex(16)}"
    hill.agent_token = new_token

    db.add(AuditLog(
        event_type="agent_token_generated",
        actor="admin",
        details={"hill_id": hill_id, "hill_name": hill.name},
    ))
    await db.commit()

    logger.info(f"ADMIN: Generated agent token for hill {hill.name}")
    return {
        "hill_id": hill_id,
        "hill_name": hill.name,
        "agent_token": new_token,
    }
