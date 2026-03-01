"""
Tests for Pydantic schema validation.

Covers:
  - TeamCreate validation (name pattern, length)
  - TeamRegisterRequest validation
  - HillCreate defaults and constraints
  - GameControlRequest action validation
  - ScoreAdjustRequest
  - AgentReportRequest
"""
import pytest
from app.schemas import (
    AgentReportRequest,
    GameControlRequest,
    HillCreate,
    HillUpdate,
    ScoreAdjustRequest,
    TeamCreate,
    TeamRegisterRequest,
    WSMessage,
)
from pydantic import ValidationError


class TestTeamCreate:

    def test_valid_team(self):
        t = TeamCreate(name="Alpha-1", category="default")
        assert t.name == "Alpha-1"
        assert t.category == "default"

    def test_name_alphanumeric_underscore_dash(self):
        TeamCreate(name="team_1-test")  # should not raise

    def test_name_rejects_spaces(self):
        with pytest.raises(ValidationError):
            TeamCreate(name="team with spaces")

    def test_name_rejects_special_chars(self):
        with pytest.raises(ValidationError):
            TeamCreate(name="team!@#$")

    def test_name_max_length(self):
        with pytest.raises(ValidationError):
            TeamCreate(name="a" * 65)  # max 64

    def test_name_min_required(self):
        with pytest.raises(ValidationError):
            TeamCreate(name="")

    def test_category_max_length(self):
        with pytest.raises(ValidationError):
            TeamCreate(name="ok", category="x" * 33)  # max 32


class TestTeamRegisterRequest:

    def test_valid_registration(self):
        r = TeamRegisterRequest(
            name="Alpha",
            display_name="Team Alpha",
            registration_code="CODE123",
        )
        assert r.name == "Alpha"
        assert r.category == "default"

    def test_name_min_length(self):
        with pytest.raises(ValidationError):
            TeamRegisterRequest(name="A", display_name="Aa", registration_code="X")

    def test_display_name_allowed_chars(self):
        # Parentheses, dots, spaces are allowed
        r = TeamRegisterRequest(
            name="Alpha",
            display_name="Team Alpha (v2.0)",
            registration_code="CODE",
        )
        assert r.display_name == "Team Alpha (v2.0)"

    def test_display_name_rejects_html(self):
        with pytest.raises(ValidationError):
            TeamRegisterRequest(
                name="Alpha",
                display_name="<script>alert(1)</script>",
                registration_code="CODE",
            )


class TestHillCreate:

    def test_defaults(self):
        h = HillCreate(name="Hill-1", ip_address="10.0.0.1")
        assert h.ssh_port == 22
        assert h.base_points == 10
        assert h.multiplier == 1.0
        assert h.king_file_path == "/root/king.txt"
        assert h.is_behind_pivot is False

    def test_ssh_port_range(self):
        with pytest.raises(ValidationError):
            HillCreate(name="Hill-1", ip_address="10.0.0.1", ssh_port=0)
        with pytest.raises(ValidationError):
            HillCreate(name="Hill-1", ip_address="10.0.0.1", ssh_port=70000)

    def test_multiplier(self):
        h = HillCreate(name="Pivot", ip_address="10.0.0.1", multiplier=2.0)
        assert h.multiplier == 2.0

    def test_king_file_path_must_be_absolute(self):
        with pytest.raises(ValidationError):
            HillCreate(name="Hill", ip_address="10.0.0.1", king_file_path="relative/path.txt")


class TestHillUpdate:

    def test_all_optional(self):
        h = HillUpdate()
        assert h.name is None
        assert h.ip_address is None

    def test_partial_update(self):
        h = HillUpdate(name="New Name", multiplier=2.5)
        assert h.name == "New Name"
        assert h.multiplier == 2.5
        assert h.ip_address is None


class TestGameControlRequest:

    @pytest.mark.parametrize("action", ["start", "pause", "resume", "stop"])
    def test_valid_actions(self, action: str):
        r = GameControlRequest(action=action)
        assert r.action == action

    def test_invalid_action(self):
        with pytest.raises(ValidationError):
            GameControlRequest(action="restart")

    def test_empty_action(self):
        with pytest.raises(ValidationError):
            GameControlRequest(action="")


class TestScoreAdjustRequest:

    def test_valid(self):
        r = ScoreAdjustRequest(team_id=1, points=100, reason="Bonus")
        assert r.team_id == 1
        assert r.points == 100

    def test_negative_points(self):
        r = ScoreAdjustRequest(team_id=1, points=-50, reason="Penalty")
        assert r.points == -50


class TestAgentReportRequest:

    def test_valid(self):
        r = AgentReportRequest(
            hill_id=1,
            agent_token="tok123",
            king_name="Alpha",
            sla_status=True,
        )
        assert r.hill_id == 1
        assert r.king_name == "Alpha"

    def test_optional_fields(self):
        r = AgentReportRequest(hill_id=1, agent_token="tok")
        assert r.king_name is None
        assert r.raw_king_txt is None
        assert r.sla_status is True  # default


class TestWSMessage:

    def test_valid(self):
        m = WSMessage(type="tick_update", data={"tick": 1})
        assert m.type == "tick_update"
        assert m.timestamp is not None
