"""
KoTH CTF Platform — Tick Engine
Manages game ticks and orchestrates hill checks.

Dual-Verification: Each tick performs both SSH-based (scorebot) and
agent-based king.txt verification. Results are merged before scoring.
"""
import asyncio
import logging
import time
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import async_session
from app.models import Tick, Hill, GameConfig
from app.services.scoring import ScoringEngine

logger = logging.getLogger("koth.tick_engine")


class TickEngine:
    """Async tick engine that runs the game loop"""

    def __init__(self):
        self.is_running = False
        self.is_paused = False
        self.current_tick = 0
        self.tick_interval = 60
        self.grace_period = 300
        self.game_start_time: Optional[datetime] = None
        self.game_duration = 21600  # 6 hours in seconds
        self.freeze_before_end = 1800
        self.scorebot_url = "http://scorebot:8081"
        self._task: Optional[asyncio.Task] = None
        self._ws_broadcast_callback = None
        self._redis = None  # Redis instance for agent reports
        self.manual_freeze = False  # Manual scoreboard freeze by admin
        self.frozen_at_tick = 0  # Tick number when freeze started
        self._pause_elapsed = 0  # Accumulated elapsed seconds when paused
        self._pause_start_time: Optional[datetime] = None  # When current pause started
        self._game_end_elapsed = 0  # Final elapsed seconds when game finished

    def set_ws_callback(self, callback):
        """Set WebSocket broadcast callback"""
        self._ws_broadcast_callback = callback

    def set_redis(self, redis):
        """Set Redis instance for agent report lookups"""
        self._redis = redis

    async def load_config(self, db: AsyncSession):
        """Load configuration from database"""
        scoring = ScoringEngine(db)
        self.tick_interval = await scoring.get_config_int("tick_interval", 60)
        self.grace_period = await scoring.get_config_int("grace_period", 300)
        self.game_duration = await scoring.get_config_int("game_duration", 21600)
        self.freeze_before_end = await scoring.get_config_int("freeze_before_end", 1800)
        self.current_tick = await scoring.get_config_int("current_tick", 0)

        start_time_str = await scoring.get_config("game_start_time")
        if start_time_str:
            try:
                self.game_start_time = datetime.fromisoformat(start_time_str)
            except (ValueError, TypeError):
                pass

        # Restore game running state from DB
        persisted_status = await scoring.get_config("game_status")
        if persisted_status == "running":
            self.is_running = True
            self.is_paused = False
        elif persisted_status == "paused":
            self.is_running = True
            self.is_paused = True
        elif persisted_status == "finished":
            self.is_running = False
            self.is_paused = False
            # Restore frozen elapsed time
            self._game_end_elapsed = await scoring.get_config_int("game_end_elapsed", 0)

        # Restore freeze state from DB (shared across workers)
        manual_freeze_val = await scoring.get_config("manual_freeze")
        if manual_freeze_val == "true":
            self.manual_freeze = True
            self.frozen_at_tick = await scoring.get_config_int("frozen_at_tick", 0)
            logger.info(f"Restored freeze state from DB: frozen_at_tick={self.frozen_at_tick}")

    async def start(self):
        """Start the tick engine"""
        if self.is_running:
            logger.warning("Tick engine already running")
            return

        async with async_session() as db:
            scoring = ScoringEngine(db)

            # Set game start time
            self.game_start_time = datetime.utcnow()
            await scoring.set_config("game_start_time", self.game_start_time.isoformat())
            await scoring.set_config("game_status", "running")
            await db.commit()

            await self.load_config(db)

        self.is_running = True
        self.is_paused = False
        self._task = asyncio.create_task(self._game_loop())

        logger.info(
            f"🎮 GAME STARTED! Tick interval: {self.tick_interval}s, "
            f"Grace period: {self.grace_period}s"
        )

    async def pause(self):
        """Pause the tick engine"""
        self.is_paused = True
        self._pause_start_time = datetime.utcnow()
        async with async_session() as db:
            scoring = ScoringEngine(db)
            await scoring.set_config("game_status", "paused")
            await db.commit()
        logger.info("⏸️ GAME PAUSED")

    async def resume(self):
        """Resume the tick engine"""
        # Accumulate paused duration so elapsed time is correct
        if self._pause_start_time:
            paused_seconds = (datetime.utcnow() - self._pause_start_time).total_seconds()
            self._pause_elapsed += paused_seconds
            self._pause_start_time = None
            logger.info(f"Accumulated pause: {paused_seconds:.0f}s (total paused: {self._pause_elapsed:.0f}s)")
        self.is_paused = False
        async with async_session() as db:
            scoring = ScoringEngine(db)
            await scoring.set_config("game_status", "running")
            await db.commit()
        logger.info("▶️ GAME RESUMED")

    async def stop(self):
        """Stop the tick engine"""
        # Calculate and freeze the final elapsed time before stopping
        if self.game_start_time:
            raw_elapsed = (datetime.utcnow() - self.game_start_time).total_seconds()
            self._game_end_elapsed = int(max(0, raw_elapsed - self._pause_elapsed))
            # Cap at game duration
            self._game_end_elapsed = min(self._game_end_elapsed, self.game_duration)
        self.is_running = False
        if self._task:
            self._task.cancel()
        async with async_session() as db:
            scoring = ScoringEngine(db)
            await scoring.set_config("game_status", "finished")
            await scoring.set_config("game_end_elapsed", str(self._game_end_elapsed))
            await db.commit()
        logger.info(f"🏁 GAME FINISHED — final elapsed: {self._game_end_elapsed}s")

    async def _game_loop(self):
        """Main game loop - runs ticks at configured interval"""
        logger.info(f"Grace period: waiting {self.grace_period}s before first tick...")

        # Grace period
        await asyncio.sleep(self.grace_period)

        while self.is_running:
            if self.is_paused:
                await asyncio.sleep(1)
                continue

            # Check game duration (subtract paused time)
            if self.game_start_time:
                elapsed = (datetime.utcnow() - self.game_start_time).total_seconds() - self._pause_elapsed
                if elapsed >= self.game_duration:
                    logger.info("Game duration reached, stopping...")
                    await self.stop()
                    break

            tick_start = time.time()

            try:
                await self._execute_tick()
            except Exception as e:
                logger.error(f"Tick #{self.current_tick} failed: {e}", exc_info=True)

            # Wait for next tick (accounting for tick processing time)
            tick_duration = time.time() - tick_start
            sleep_time = max(0, self.tick_interval - tick_duration)
            logger.debug(
                f"Tick took {tick_duration:.2f}s, sleeping {sleep_time:.2f}s"
            )
            await asyncio.sleep(sleep_time)

    async def _execute_tick(self):
        """Execute a single tick: check all hills via SSH + agent dual-verify"""
        async with async_session() as db:
            # Always sync current_tick from DB to survive restarts
            max_tick = await db.execute(select(func.coalesce(func.max(Tick.tick_number), 0)))
            db_tick = max_tick.scalar() or 0
            if db_tick > self.current_tick:
                logger.info(f"Synced current_tick from DB: {self.current_tick} → {db_tick}")
                self.current_tick = db_tick

        self.current_tick += 1
        tick_start = datetime.utcnow()

        logger.info(f"━━━ TICK #{self.current_tick} START ━━━")

        async with async_session() as db:
            # Create tick record
            tick = Tick(
                tick_number=self.current_tick,
                started_at=tick_start,
                status="running",
            )
            db.add(tick)
            await db.flush()

            # Get active hills
            hills_result = await db.execute(
                select(Hill).where(Hill.is_active == True)
            )
            hills = hills_result.scalars().all()

            if not hills:
                logger.warning("No active hills found!")
                tick.status = "completed"
                tick.completed_at = datetime.utcnow()
                await db.commit()
                return

            # Step 1: SSH-based check via scorebot
            ssh_results = await self._check_all_hills(hills)

            # Step 2: Get latest agent reports from Redis
            agent_reports = await self._get_agent_reports()

            # Step 3: Merge SSH results + agent reports into dual-verified results
            check_results = self._merge_verification_results(
                ssh_results, agent_reports, hills
            )

            # Process results through scoring engine
            scoring = ScoringEngine(db)
            tick_summary = await scoring.process_tick_results(tick, check_results)

            # Broadcast via WebSocket
            # When scoreboard is frozen, only broadcast to admin channel
            status = self.get_status()
            is_frozen = status.get("is_frozen", False)

            if self._ws_broadcast_callback:
                from app.services.ws_manager import ws_manager

                # Always send to admin channel
                await ws_manager.broadcast({
                    "type": "tick_update",
                    "data": tick_summary,
                    "timestamp": datetime.utcnow().isoformat(),
                }, "admin")

                if not is_frozen:
                    # Public scoreboard channel only when NOT frozen
                    await ws_manager.broadcast({
                        "type": "tick_update",
                        "data": tick_summary,
                        "timestamp": datetime.utcnow().isoformat(),
                    }, "scoreboard")

                # Broadcast king changes
                for change in tick_summary.get("king_changes", []):
                    await ws_manager.broadcast({
                        "type": "king_change",
                        "data": change,
                        "timestamp": datetime.utcnow().isoformat(),
                    }, "admin")
                    if not is_frozen:
                        await ws_manager.broadcast({
                            "type": "king_change",
                            "data": change,
                            "timestamp": datetime.utcnow().isoformat(),
                        }, "scoreboard")

                # Broadcast first bloods
                for fb in tick_summary.get("first_bloods", []):
                    await ws_manager.broadcast({
                        "type": "first_blood",
                        "data": fb,
                        "timestamp": datetime.utcnow().isoformat(),
                    }, "admin")
                    if not is_frozen:
                        await ws_manager.broadcast({
                            "type": "first_blood",
                            "data": fb,
                            "timestamp": datetime.utcnow().isoformat(),
                        }, "scoreboard")

        # Persist current_tick to game_config so it survives restarts
        async with async_session() as db:
            scoring = ScoringEngine(db)
            await scoring.set_config("current_tick", str(self.current_tick))
            await db.commit()

        logger.info(f"━━━ TICK #{self.current_tick} COMPLETE ━━━")

    async def _check_all_hills(self, hills: list) -> List[Dict]:
        """Call scorebot to check all hills in parallel"""
        results = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = []
            for hill in hills:
                tasks.append(self._check_single_hill(client, hill))

            # Run all checks in parallel
            check_results = await asyncio.gather(*tasks, return_exceptions=True)

            for hill, result in zip(hills, check_results):
                if isinstance(result, Exception):
                    logger.error(f"Check failed for {hill.name}: {result}")
                    results.append({
                        "hill_id": hill.id,
                        "king_team_name": None,
                        "sla_status": False,
                        "raw_king_txt": None,
                        "check_duration_ms": 0,
                        "error_message": str(result),
                    })
                else:
                    results.append(result)

        return results

    async def _check_single_hill(self, client: httpx.AsyncClient, hill) -> Dict:
        """Check a single hill via scorebot API"""
        try:
            payload = {
                    "hill_id": hill.id,
                    "ip_address": hill.ip_address,
                    "ssh_port": hill.ssh_port,
                    "king_file_path": hill.king_file_path,
                    "sla_check_type": hill.sla_check_type,
                    "sla_check_url": hill.sla_check_url,
                    "sla_check_port": hill.sla_check_port,
            }
            # Per-hill SSH credentials override global defaults
            if getattr(hill, 'ssh_user', None):
                payload["ssh_user"] = hill.ssh_user
            if getattr(hill, 'ssh_pass', None):
                payload["ssh_pass"] = hill.ssh_pass

            response = await client.post(
                f"{self.scorebot_url}/check",
                json=payload,
                timeout=20.0,
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "hill_id": hill.id,
                    "king_team_name": None,
                    "sla_status": False,
                    "raw_king_txt": None,
                    "check_duration_ms": 0,
                    "error_message": f"Scorebot returned {response.status_code}",
                }
        except Exception as e:
            return {
                "hill_id": hill.id,
                "king_team_name": None,
                "sla_status": False,
                "raw_king_txt": None,
                "check_duration_ms": 0,
                "error_message": str(e),
            }

    async def _get_agent_reports(self) -> Dict[int, Dict]:
        """Fetch latest agent reports from Redis for all hills"""
        try:
            from app.routers.agent import get_latest_agent_reports
            if self._redis:
                reports = await get_latest_agent_reports(self._redis)
                logger.info(f"Agent reports available for {len(reports)} hills")
                return reports
            else:
                logger.debug("Redis not available, skipping agent reports")
                return {}
        except Exception as e:
            logger.warning(f"Failed to fetch agent reports: {e}")
            return {}

    def _merge_verification_results(
        self,
        ssh_results: List[Dict],
        agent_reports: Dict[int, Dict],
        hills: list,
    ) -> List[Dict]:
        """
        Merge SSH-based scorebot results with agent-based reports.

        Logic:
        - Both SSH and agent verified → verification_count=2, use agreed king name
        - Only SSH verified → verification_count=1, use SSH king name
        - Only agent verified → verification_count=1, use agent king name
        - Neither verified → verification_count=0, no king

        If both verified but disagree on king name, SSH takes priority
        (agent might have stale data) but both names are recorded.
        """
        merged = []

        for ssh_result in ssh_results:
            hill_id = ssh_result["hill_id"]
            agent_report = agent_reports.get(hill_id)

            # Determine SSH verification status
            ssh_ok = (
                ssh_result.get("king_team_name") is not None
                and not ssh_result.get("error_message")
            ) or (
                ssh_result.get("raw_king_txt") is not None
                and not ssh_result.get("error_message")
            )
            ssh_king = ssh_result.get("king_team_name") or ""

            # Determine agent verification status
            agent_ok = False
            agent_king = ""
            if agent_report:
                agent_ok = True
                agent_king = agent_report.get("king_name", "")

            # Calculate verification count
            verify_count = (1 if ssh_ok else 0) + (1 if agent_ok else 0)

            # Determine final king name:
            # - If both agree → use that name
            # - If only SSH → use SSH name
            # - If only agent → use agent name
            # - If both disagree → use SSH (more authoritative, real-time)
            if ssh_ok and agent_ok:
                # Both verified — prefer SSH if they disagree
                final_king = ssh_king if ssh_king else agent_king
                if ssh_king and agent_king and ssh_king.lower() != agent_king.lower():
                    logger.warning(
                        f"Hill {hill_id}: SSH says '{ssh_king}' but agent says "
                        f"'{agent_king}' — using SSH (authoritative)"
                    )
            elif ssh_ok:
                final_king = ssh_king
            elif agent_ok:
                final_king = agent_king
                logger.info(
                    f"Hill {hill_id}: SSH failed but agent reports king='{agent_king}'"
                )
            else:
                final_king = None

            # Determine SLA status: SSH SLA takes priority, but if SSH failed
            # and agent reports SLA ok, use agent's SLA
            sla_status = ssh_result.get("sla_status", False)
            if not sla_status and agent_ok:
                sla_status = agent_report.get("sla_status", False)

            # Build merged result
            merged_result = {
                "hill_id": hill_id,
                "king_team_name": final_king,
                "sla_status": sla_status,
                "raw_king_txt": ssh_result.get("raw_king_txt") or (
                    agent_report.get("raw_king_txt") if agent_report else None
                ),
                "check_duration_ms": ssh_result.get("check_duration_ms", 0),
                "error_message": ssh_result.get("error_message"),
                # Dual-verification metadata
                "ssh_verified": ssh_ok,
                "agent_verified": agent_ok,
                "ssh_king_name": ssh_king or None,
                "agent_king_name": agent_king or None,
                "verification_count": verify_count,
            }
            merged.append(merged_result)

            # Log verification status
            status_icon = "✅" if verify_count == 2 else ("⚠️" if verify_count == 1 else "❌")
            logger.info(
                f"Hill {hill_id}: {status_icon} {verify_count}/2 verified | "
                f"SSH: {'✓' if ssh_ok else '✗'} ({ssh_king or '-'}) | "
                f"Agent: {'✓' if agent_ok else '✗'} ({agent_king or '-'}) | "
                f"Final: {final_king or '(none)'}"
            )

        return merged

    async def run_single_tick(self):
        """Run a single tick manually (force tick)"""
        # Ensure config is loaded (important for force-tick without start)
        async with async_session() as db:
            await self.load_config(db)
        await self._execute_tick()

    def get_status(self) -> Dict:
        """Get current engine status"""
        elapsed = 0
        remaining = self.game_duration

        # Determine status first
        status = "not_started"
        if self.is_running and not self.is_paused:
            status = "running"
        elif self.is_running and self.is_paused:
            status = "paused"
        elif not self.is_running and self.current_tick > 0:
            status = "finished"

        if status == "finished":
            # Use frozen elapsed time — don't keep counting from game_start_time
            elapsed = self._game_end_elapsed if self._game_end_elapsed > 0 else self.game_duration
            remaining = max(0, self.game_duration - elapsed)
        elif self.game_start_time:
            raw_elapsed = (datetime.utcnow() - self.game_start_time).total_seconds()
            # Subtract accumulated pause time
            current_pause = 0
            if self.is_paused and self._pause_start_time:
                current_pause = (datetime.utcnow() - self._pause_start_time).total_seconds()
            elapsed = int(raw_elapsed - self._pause_elapsed - current_pause)
            elapsed = max(0, elapsed)
            remaining = max(0, self.game_duration - elapsed)

        is_frozen = self.manual_freeze or (remaining <= self.freeze_before_end if self.is_running else False)

        return {
            "status": status,
            "current_tick": self.current_tick,
            "tick_interval": self.tick_interval,
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "is_frozen": is_frozen,
            "game_start_time": self.game_start_time.isoformat() if self.game_start_time else None,
        }


# Global tick engine instance
tick_engine = TickEngine()
