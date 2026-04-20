"""Application settings loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, extra="ignore")

    APP_ENV: str = Field(default="development")

    MYSQL_HOST: str = Field(default="db")
    MYSQL_PORT: int = Field(default=3306)
    MYSQL_DATABASE: str = Field(default="jobsearchpal")
    MYSQL_USER: str = Field(default="jsp")
    MYSQL_PASSWORD: str = Field(default="")

    SESSION_SECRET: str = Field(default="dev-only-change-me")
    MASTER_SECRET: str = Field(default="dev-only-change-me")

    ANTHROPIC_API_KEY: str = Field(default="")
    ANTHROPIC_DEFAULT_MODEL: str = Field(default="claude-sonnet-4-6")

    CLAUDE_CODE_BIN: str = Field(default="claude")
    SKILLS_DIR: str = Field(default="/app/skills")

    ACCESS_TOKEN_TTL_MIN: int = Field(default=60 * 24 * 7)  # 7 days
    COOKIE_NAME: str = Field(default="jsp_session")
    COOKIE_SECURE: bool = Field(default=False)  # set True behind TLS

    @property
    def sync_database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    @property
    def async_database_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
