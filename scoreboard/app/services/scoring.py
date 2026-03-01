"""
KoTH CTF Platform — Scoring Engine
Core scoring logic for King of the Hill
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict
from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import (
    Team, Hill, Tick, TickResult, Score, TeamScore, FirstBlood, GameConfig, AuditLog
)

logger = logging.getLogger("koth.scoring")


class ScoringEngine:
    """Handles all score calculations and updates"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_config(self, key: str) -> Optional[str]:
        result = await self.db.execute(
            select(GameConfig.value).where(GameConfig.key == key)
        )
        row = result.scalar_one_or_none()
        return row

    async def get_config_int(self, key: str, default: int = 0) -> int:
        val = await self.get_config(key)
        return int(val) if val else default

    async def set_config(self, key: str, value: str):
        await self.db.execute(
            update(GameConfig)
            .where(GameConfig.key == key)
            .values(value=value, updated_at=datetime.utcnow())
        )
        await self.db.flush()

    async def resolve_team_name(self, king_txt: Optional[str]) -> Optional[Team]:
        """Resolve king.txt content to a registered team"""
        if not king_txt or not king_txt.strip():
            return None

        # VULN-17: Truncate oversized king.txt to prevent abuse (max 256 chars)
        if len(king_txt) > 256:
            logger.warning(f"king.txt too large ({len(king_txt)} chars), truncating to 256")
            king_txt = king_txt[:256]

        team_name = king_txt.strip().split('\n')[0].strip()
        if not team_name or len(team_name) > 64:
            return None

        result = await self.db.execute(
            select(Team).where(
                and_(
                    func.lower(Team.name) == func.lower(team_name),
                    Team.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()

    async def process_tick_results(
        self,
        tick: Tick,
        check_results: List[Dict]
    ) -> Dict:
        """
        Process all hill check results for a tick and calculate scores.
        
        check_results format:
        [
            {
                "hill_id": 1,
                "king_team_name": "TeamAlpha",
                "sla_status": true,
                "raw_king_txt": "TeamAlpha\n",
                "check_duration_ms": 234,
                "error_message": null
            },
            ...
        ]

        Returns summary dict.
        """
        tick_summary = {
            "tick_number": tick.tick_number,
            "results": [],
            "king_changes": [],
            "first_bloods": [],
            "points_awarded": {}
        }

        base_points = await self.get_config_int("base_points", 10)
        first_blood_bonus = await self.get_config_int("first_blood_bonus", 50)
        streak_bonus = await self.get_config_int("defense_streak_bonus", 5)

        for check in check_results:
            hill_id = check["hill_id"]

            # Get hill info
            hill_result = await self.db.execute(
                select(Hill).where(Hill.id == hill_id)
            )
            hill = hill_result.scalar_one_or_none()
            if not hill:
                logger.warning(f"Hill {hill_id} not found, skipping")
                continue

            # Resolve king team
            king_team = await self.resolve_team_name(check.get("king_team_name"))
            sla_status = check.get("sla_status", False)

            # Calculate points
            points = 0
            if king_team and sla_status:
                # Base points × hill multiplier
                points = int(base_points * hill.multiplier)

                # Check defense streak
                prev_score = await self.db.execute(
                    select(Score).where(
                        and_(
                            Score.team_id == king_team.id,
                            Score.hill_id == hill_id
                        )
                    )
                )
                prev = prev_score.scalar_one_or_none()
                consecutive = (prev.consecutive_ticks + 1) if prev and prev.current_king else 1

                # Streak bonus (after 3 consecutive ticks)
                if consecutive >= 3:
                    points += streak_bonus

            elif king_team and not sla_status:
                # King but SLA down = 0 points (penalty)
                points = 0
                logger.info(
                    f"Hill {hill.name}: Team {king_team.name} is king but SLA DOWN - 0 points"
                )

            # Create tick result record (with dual-verification metadata)
            tick_result = TickResult(
                tick_id=tick.id,
                hill_id=hill_id,
                king_team_id=king_team.id if king_team else None,
                sla_status=sla_status,
                points_awarded=points,
                raw_king_txt=check.get("raw_king_txt"),
                check_duration_ms=check.get("check_duration_ms"),
                error_message=check.get("error_message"),
                # Dual-verification fields
                ssh_verified=check.get("ssh_verified", False),
                agent_verified=check.get("agent_verified", False),
                ssh_king_name=check.get("ssh_king_name"),
                agent_king_name=check.get("agent_king_name"),
                verification_count=check.get("verification_count", 0),
            )
            self.db.add(tick_result)

            # Check for first blood
            if king_team:
                fb_result = await self.db.execute(
                    select(FirstBlood).where(FirstBlood.hill_id == hill_id)
                )
                existing_fb = fb_result.scalar_one_or_none()

                if not existing_fb:
                    fb = FirstBlood(
                        hill_id=hill_id,
                        team_id=king_team.id,
                        tick_number=tick.tick_number,
                        bonus_points=first_blood_bonus,
                    )
                    self.db.add(fb)
                    points += first_blood_bonus
                    tick_summary["first_bloods"].append({
                        "hill_id": hill_id,
                        "hill_name": hill.name,
                        "team_id": king_team.id,
                        "team_name": king_team.name,
                        "bonus": first_blood_bonus,
                    })
                    logger.info(
                        f"FIRST BLOOD! {king_team.name} captured {hill.name} "
                        f"(+{first_blood_bonus} bonus)"
                    )

            # Update per-hill score for king team
            if king_team:
                await self._update_hill_score(
                    king_team.id, hill_id, points, tick.tick_number
                )

                if king_team.id not in tick_summary["points_awarded"]:
                    tick_summary["points_awarded"][king_team.id] = 0
                tick_summary["points_awarded"][king_team.id] += points

            # Check for king change
            await self._check_king_change(
                hill_id, king_team, tick, tick_summary
            )

            tick_summary["results"].append({
                "hill_id": hill_id,
                "hill_name": hill.name,
                "king_team": king_team.name if king_team else None,
                "king_team_id": king_team.id if king_team else None,
                "sla_status": sla_status,
                "points": points,
                # Dual-verification info
                "ssh_verified": check.get("ssh_verified", False),
                "agent_verified": check.get("agent_verified", False),
                "ssh_king_name": check.get("ssh_king_name"),
                "agent_king_name": check.get("agent_king_name"),
                "verification_count": check.get("verification_count", 0),
            })

        # Update aggregate team scores
        await self._update_team_scores()

        # Mark tick as completed
        tick.completed_at = datetime.utcnow()
        tick.status = "completed"
        tick.details = tick_summary
        await self.db.flush()

        # Update current tick in config
        await self.set_config("current_tick", str(tick.tick_number))

        await self.db.commit()

        logger.info(
            f"Tick #{tick.tick_number} completed. "
            f"Points awarded: {tick_summary['points_awarded']}"
        )

        return tick_summary

    async def _update_hill_score(
        self, team_id: int, hill_id: int, points: int, tick_number: int
    ):
        """Update or create score record for team on specific hill"""
        result = await self.db.execute(
            select(Score).where(
                and_(Score.team_id == team_id, Score.hill_id == hill_id)
            )
        )
        score = result.scalar_one_or_none()

        if score:
            score.total_points += points
            score.ticks_as_king += 1
            score.current_king = True
            score.consecutive_ticks += 1
            score.last_updated = datetime.utcnow()
        else:
            score = Score(
                team_id=team_id,
                hill_id=hill_id,
                total_points=points,
                ticks_as_king=1,
                current_king=True,
                consecutive_ticks=1,
            )
            self.db.add(score)

        # Reset consecutive for all OTHER teams on this hill
        await self.db.execute(
            update(Score)
            .where(and_(Score.hill_id == hill_id, Score.team_id != team_id))
            .values(current_king=False, consecutive_ticks=0)
        )
        await self.db.flush()

    async def _check_king_change(
        self, hill_id: int, new_king: Optional[Team],
        tick: Tick, summary: Dict
    ):
        """Detect king changes and log them"""
        # Get previous tick's king for this hill
        prev_tick_result = await self.db.execute(
            select(TickResult)
            .where(
                and_(
                    TickResult.hill_id == hill_id,
                    TickResult.tick_id != tick.id,
                )
            )
            .order_by(TickResult.checked_at.desc())
            .limit(1)
        )
        prev = prev_tick_result.scalar_one_or_none()

        prev_king_id = prev.king_team_id if prev else None
        new_king_id = new_king.id if new_king else None

        if prev_king_id != new_king_id:
            # Get hill name
            hill_result = await self.db.execute(
                select(Hill.name).where(Hill.id == hill_id)
            )
            hill_name = hill_result.scalar_one_or_none()

            change = {
                "hill_id": hill_id,
                "hill_name": hill_name,
                "old_king_id": prev_king_id,
                "new_king_id": new_king_id,
                "new_king_name": new_king.name if new_king else None,
                "tick": tick.tick_number,
            }
            summary["king_changes"].append(change)

            # Audit log
            self.db.add(AuditLog(
                event_type="king_change",
                details=change,
            ))

    async def _update_team_scores(self):
        """Recalculate aggregate team scores"""
        # Get all teams
        teams_result = await self.db.execute(
            select(Team).where(Team.is_active == True)
        )
        teams = teams_result.scalars().all()

        for team in teams:
            # Sum points across all hills
            points_result = await self.db.execute(
                select(func.coalesce(func.sum(Score.total_points), 0))
                .where(Score.team_id == team.id)
            )
            total_points = points_result.scalar()

            # Count hills currently owned
            hills_result = await self.db.execute(
                select(func.count())
                .where(and_(Score.team_id == team.id, Score.current_king == True))
            )
            hills_owned = hills_result.scalar()

            # Total ticks as king
            ticks_result = await self.db.execute(
                select(func.coalesce(func.sum(Score.ticks_as_king), 0))
                .where(Score.team_id == team.id)
            )
            total_ticks = ticks_result.scalar()

            # First bloods
            fb_result = await self.db.execute(
                select(func.count())
                .where(FirstBlood.team_id == team.id)
            )
            first_bloods = fb_result.scalar()

            # NOTE: First blood bonus is already included in Score.total_points
            # (added during process_tick_results), so we do NOT add it again here.

            # Upsert team score
            existing = await self.db.execute(
                select(TeamScore).where(TeamScore.team_id == team.id)
            )
            ts = existing.scalar_one_or_none()

            if ts:
                ts.total_points = total_points
                ts.hills_owned = hills_owned
                ts.total_ticks_as_king = total_ticks
                ts.first_bloods = first_bloods
                ts.last_updated = datetime.utcnow()
            else:
                self.db.add(TeamScore(
                    team_id=team.id,
                    total_points=total_points,
                    hills_owned=hills_owned,
                    total_ticks_as_king=total_ticks,
                    first_bloods=first_bloods,
                ))

        await self.db.flush()

    async def get_leaderboard(self) -> List[Dict]:
        """Get current leaderboard sorted by total points"""
        result = await self.db.execute(
            select(TeamScore, Team)
            .join(Team, TeamScore.team_id == Team.id)
            .where(Team.is_active == True)
            .order_by(TeamScore.total_points.desc())
        )
        rows = result.all()

        leaderboard = []
        for rank, (ts, team) in enumerate(rows, 1):
            leaderboard.append({
                "rank": rank,
                "team_id": team.id,
                "team_name": team.name,
                "display_name": team.display_name or team.name,
                "category": team.category,
                "total_points": ts.total_points,
                "hills_owned": ts.hills_owned,
                "total_ticks_as_king": ts.total_ticks_as_king,
                "first_bloods": ts.first_bloods,
            })

        return leaderboard

    async def adjust_score(self, team_id: int, points: int, reason: str, actor: str = "admin"):
        """Manual score adjustment by admin"""
        ts_result = await self.db.execute(
            select(TeamScore).where(TeamScore.team_id == team_id)
        )
        ts = ts_result.scalar_one_or_none()

        if ts:
            ts.total_points += points
            ts.last_updated = datetime.utcnow()
        else:
            self.db.add(TeamScore(
                team_id=team_id,
                total_points=points,
            ))

        # Audit log
        self.db.add(AuditLog(
            event_type="score_adjust",
            actor=actor,
            details={
                "team_id": team_id,
                "points": points,
                "reason": reason,
            }
        ))
        await self.db.commit()
