"""
KoTH CTF Platform — Game Manager
Manages game lifecycle and state
"""
import logging
from datetime import datetime
from typing import Dict, List
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import GameConfig, Team, Hill, TeamScore, Score, AuditLog

logger = logging.getLogger("koth.game_manager")


class GameManager:
    """Manages game state, team registration, and hill configuration"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_game_status(self) -> str:
        result = await self.db.execute(
            select(GameConfig.value).where(GameConfig.key == "game_status")
        )
        return result.scalar_one_or_none() or "not_started"

    async def register_team(self, name: str, display_name: str = None,
                            category: str = "default", vpn_ip: str = None) -> Team:
        """Register a new team"""
        import secrets
        token = secrets.token_hex(32)

        team = Team(
            name=name,
            display_name=display_name or name,
            category=category,
            vpn_ip=vpn_ip,
            token=token,
        )
        self.db.add(team)

        # Initialize team score
        await self.db.flush()
        self.db.add(TeamScore(team_id=team.id))

        self.db.add(AuditLog(
            event_type="team_registered",
            actor="admin",
            details={"team_name": name, "category": category},
        ))
        await self.db.commit()

        logger.info(f"Team registered: {name} ({category})")
        return team

    async def register_teams_bulk(self, teams: List[Dict]) -> List[Team]:
        """Register multiple teams at once"""
        registered = []
        for t in teams:
            team = await self.register_team(
                name=t["name"],
                display_name=t.get("display_name"),
                category=t.get("category", "default"),
                vpn_ip=t.get("vpn_ip"),
            )
            registered.append(team)
        return registered

    async def get_all_teams(self) -> List[Team]:
        result = await self.db.execute(
            select(Team).where(Team.is_active == True).order_by(Team.id)
        )
        return result.scalars().all()

    async def get_all_hills(self) -> List[Hill]:
        result = await self.db.execute(
            select(Hill).where(Hill.is_active == True).order_by(Hill.id)
        )
        return result.scalars().all()

    async def get_hill_status(self) -> List[Dict]:
        """Get current king status for all hills"""
        hills = await self.get_all_hills()
        statuses = []

        for hill in hills:
            # Get current king
            king_result = await self.db.execute(
                select(Score, Team)
                .join(Team, Score.team_id == Team.id)
                .where(Score.hill_id == hill.id, Score.current_king == True)
            )
            king_row = king_result.first()

            statuses.append({
                "hill_id": hill.id,
                "hill_name": hill.name,
                "current_king": king_row[1].name if king_row else None,
                "current_king_team_id": king_row[1].id if king_row else None,
                "sla_status": True,  # Will be updated by tick results
                "multiplier": hill.multiplier,
                "is_behind_pivot": hill.is_behind_pivot,
            })

        return statuses

    async def reset_game(self):
        """Reset all game data (for testing/restart)"""
        await self.db.execute(delete(Score))
        await self.db.execute(delete(TeamScore))
        # Reset team scores
        teams = await self.get_all_teams()
        for team in teams:
            self.db.add(TeamScore(team_id=team.id))

        # Reset game config
        from sqlalchemy import update
        await self.db.execute(
            update(GameConfig)
            .where(GameConfig.key == "game_status")
            .values(value="not_started")
        )
        await self.db.execute(
            update(GameConfig)
            .where(GameConfig.key == "current_tick")
            .values(value="0")
        )
        await self.db.execute(
            update(GameConfig)
            .where(GameConfig.key == "game_start_time")
            .values(value="")
        )

        self.db.add(AuditLog(
            event_type="game_reset",
            actor="admin",
            details={"message": "Game data has been reset"},
        ))
        await self.db.commit()
        logger.info("🔄 Game data reset complete")
