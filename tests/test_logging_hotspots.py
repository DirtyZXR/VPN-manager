"""Гард: в почищенных хотспотах не осталось [TAG]-префиксов логов."""

from pathlib import Path

import pytest

TAGS = [
    "[SYNC]", "[OK]", "[ERROR]", "[LOG]", "[RECONCILE]", "[SKIP]",
    "[WARN]", "[STOP]", "[PAUSE]", "[STATS]", "[NEW]", "[TOTAL LOG]",
]
HOTSPOTS = [
    "app/services/sync_service.py",
    "app/services/notification_service.py",
    "app/services/notification_checker.py",
    "app/services/subscription_template_service.py",
    "app/main.py",
    "app/services/protocol_sync/__init__.py",
    "app/services/protocol_sync/xui_sync.py",
    "app/services/protocol_sync/mtproxy_sync.py",
    "app/services/protocol_sync/awg_sync.py",
    "app/xui_client/client.py",
]


@pytest.mark.parametrize("path", HOTSPOTS)
def test_no_tag_prefixes(path):
    text = Path(path).read_text(encoding="utf-8")
    found = [t for t in TAGS if t in text]
    assert not found, f"{path}: остались теги {found}"
