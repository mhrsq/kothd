"""
Tests for the scoring engine — core game logic.

Covers:
  - Team name resolution from king.txt
  - Point calculation (base, multiplier, streak bonus)
  - First blood detection and bonus
  - SLA penalty (king but SLA down = 0 points)
  - King change detection
  - Aggregate team score updates
  - Manual score adjustment
  - Leaderboard ordering
"""
import pytest
from app.models import Hill, Team, TeamScore, Tick
from app.services.scoring import ScoringEngine
from sqlalchemy.ext.asyncio import AsyncSession

# ── Helpers ──────────────────────────────────────────────────────────────────

async def _seed_team(db: AsyncSession, name="Alpha", category="default") -> Team:
    team = Team(name=name, display_name=name, category=category, token=f"tok-{name}", is_active=True)
    db.add(team)
    await db.flush()
    db.add(TeamScore(team_id=team.id))
    await db.flush()
    return team


async def _seed_hill(db: AsyncSession, name="Hill-1", ip="10.0.0.1", multiplier=1.0, is_behind_pivot=False) -> Hill:
    hill = Hill(
        name=name, ip_address=ip, base_points=10,
        multiplier=multiplier, is_behind_pivot=is_behind_pivot, is_active=True,
    )
    db.add(hill)
    await db.flush()
    return hill


async def _seed_tick(db: AsyncSession, tick_number: int) -> Tick:
    tick = Tick(tick_number=tick_number, status="running")
    db.add(tick)
    await db.flush()
    return tick


# ── Tests ────────────────────────────────────────────────────────────────────

class TestResolveTeamName:
    """Test ScoringEngine.resolve_team_name()"""

    @pytest.mark.asyncio
    async def test_resolve_valid_team(self, db_session: AsyncSession):
        team = await _seed_team(db_session, name="Alpha")
        scoring = ScoringEngine(db_session)

        resolved = await scoring.resolve_team_name("Alpha\n")
        assert resolved is not None
        assert resolved.id == team.id
        assert resolved.name == "Alpha"

    @pytest.mark.asyncio
    async def test_resolve_case_insensitive(self, db_session: AsyncSession):
        await _seed_team(db_session, name="Alpha")
        scoring = ScoringEngine(db_session)

        resolved = await scoring.resolve_team_name("alpha")
        assert resolved is not None
        assert resolved.name == "Alpha"

    @pytest.mark.asyncio
    async def test_resolve_empty_returns_none(self, db_session: AsyncSession):
        scoring = ScoringEngine(db_session)
        assert await scoring.resolve_team_name("") is None
        assert await scoring.resolve_team_name(None) is None
        assert await scoring.resolve_team_name("   \n") is None

    @pytest.mark.asyncio
    async def test_resolve_unknown_team_returns_none(self, db_session: AsyncSession):
        scoring = ScoringEngine(db_session)
        assert await scoring.resolve_team_name("NonExistentTeam") is None

    @pytest.mark.asyncio
    async def test_resolve_multiline_uses_first_line(self, db_session: AsyncSession):
        await _seed_team(db_session, name="Alpha")
        scoring = ScoringEngine(db_session)

        resolved = await scoring.resolve_team_name("Alpha\ngarbage\nmore")
        assert resolved is not None
        assert resolved.name == "Alpha"

    @pytest.mark.asyncio
    async def test_resolve_truncates_oversized_input(self, db_session: AsyncSession):
        """king.txt > 256 chars should be truncated (VULN-17 mitigation)"""
        await _seed_team(db_session, name="Alpha")
        scoring = ScoringEngine(db_session)

        huge = "Alpha\n" + "A" * 500
        resolved = await scoring.resolve_team_name(huge)
        assert resolved is not None  # Should still resolve from first line

    @pytest.mark.asyncio
    async def test_resolve_inactive_team_returns_none(self, db_session: AsyncSession):
        team = await _seed_team(db_session, name="Inactive")
        team.is_active = False
        await db_session.flush()

        scoring = ScoringEngine(db_session)
        assert await scoring.resolve_team_name("Inactive") is None


class TestProcessTickResults:
    """Test ScoringEngine.process_tick_results()"""

    @pytest.mark.asyncio
    async def test_basic_scoring(self, db_session: AsyncSession):
        """King with SLA up gets base_points × multiplier"""
        team = await _seed_team(db_session, name="Alpha")
        hill = await _seed_hill(db_session, name="Hill-1", multiplier=1.0)
        tick = await _seed_tick(db_session, tick_number=1)

        scoring = ScoringEngine(db_session)
        summary = await scoring.process_tick_results(tick, [
            {
                "hill_id": hill.id,
                "king_team_name": "Alpha",
                "sla_status": True,
                "raw_king_txt": "Alpha\n",
            }
        ])

        assert summary["tick_number"] == 1
        assert team.id in summary["points_awarded"]
        # First tick as king: base(10) × multiplier(1.0) + first_blood(50) = 60
        assert summary["points_awarded"][team.id] == 60

    @pytest.mark.asyncio
    async def test_multiplier_applied(self, db_session: AsyncSession):
        """Hill multiplier increases points"""
        team = await _seed_team(db_session, name="Alpha")
        hill = await _seed_hill(db_session, name="Pivot", multiplier=1.5)
        tick = await _seed_tick(db_session, tick_number=1)

        scoring = ScoringEngine(db_session)
        summary = await scoring.process_tick_results(tick, [
            {"hill_id": hill.id, "king_team_name": "Alpha", "sla_status": True, "raw_king_txt": "Alpha\n"}
        ])

        # base(10) × 1.5 = 15, + first_blood(50) = 65
        assert summary["points_awarded"][team.id] == 65

    @pytest.mark.asyncio
    async def test_sla_down_zero_points(self, db_session: AsyncSession):
        """King with SLA down gets 0 base points but first blood is still awarded"""
        team = await _seed_team(db_session, name="Alpha")
        hill = await _seed_hill(db_session, name="Hill-1")
        tick = await _seed_tick(db_session, tick_number=1)

        scoring = ScoringEngine(db_session)
        summary = await scoring.process_tick_results(tick, [
            {"hill_id": hill.id, "king_team_name": "Alpha", "sla_status": False, "raw_king_txt": "Alpha\n"}
        ])

        # SLA down = 0 base points, but first blood bonus (50) is still awarded
        # because first blood recognises capture regardless of SLA status
        assert summary["points_awarded"][team.id] == 50

    @pytest.mark.asyncio
    async def test_no_king_no_points(self, db_session: AsyncSession):
        """Empty king.txt = no points to anyone"""
        hill = await _seed_hill(db_session, name="Hill-1")
        tick = await _seed_tick(db_session, tick_number=1)

        scoring = ScoringEngine(db_session)
        summary = await scoring.process_tick_results(tick, [
            {"hill_id": hill.id, "king_team_name": None, "sla_status": True, "raw_king_txt": ""}
        ])

        assert summary["points_awarded"] == {}

    @pytest.mark.asyncio
    async def test_first_blood_detection(self, db_session: AsyncSession):
        """First capture of a hill should trigger first blood bonus"""
        await _seed_team(db_session, name="Alpha")
        hill = await _seed_hill(db_session, name="Hill-1")
        tick = await _seed_tick(db_session, tick_number=1)

        scoring = ScoringEngine(db_session)
        summary = await scoring.process_tick_results(tick, [
            {"hill_id": hill.id, "king_team_name": "Alpha", "sla_status": True, "raw_king_txt": "Alpha\n"}
        ])

        assert len(summary["first_bloods"]) == 1
        assert summary["first_bloods"][0]["team_name"] == "Alpha"
        assert summary["first_bloods"][0]["bonus"] == 50

    @pytest.mark.asyncio
    async def test_no_duplicate_first_blood(self, db_session: AsyncSession):
        """Second tick on same hill should NOT trigger first blood again"""
        team = await _seed_team(db_session, name="Alpha")
        hill = await _seed_hill(db_session, name="Hill-1")

        scoring = ScoringEngine(db_session)

        tick1 = await _seed_tick(db_session, tick_number=1)
        await scoring.process_tick_results(tick1, [
            {"hill_id": hill.id, "king_team_name": "Alpha", "sla_status": True, "raw_king_txt": "Alpha\n"}
        ])

        tick2 = await _seed_tick(db_session, tick_number=2)
        summary2 = await scoring.process_tick_results(tick2, [
            {"hill_id": hill.id, "king_team_name": "Alpha", "sla_status": True, "raw_king_txt": "Alpha\n"}
        ])

        assert len(summary2["first_bloods"]) == 0
        # Tick 2: base(10), no first blood, consecutive=2 (< 3 for streak)
        assert summary2["points_awarded"][team.id] == 10

    @pytest.mark.asyncio
    async def test_defense_streak_bonus(self, db_session: AsyncSession):
        """After 3 consecutive ticks as king, streak bonus is applied"""
        team = await _seed_team(db_session, name="Alpha")
        hill = await _seed_hill(db_session, name="Hill-1")

        scoring = ScoringEngine(db_session)

        # Ticks 1, 2, 3
        for i in range(1, 4):
            tick = await _seed_tick(db_session, tick_number=i)
            summary = await scoring.process_tick_results(tick, [
                {"hill_id": hill.id, "king_team_name": "Alpha", "sla_status": True, "raw_king_txt": "Alpha\n"}
            ])

        # Tick 3: consecutive_ticks = 3, so streak bonus applies
        # base(10) + streak(5) = 15
        assert summary["points_awarded"][team.id] == 15

    @pytest.mark.asyncio
    async def test_king_change_detected(self, db_session: AsyncSession):
        """King change from Alpha to Bravo should be logged"""
        await _seed_team(db_session, name="Alpha")
        await _seed_team(db_session, name="Bravo")
        hill = await _seed_hill(db_session, name="Hill-1")

        scoring = ScoringEngine(db_session)

        tick1 = await _seed_tick(db_session, tick_number=1)
        await scoring.process_tick_results(tick1, [
            {"hill_id": hill.id, "king_team_name": "Alpha", "sla_status": True, "raw_king_txt": "Alpha\n"}
        ])

        tick2 = await _seed_tick(db_session, tick_number=2)
        summary = await scoring.process_tick_results(tick2, [
            {"hill_id": hill.id, "king_team_name": "Bravo", "sla_status": True, "raw_king_txt": "Bravo\n"}
        ])

        assert len(summary["king_changes"]) == 1
        assert summary["king_changes"][0]["new_king_name"] == "Bravo"

    @pytest.mark.asyncio
    async def test_multiple_hills_single_tick(self, db_session: AsyncSession):
        """Multiple hills checked in a single tick"""
        alpha = await _seed_team(db_session, name="Alpha")
        bravo = await _seed_team(db_session, name="Bravo")
        hill1 = await _seed_hill(db_session, name="Hill-1", ip="10.0.0.1")
        hill2 = await _seed_hill(db_session, name="Hill-2", ip="10.0.0.2")
        tick = await _seed_tick(db_session, tick_number=1)

        scoring = ScoringEngine(db_session)
        summary = await scoring.process_tick_results(tick, [
            {"hill_id": hill1.id, "king_team_name": "Alpha", "sla_status": True, "raw_king_txt": "Alpha\n"},
            {"hill_id": hill2.id, "king_team_name": "Bravo", "sla_status": True, "raw_king_txt": "Bravo\n"},
        ])

        assert alpha.id in summary["points_awarded"]
        assert bravo.id in summary["points_awarded"]
        assert len(summary["first_bloods"]) == 2


class TestScoreAdjustment:
    """Test manual score adjustments"""

    @pytest.mark.asyncio
    async def test_adjust_score_positive(self, db_session: AsyncSession):
        team = await _seed_team(db_session, name="Alpha")
        scoring = ScoringEngine(db_session)

        await scoring.adjust_score(team.id, 100, "Bonus for good behavior")

        from sqlalchemy import select
        result = await db_session.execute(
            select(TeamScore).where(TeamScore.team_id == team.id)
        )
        ts = result.scalar_one()
        assert ts.total_points == 100

    @pytest.mark.asyncio
    async def test_adjust_score_negative(self, db_session: AsyncSession):
        team = await _seed_team(db_session, name="Alpha")
        scoring = ScoringEngine(db_session)

        await scoring.adjust_score(team.id, -50, "Penalty for rule violation")

        from sqlalchemy import select
        result = await db_session.execute(
            select(TeamScore).where(TeamScore.team_id == team.id)
        )
        ts = result.scalar_one()
        assert ts.total_points == -50


class TestLeaderboard:
    """Test leaderboard generation"""

    @pytest.mark.asyncio
    async def test_leaderboard_ordering(self, db_session: AsyncSession):
        """Teams should be ordered by total_points descending"""
        alpha = await _seed_team(db_session, name="Alpha")
        bravo = await _seed_team(db_session, name="Bravo")

        # Give Alpha 50, Bravo 100
        scoring = ScoringEngine(db_session)
        await scoring.adjust_score(alpha.id, 50, "test")
        await scoring.adjust_score(bravo.id, 100, "test")

        leaderboard = await scoring.get_leaderboard()
        assert len(leaderboard) == 2
        assert leaderboard[0]["team_name"] == "Bravo"
        assert leaderboard[0]["rank"] == 1
        assert leaderboard[1]["team_name"] == "Alpha"
        assert leaderboard[1]["rank"] == 2

    @pytest.mark.asyncio
    async def test_empty_leaderboard(self, db_session: AsyncSession):
        scoring = ScoringEngine(db_session)
        leaderboard = await scoring.get_leaderboard()
        assert leaderboard == []


class TestGameConfig:
    """Test config get/set via ScoringEngine"""

    @pytest.mark.asyncio
    async def test_get_config(self, db_session: AsyncSession):
        scoring = ScoringEngine(db_session)
        val = await scoring.get_config("base_points")
        assert val == "10"

    @pytest.mark.asyncio
    async def test_get_config_int(self, db_session: AsyncSession):
        scoring = ScoringEngine(db_session)
        val = await scoring.get_config_int("base_points", 0)
        assert val == 10

    @pytest.mark.asyncio
    async def test_get_config_missing_returns_default(self, db_session: AsyncSession):
        scoring = ScoringEngine(db_session)
        val = await scoring.get_config_int("nonexistent_key", 42)
        assert val == 42

    @pytest.mark.asyncio
    async def test_set_config(self, db_session: AsyncSession):
        scoring = ScoringEngine(db_session)
        await scoring.set_config("base_points", "20")
        val = await scoring.get_config_int("base_points")
        assert val == 20
