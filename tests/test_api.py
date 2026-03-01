"""
API integration tests — test HTTP endpoints via HTTPX async client.

Covers:
  - Health endpoint
  - Team CRUD (admin)
  - Team registration (self-service)
  - Auth (team login, admin login, /me)
  - Hill CRUD (admin)
  - Scoreboard read
  - Admin game control
  - Announcements
"""
import pytest
from httpx import AsyncClient

# ── Health ───────────────────────────────────────────────────────────────────

class TestHealth:

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        # In test env the real DB pool is unreachable, so status is "degraded"
        assert data["status"] in ("ok", "degraded")
        assert "version" in data


# ── Registration ─────────────────────────────────────────────────────────────

class TestRegistration:

    @pytest.mark.asyncio
    async def test_registration_status(self, client: AsyncClient):
        resp = await client.get("/api/register/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "registration_enabled" in data

    @pytest.mark.asyncio
    async def test_register_team(self, client: AsyncClient, registration_payload: dict):
        resp = await client.post("/api/register", json=registration_payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "TestTeam"
        assert data["display_name"] == "Test Team"
        assert "token" in data
        assert len(data["token"]) == 64

    @pytest.mark.asyncio
    async def test_register_duplicate_name(self, client: AsyncClient, registration_payload: dict):
        await client.post("/api/register", json=registration_payload)
        resp = await client.post("/api/register", json=registration_payload)
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_register_wrong_code(self, client: AsyncClient):
        resp = await client.post("/api/register", json={
            "name": "Hacker",
            "display_name": "Hacker Team",
            "category": "default",
            "registration_code": "WRONGCODE",
        })
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_register_invalid_name(self, client: AsyncClient):
        resp = await client.post("/api/register", json={
            "name": "invalid name!@#",
            "display_name": "Bad Name",
            "category": "default",
            "registration_code": "TESTCODE",
        })
        assert resp.status_code == 422  # Validation error


# ── Auth ─────────────────────────────────────────────────────────────────────

class TestAuth:

    @pytest.mark.asyncio
    async def test_admin_login(self, client: AsyncClient):
        resp = await client.post("/api/auth/admin", json={
            "admin_token": "test-admin-token",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "admin"

    @pytest.mark.asyncio
    async def test_admin_login_wrong_token(self, client: AsyncClient):
        resp = await client.post("/api/auth/admin", json={
            "admin_token": "wrong-token",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_team_login(self, client: AsyncClient, registration_payload: dict):
        # First register
        reg = await client.post("/api/register", json=registration_payload)
        token = reg.json()["token"]

        resp = await client.post("/api/auth/team", json={"token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "team"
        assert data["team_name"] == "TestTeam"

    @pytest.mark.asyncio
    async def test_team_login_invalid_token(self, client: AsyncClient):
        resp = await client.post("/api/auth/team", json={"token": "fake-token"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_admin(self, client: AsyncClient, admin_headers: dict):
        resp = await client.get("/api/auth/me", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    @pytest.mark.asyncio
    async def test_me_team(self, client: AsyncClient, registration_payload: dict):
        reg = await client.post("/api/register", json=registration_payload)
        token = reg.json()["token"]

        resp = await client.get("/api/auth/me", headers={"X-Team-Token": token})
        assert resp.status_code == 200
        assert resp.json()["role"] == "team"


# ── Teams (Admin) ────────────────────────────────────────────────────────────

class TestTeamsAdmin:

    @pytest.mark.asyncio
    async def test_list_teams_empty(self, client: AsyncClient):
        resp = await client.get("/api/teams")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_team_admin(self, client: AsyncClient, admin_headers: dict):
        resp = await client.post("/api/teams", json={
            "name": "AdminTeam",
            "category": "default",
        }, headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "AdminTeam"

    @pytest.mark.asyncio
    async def test_create_team_unauthorized(self, client: AsyncClient):
        resp = await client.post("/api/teams", json={
            "name": "UnauthorizedTeam",
        }, headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_team_by_id(self, client: AsyncClient, admin_headers: dict):
        create = await client.post("/api/teams", json={
            "name": "FindMe",
            "category": "default",
        }, headers=admin_headers)
        team_id = create.json()["id"]

        resp = await client.get(f"/api/teams/{team_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "FindMe"

    @pytest.mark.asyncio
    async def test_get_team_not_found(self, client: AsyncClient):
        resp = await client.get("/api/teams/9999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_teams_bulk(self, client: AsyncClient, admin_headers: dict):
        resp = await client.post("/api/teams/bulk", json=[
            {"name": "BulkA", "category": "red"},
            {"name": "BulkB", "category": "blue"},
        ], headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 2


# ── Hills ────────────────────────────────────────────────────────────────────

class TestHills:

    @pytest.mark.asyncio
    async def test_list_hills_empty(self, client: AsyncClient):
        resp = await client.get("/api/hills")
        assert resp.status_code == 200
        assert resp.json() == []


# ── Scoreboard ───────────────────────────────────────────────────────────────

class TestScoreboard:

    @pytest.mark.asyncio
    async def test_get_scoreboard(self, client: AsyncClient):
        resp = await client.get("/api/scoreboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "game_status" in data
        assert "teams" in data
        assert "hills" in data

    @pytest.mark.asyncio
    async def test_get_leaderboard(self, client: AsyncClient):
        resp = await client.get("/api/scoreboard/leaderboard")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_first_bloods(self, client: AsyncClient):
        resp = await client.get("/api/scoreboard/first-bloods")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── Admin ────────────────────────────────────────────────────────────────────

class TestAdmin:

    @pytest.mark.asyncio
    async def test_get_game_status(self, client: AsyncClient, admin_headers: dict):
        resp = await client.get("/api/admin/game/status", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_started"

    @pytest.mark.asyncio
    async def test_get_game_status_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/admin/game/status", headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_config(self, client: AsyncClient, admin_headers: dict):
        resp = await client.get("/api/admin/config", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Should have a list of config entries
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_audit_log(self, client: AsyncClient, admin_headers: dict):
        resp = await client.get("/api/admin/audit", headers=admin_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_admin_stats(self, client: AsyncClient, admin_headers: dict):
        resp = await client.get("/api/admin/stats", headers=admin_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_broadcast_announcement(self, client: AsyncClient, admin_headers: dict):
        resp = await client.post("/api/admin/announcement", json={
            "message": "Test announcement",
            "type": "info",
        }, headers=admin_headers)
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_list_announcements(self, client: AsyncClient, admin_headers: dict):
        # Create one first
        await client.post("/api/admin/announcement", json={
            "message": "Hello world",
            "type": "info",
        }, headers=admin_headers)

        resp = await client.get("/api/admin/announcements", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_registration_status_admin(self, client: AsyncClient, admin_headers: dict):
        resp = await client.get("/api/admin/registration/status", headers=admin_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_score_adjust(self, client: AsyncClient, admin_headers: dict):
        # Create a team first
        team_resp = await client.post("/api/teams", json={
            "name": "AdjustMe",
            "category": "default",
        }, headers=admin_headers)
        team_id = team_resp.json()["id"]

        resp = await client.post("/api/admin/score/adjust", json={
            "team_id": team_id,
            "points": 100,
            "reason": "Test bonus",
        }, headers=admin_headers)
        assert resp.status_code == 200
