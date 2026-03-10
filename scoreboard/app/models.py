"""
KoTH CTF Platform — SQLAlchemy Models
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Text, DateTime, ForeignKey, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128))
    vpn_ip = Column(String(45))
    token = Column(String(128))
    email = Column(String(255), nullable=True)
    category = Column(String(32), default="default")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    tick_results = relationship("TickResult", back_populates="king_team")
    scores = relationship("Score", back_populates="team")
    team_score = relationship("TeamScore", back_populates="team", uselist=False)
    first_bloods = relationship("FirstBlood", back_populates="team")


class Hill(Base):
    __tablename__ = "hills"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)
    description = Column(Text)
    ip_address = Column(String(45), nullable=False)
    ssh_port = Column(Integer, default=22)
    ssh_user = Column(String(64), nullable=True)  # Per-hill SSH user (overrides global)
    ssh_pass = Column(String(128), nullable=True)  # Per-hill SSH password (overrides global)
    sla_check_url = Column(String(256))
    sla_check_port = Column(Integer)
    sla_check_type = Column(String(32), default="http")
    king_file_path = Column(String(256), default="/root/king.txt")
    base_points = Column(Integer, default=10)
    multiplier = Column(Float, default=1.0)
    is_behind_pivot = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    agent_token = Column(String(128), nullable=True)  # Per-hill agent auth token
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    tick_results = relationship("TickResult", back_populates="hill")
    scores = relationship("Score", back_populates="hill")
    first_blood = relationship("FirstBlood", back_populates="hill", uselist=False)


class Tick(Base):
    __tablename__ = "ticks"

    id = Column(Integer, primary_key=True, index=True)
    tick_number = Column(Integer, unique=True, nullable=False, index=True)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    status = Column(String(16), default="running")
    details = Column(JSON, default={})

    # Relationships
    results = relationship("TickResult", back_populates="tick")


class TickResult(Base):
    __tablename__ = "tick_results"

    id = Column(Integer, primary_key=True, index=True)
    tick_id = Column(Integer, ForeignKey("ticks.id", ondelete="CASCADE"))
    hill_id = Column(Integer, ForeignKey("hills.id", ondelete="CASCADE"))
    king_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    sla_status = Column(Boolean, default=False)
    points_awarded = Column(Integer, default=0)
    raw_king_txt = Column(Text)
    check_duration_ms = Column(Integer)
    error_message = Column(Text)
    checked_at = Column(DateTime, server_default=func.now())

    # ── Dual-Verification Fields ─────────────────────────────────────────
    ssh_verified = Column(Boolean, default=False)       # SSH check succeeded
    agent_verified = Column(Boolean, default=False)     # Agent report received
    ssh_king_name = Column(String(64), nullable=True)   # King name from SSH
    agent_king_name = Column(String(64), nullable=True) # King name from agent
    verification_count = Column(Integer, default=0)     # 0, 1, or 2

    __table_args__ = (UniqueConstraint('tick_id', 'hill_id'),)

    # Relationships
    tick = relationship("Tick", back_populates="results")
    hill = relationship("Hill", back_populates="tick_results")
    king_team = relationship("Team", back_populates="tick_results")


class Score(Base):
    __tablename__ = "scores"

    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    hill_id = Column(Integer, ForeignKey("hills.id", ondelete="CASCADE"), primary_key=True)
    total_points = Column(Integer, default=0)
    ticks_as_king = Column(Integer, default=0)
    current_king = Column(Boolean, default=False)
    consecutive_ticks = Column(Integer, default=0)
    last_updated = Column(DateTime, server_default=func.now())

    # Relationships
    team = relationship("Team", back_populates="scores")
    hill = relationship("Hill", back_populates="scores")


class TeamScore(Base):
    __tablename__ = "team_scores"

    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    total_points = Column(Integer, default=0)
    hills_owned = Column(Integer, default=0)
    total_ticks_as_king = Column(Integer, default=0)
    first_bloods = Column(Integer, default=0)
    last_updated = Column(DateTime, server_default=func.now())

    # Relationships
    team = relationship("Team", back_populates="team_score")


class FirstBlood(Base):
    __tablename__ = "first_bloods"

    hill_id = Column(Integer, ForeignKey("hills.id"), primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    tick_number = Column(Integer)
    bonus_points = Column(Integer, default=50)
    captured_at = Column(DateTime, server_default=func.now())

    # Relationships
    hill = relationship("Hill", back_populates="first_blood")
    team = relationship("Team", back_populates="first_bloods")


class GameConfig(Base):
    __tablename__ = "game_config"

    key = Column(String(64), primary_key=True)
    value = Column(Text)
    description = Column(Text)
    updated_at = Column(DateTime, server_default=func.now())


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, index=True)
    message = Column(Text, nullable=False)
    type = Column(String(16), default="info")          # info | warning | danger
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(32), nullable=False, index=True)
    actor = Column(String(64))
    details = Column(JSON, default={})
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class OrganizerUser(Base):
    """Admin/organizer user accounts for multi-user management."""
    __tablename__ = "organizer_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128))
    password_hash = Column(String(256), nullable=False)
    role = Column(String(16), default="organizer")  # superadmin | organizer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime, nullable=True)


class IndividualUser(Base):
    """Individual user accounts (used when event_mode=individual)."""
    __tablename__ = "individual_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128))
    password_hash = Column(String(256), nullable=False)
    vpn_ip = Column(String(45), nullable=True)
    category = Column(String(32), default="default")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime, nullable=True)
