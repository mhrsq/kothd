"""
KoTH CTF Platform — Configuration
All secrets MUST be set via environment variables or .env file.
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "koth"
    postgres_user: str = "koth_admin"
    postgres_password: str = ""

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_secret_key: str = ""
    api_admin_token: str = ""
    api_debug: bool = False

    # Tick Engine
    tick_interval: int = 60
    tick_grace_period: int = 300
    tick_freeze_before_end: int = 1800
    game_duration_hours: int = 6

    # Scoring
    base_points: int = 10
    pivot_multiplier: float = 1.5
    first_blood_bonus: int = 50
    defense_streak_bonus: int = 5

    # Event mode: "team" or "individual"
    event_mode: str = "team"

    # Registration
    registration_enabled: bool = True
    registration_code: str = ""

    # Scorebot
    scorebot_host: str = "scorebot"
    scorebot_port: int = 8081
    scorebot_check_timeout: int = 15

    # Branding
    event_name: str = "KoTH CTF"
    event_subtitle: str = "King of the Hill Competition"

    @field_validator('postgres_password', 'api_secret_key', 'api_admin_token')
    @classmethod
    def must_not_be_empty(cls, v, info):
        if not v:
            raise ValueError(
                f"{info.field_name} must be set in .env — "
                f"see .env.example for reference"
            )
        return v

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def database_url_sync(self) -> str:
        return f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
