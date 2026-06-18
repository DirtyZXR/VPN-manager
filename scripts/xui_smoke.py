"""Smoke-тест клиента 3x-ui против живой панели.

Прогоняет полный CRUD-цикл клиента через XUIClient и печатает PASS/FAIL по шагам.
Креды берутся ТОЛЬКО из окружения, в коде/репозитории не хранятся.

Запуск (PowerShell):
  $env:XUI_BASE_URL="https://host:8443/path"; $env:XUI_USER="admin"; $env:XUI_PASS="..."
  $env:XUI_INBOUND_ID="2"; $env:XUI_VERIFY_SSL="0"
  python scripts/xui_smoke.py

Переменные окружения:
  XUI_BASE_URL    (обяз.) базовый URL панели вместе с web-path
  XUI_USER        (обяз.) логин панели
  XUI_PASS        (обяз.) пароль панели
  XUI_INBOUND_ID  id inbound для теста (по умолчанию 1)
  XUI_VERIFY_SSL  "1" — проверять сертификат, иначе отключено
  XUI_SMOKE_EMAIL email тест-клиента (по умолчанию smoke-test-client)
"""

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger  # noqa: E402

from app.xui_client.client import XUIClient  # noqa: E402
from app.xui_client.models import XUIAddClientRequest  # noqa: E402

logger.remove()  # тихий вывод, оставляем только PASS/FAIL шагов


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"[FATAL] переменная окружения {name} не задана")
        sys.exit(2)
    return value


async def main() -> None:
    base_url = _require("XUI_BASE_URL")
    user = _require("XUI_USER")
    password = _require("XUI_PASS")
    inbound_id = int(os.environ.get("XUI_INBOUND_ID", "1"))
    verify_ssl = os.environ.get("XUI_VERIFY_SSL", "0") == "1"
    email = os.environ.get("XUI_SMOKE_EMAIL", "smoke-test-client")

    client = XUIClient(base_url=base_url, username=user, password=password, verify_ssl=verify_ssl)
    ok = True

    def step(name: str, passed: bool) -> None:
        nonlocal ok
        print(("[PASS] " if passed else "[FAIL] ") + name)
        ok = ok and passed

    try:
        await client.connect()
        step("connect (login + CSRF)", True)

        inbounds = await client.get_inbounds()
        step(f"get_inbounds -> {len(inbounds)} inbound(s)", len(inbounds) >= 0)

        req = XUIAddClientRequest(
            id=str(uuid.uuid4()), email=email, enable=True, flow="",
            totalGB=1073741824, expiryTime=0, subId="smoke", limitIp=0, tgId=0,
        )
        step("add_client", await client.add_client(req, [inbound_id]))

        traffic = await client.get_client_traffic(email)
        step("get_client_traffic (real uuid получен)", bool(traffic and traffic.get("uuid")))

        req.enable = False
        step("update_client (disable)", await client.update_client(email, req))

        step("reset_client_traffic", await client.reset_client_traffic(email))

        clients = await client.get_clients()
        step("get_clients содержит тест-email", any(c.get("email") == email for c in clients))

        step("delete_client", await client.delete_client(email))
        step("после delete: traffic = None", await client.get_client_traffic(email) is None)
    finally:
        await client.close()

    print("\nИТОГ:", "ALL PASS" if ok else "ЕСТЬ ОШИБКИ")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
