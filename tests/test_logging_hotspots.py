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
    # Батч 2: installers + vpn_providers + core-сервисы
    "app/services/installers/base.py",
    "app/services/installers/xui_installer.py",
    "app/services/installers/mtproxy_installer.py",
    "app/services/installers/awg_installer.py",
    "app/services/new_subscription_service.py",
    "app/services/xui_service.py",
    "app/services/ssh_service.py",
    "app/services/auto_discovery.py",
    "app/services/server_monitor.py",
    "app/services/client_service.py",
    "app/services/vpn_providers/amnezia_awg.py",
    "app/services/vpn_providers/mtproxy.py",
    "app/services/vpn_providers/port_manager.py",
    "app/utils/texts.py",
]


@pytest.mark.parametrize("path", HOTSPOTS)
def test_no_tag_prefixes(path):
    text = Path(path).read_text(encoding="utf-8")
    found = [t for t in TAGS if t in text]
    assert not found, f"{path}: остались теги {found}"
