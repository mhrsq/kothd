"""
KoTH CTF Platform — Pydantic Schemas
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ---- Team Schemas ----
class TeamBase(BaseModel):
    name: str = Field(..., max_length=64)
    display_name: Optional[str] = None
    category: str = Field(default="default", max_length=32)

class TeamCreate(TeamBase):
    name: str = Field(..., max_length=64, pattern="^[a-zA-Z0-9_-]+$")
    vpn_ip: Optional[str] = None

class TeamResponse(TeamBase):
    id: int
    is_active: bool = True
    created_at: datetime

    class Config:
        from_attributes = True

class TeamScoreResponse(BaseModel):
    team_id: int
    team_name: str
    display_name: Optional[str] = None
    category: str
    total_points: int = 0
    hills_owned: int = 0
    total_ticks_as_king: int = 0
    first_bloods: int = 0
    rank: int = 0

    class Config:
        from_attributes = True


# ---- Hill Schemas ----
class HillBase(BaseModel):
    name: str
    description: Optional[str] = None
    ip_address: str
    sla_check_type: str = "http"
    base_points: int = 10
    multiplier: float = 1.0
    is_behind_pivot: bool = False

class HillCreate(HillBase):
    ssh_port: int = Field(22, ge=1, le=65535)
    ssh_user: Optional[str] = Field(None, max_length=64, description="Per-hill SSH user (overrides global)")
    ssh_pass: Optional[str] = Field(None, max_length=128, description="Per-hill SSH password (overrides global)")
    sla_check_url: Optional[str] = Field(None, max_length=256, pattern=r"^https?://[a-zA-Z0-9._:/-]+$")
    sla_check_port: Optional[int] = Field(None, ge=1, le=65535)
    king_file_path: str = Field("/root/king.txt", max_length=256, pattern=r"^/[a-zA-Z0-9._/-]+$")
    agent_token: Optional[str] = Field(None, max_length=128, description="Pre-set agent token for hill agent")

class HillUpdate(BaseModel):
    """All fields optional — only provided fields are updated"""
    name: Optional[str] = None
    description: Optional[str] = None
    ip_address: Optional[str] = None
    ssh_port: Optional[int] = Field(None, ge=1, le=65535)
    ssh_user: Optional[str] = Field(None, max_length=64)
    ssh_pass: Optional[str] = Field(None, max_length=128)
    sla_check_type: Optional[str] = None
    sla_check_url: Optional[str] = None
    sla_check_port: Optional[int] = Field(None, ge=1, le=65535)
    king_file_path: Optional[str] = None
    base_points: Optional[int] = None
    multiplier: Optional[float] = None
    is_behind_pivot: Optional[bool] = None
    is_active: Optional[bool] = None

class HillResponse(HillBase):
    id: int
    is_active: bool
    current_king: Optional[str] = None
    current_king_team_id: Optional[int] = None
    sla_status: Optional[bool] = None
    created_at: datetime

    class Config:
        from_attributes = True

class HillStatusResponse(BaseModel):
    hill_id: int
    hill_name: str
    current_king: Optional[str] = None
    current_king_team_id: Optional[int] = None
    sla_status: bool = False
    multiplier: float = 1.0
    is_behind_pivot: bool = False


# ---- Tick Schemas ----
class TickResponse(BaseModel):
    id: int
    tick_number: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    results: List["TickResultResponse"] = []

    class Config:
        from_attributes = True

class TickResultResponse(BaseModel):
    hill_id: int
    hill_name: Optional[str] = None
    king_team_id: Optional[int] = None
    king_team_name: Optional[str] = None
    sla_status: bool = False
    points_awarded: int = 0
    check_duration_ms: Optional[int] = None
    # Dual-verification
    ssh_verified: bool = False
    agent_verified: bool = False
    ssh_king_name: Optional[str] = None
    agent_king_name: Optional[str] = None
    verification_count: int = 0

    class Config:
        from_attributes = True

class TickResultSubmit(BaseModel):
    hill_id: int
    king_team_name: Optional[str] = None
    sla_status: bool = False
    raw_king_txt: Optional[str] = None
    check_duration_ms: Optional[int] = None
    error_message: Optional[str] = None


# ---- Agent Report Schemas ----
class AgentReportRequest(BaseModel):
    """Report from hill agent with king.txt content"""
    hill_id: int
    agent_token: str
    king_name: Optional[str] = None
    raw_king_txt: Optional[str] = None
    sla_status: bool = True
    timestamp: Optional[str] = None

class AgentReportResponse(BaseModel):
    status: str
    message: str
    hill_id: int

class AgentStatusResponse(BaseModel):
    hill_id: int
    hill_name: str
    last_report_at: Optional[str] = None
    last_king_name: Optional[str] = None
    agent_alive: bool = False
    seconds_since_report: Optional[int] = None


# ---- Scoreboard Schemas ----
class ScoreboardResponse(BaseModel):
    game_status: str
    current_tick: int
    total_ticks: int
    elapsed_seconds: int = 0
    remaining_seconds: int = 0
    teams: List[TeamScoreResponse]
    hills: List[HillStatusResponse]
    last_updated: datetime
    is_frozen: bool = False

class ScoreDetailResponse(BaseModel):
    team_id: int
    hill_id: int
    hill_name: str
    total_points: int
    ticks_as_king: int
    current_king: bool
    consecutive_ticks: int


# ---- Game Control Schemas ----
class GameControlRequest(BaseModel):
    action: str = Field(..., pattern="^(start|pause|resume|stop)$")

class GameStatusResponse(BaseModel):
    status: str
    current_tick: int
    start_time: Optional[str] = None
    elapsed_seconds: int = 0
    remaining_seconds: int = 0
    is_frozen: bool = False

class ScoreAdjustRequest(BaseModel):
    team_id: int
    points: int
    reason: str


# ---- WebSocket Message Schemas ----
class WSMessage(BaseModel):
    type: str  # 'tick_update', 'king_change', 'first_blood', 'game_event'
    data: dict
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---- First Blood ----
class FirstBloodResponse(BaseModel):
    hill_id: int
    hill_name: str
    team_id: int
    team_name: str
    tick_number: int
    bonus_points: int
    captured_at: datetime

    class Config:
        from_attributes = True


# ---- Team Self-Registration ----
class TeamRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64, pattern="^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=2, max_length=128, pattern="^[a-zA-Z0-9 _\\-().]+$")
    category: str = Field(default="default", max_length=32)
    registration_code: str = Field(..., min_length=1)

class TeamRegisterResponse(BaseModel):
    id: int
    name: str
    display_name: str
    category: str
    token: str
    vpn_ip: Optional[str] = None
    vpn_config_ready: bool = False
    message: str

    class Config:
        from_attributes = True


# ---- Historical Points ----
class TeamPointHistoryEntry(BaseModel):
    tick_number: int
    timestamp: Optional[datetime] = None
    points_this_tick: int = 0
    cumulative_points: int = 0
    hill_id: Optional[int] = None
    hill_name: Optional[str] = None
    was_king: bool = False

class TeamPointHistory(BaseModel):
    team_id: int
    team_name: str
    display_name: Optional[str] = None
    total_points: int = 0
    history: List[TeamPointHistoryEntry] = []

class AllTeamsPointTimeline(BaseModel):
    ticks: List[int] = []
    teams: List[dict] = []  # [{team_id, team_name, points: [cumulative per tick]}]


# ---- Health Check ----
class HealthResponse(BaseModel):
    status: str
    version: str
    db_connected: bool
    redis_connected: bool
    game_status: str
    uptime_seconds: float
