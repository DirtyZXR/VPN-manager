import yaml
from pathlib import Path
from loguru import logger
from typing import Any


class TextManager:
    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        self._texts: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.filepath.exists():
            logger.warning(f"Text file not found: {self.filepath}")
            return

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._texts = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load text file {self.filepath}: {e}")

    def get(self, key: str, default: str, **kwargs) -> str:
        parts = key.split(".")
        current = self._texts

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default.format(**kwargs) if kwargs else default

        if isinstance(current, str):
            return current.format(**kwargs) if kwargs else current

        return default.format(**kwargs) if kwargs else default


# Global instance assuming messages.yaml is in the project root
_text_manager = TextManager("messages.yaml")


def t(key: str, default: str, **kwargs) -> str:
    """
    Get a text from messages.yaml by dot-separated key.
    If the key is not found, returns the default value.
    Any kwargs are used to format the resulting string.
    """
    return _text_manager.get(key, default, **kwargs)
