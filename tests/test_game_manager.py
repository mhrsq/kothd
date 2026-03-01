"""
Tests for the game manager — team registration and game lifecycle.

Covers:
  - Single team registration
  - Bulk team registration
  - Game status retrieval
  - Team listing
  - Hill listing
"""
import pytest
from app.models import Hill, TeamScore
from app.services.game_manager import GameManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── Helpers ──────────────────────────────────────────────────────────────────

async def _seed_hill(db: AsyncSession, name="Hill-1", ip="10.0.0.1") -> Hill:
    hill = Hill(name=name, ip_address=ip, is_active=True)
    db.add(hill)
    await db.flush()
    return hill


# ── Tests ────────────────────────────────────────────────────────────────────

class TestTeamRegistration:

    @pytest.mark.asyncio
    async def test_register_single_team(self, db_session: AsyncSession):
        gm = GameManager(db_session)
        team = await gm.register_team("Alpha", display_name="Team Alpha", category="default")

        assert team.id is not None
        assert team.name == "Alpha"
        assert team.display_name == "Team Alpha"
        assert team.token is not None
        assert len(team.token) == 64  # secrets.token_hex(32) → 64 hex chars

    @pytest.mark.asyncio
    async def test_register_team_creates_team_score(self, db_session: AsyncSession):
        gm = GameManager(db_session)
        team = await gm.register_team("Alpha")

        result = await db_session.execute(
            select(TeamScore).where(TeamScore.team_id == team.id)
        )
        ts = result.scalar_one_or_none()
        assert ts is not None
        assert ts.total_points == 0

    @pytest.mark.asyncio
    async def test_register_team_default_display_name(self, db_session: AsyncSession):
        gm = GameManager(db_session)
        team = await gm.register_team("Alpha")
        assert team.display_name == "Alpha"

    @pytest.mark.asyncio
    async def test_register_teams_bulk(self, db_session: AsyncSession):
        gm = GameManager(db_session)
        teams = await gm.register_teams_bulk([
            {"name": "Alpha", "display_name": "Team Alpha", "category": "red"},
            {"name": "Bravo", "display_name": "Team Bravo", "category": "blue"},
            {"name": "Charlie"},  # minimal fields
        ])

        assert len(teams) == 3
        assert teams[0].name == "Alpha"
        assert teams[0].category == "red"
        assert teams[1].name == "Bravo"
        assert teams[2].name == "Charlie"
        assert teams[2].category == "default"


class TestGameStatus:

    @pytest.mark.asyncio
    async def test_get_game_status_default(self, db_session: AsyncSession):
        gm = GameManager(db_session)
        status = await gm.get_game_status()
        assert status == "not_started"


class TestTeamListing:

    @pytest.mark.asyncio
    async def test_list_teams_empty(self, db_session: AsyncSession):
        gm = GameManager(db_session)
        teams = await gm.get_all_teams()
        assert teams == []

    @pytest.mark.asyncio
    async def test_list_teams_after_registration(self, db_session: AsyncSession):
        gm = GameManager(db_session)
        await gm.register_team("Alpha")
        await gm.register_team("Bravo")

        teams = await gm.get_all_teams()
        assert len(teams) == 2

    @pytest.mark.asyncio
    async def test_list_teams_excludes_inactive(self, db_session: AsyncSession):
        gm = GameManager(db_session)
        team = await gm.register_team("Inactive")
        team.is_active = False
        await db_session.flush()

        teams = await gm.get_all_teams()
        assert len(teams) == 0


class TestHillListing:

    @pytest.mark.asyncio
    async def test_list_hills_empty(self, db_session: AsyncSession):
        gm = GameManager(db_session)
        hills = await gm.get_all_hills()
        assert hills == []

    @pytest.mark.asyncio
    async def test_list_hills(self, db_session: AsyncSession):
        await _seed_hill(db_session, "Hill-1", "10.0.0.1")
        await _seed_hill(db_session, "Hill-2", "10.0.0.2")

        gm = GameManager(db_session)
        hills = await gm.get_all_hills()
        assert len(hills) == 2
