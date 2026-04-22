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

    def _format(self, text: str, **kwargs) -> str:
        if not kwargs:
            return text
        try:
            return text.format(**kwargs)
        except KeyError as e:
            logger.warning(f"Missing kwargs for text formatting. Key expected: {e}, Text: '{text}'")
            return text
        except ValueError as e:
            logger.warning(f"Value error during text formatting: {e}, Text: '{text}'")
            return text
        except Exception as e:
            logger.warning(f"Unexpected error formatting text: {e}")
            return text

    def get(self, key: str, default: str, **kwargs) -> str:
        parts = key.split(".")
        current = self._texts

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return self._format(default, **kwargs)

        if isinstance(current, str):
            return self._format(current, **kwargs)

        return self._format(default, **kwargs)

    def reload(self) -> None:
        """Force reload the YAML file from disk."""
        logger.info(f"Reloading texts from {self.filepath}")
        self._load()


# Global instance assuming messages.yaml is in the project root
_text_manager = TextManager("messages.yaml")


def reload_texts() -> None:
    """Reload all texts from the messages.yaml file."""
    _text_manager.reload()


def t(key: str, default: str, **kwargs) -> str:
    """
    Get a text from messages.yaml by dot-separated key.
    If the key is not found, returns the default value.
    Any kwargs are used to format the resulting string.
    """
    return _text_manager.get(key, default, **kwargs)
