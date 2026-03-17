"""Application configuration using pydantic-settings."""

from functools import lru_cache
from typing import Set

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Telegram
    bot_token: str = Field(..., description="Telegram bot token")
    admin_telegram_ids: str = Field(
        default="",
        description="Comma-separated admin Telegram IDs",
    )

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/vpn_manager.db",
        description="Database connection URL",
    )

    # Security
    encryption_key: str = Field(
        ...,
        description="Fernet key for encrypting passwords",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )

    @property
    def admin_ids(self) -> Set[int]:
        """Parse admin Telegram IDs from comma-separated string."""
        if not self.admin_telegram_ids:
            return set()
        return {
            int(id_.strip())
            for id_ in self.admin_telegram_ids.split(",")
            if id_.strip()
        }

    def is_admin(self, telegram_id: int) -> bool:
        """Check if Telegram ID is in admin list."""
        return telegram_id in self.admin_ids


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
