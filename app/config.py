"""Application configuration using pydantic-settings."""

from functools import lru_cache
from pathlib import Path

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

    # XUI Client
    xui_timeout: int = Field(
        default=30,
        description="XUI client timeout in seconds",
    )

    @property
    def admin_ids(self) -> set[int]:
        """Parse admin Telegram IDs from comma-separated string."""
        if not self.admin_telegram_ids:
            return set()
        return {int(id_.strip()) for id_ in self.admin_telegram_ids.split(",") if id_.strip()}

    def is_admin(self, telegram_id: int) -> bool:
        """Check if Telegram ID is in admin list."""
        return telegram_id in self.admin_ids


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


_instructions_cache: dict | None = None


def load_instructions() -> dict:
    """Load all instructions from YAML files in content/ directory with caching.

    Returns:
        Dictionary mapping filename (without .yaml) to parsed YAML content.
    """
    global _instructions_cache
    if _instructions_cache is not None:
        return _instructions_cache

    import yaml

    content_dir = Path(__file__).parent.parent / "content"
    result = {}

    if content_dir.exists() and content_dir.is_dir():
        for file_path in content_dir.glob("*.yaml"):
            with open(file_path, encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f)
                    if data is not None:
                        result[file_path.stem] = data
                except yaml.YAMLError:
                    pass

    _instructions_cache = result
    return result


def reload_instructions() -> dict:
    """Force reload instructions from YAML files (clears cache).

    Returns:
        Freshly loaded instructions dictionary.
    """
    global _instructions_cache
    _instructions_cache = None
    return load_instructions()
