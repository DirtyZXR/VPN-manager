"""Характеризующий тест структуры servers.router.

Замораживает множество (имя функции + кратность) зарегистрированных
хэндлеров в агрегированном servers.router, обходя дерево под-роутеров.
Гарантирует, что распил god-файла не потерял, не задублировал и не
переименовал ни одного хэндлера. Должен оставаться зелёным после
каждого шага распила.
"""

import json
import os
from collections import Counter
from pathlib import Path

from app.bot.handlers.admin import servers

GOLDEN = Path(__file__).parent / "data" / "servers_router_handlers.json"


def _collect(router) -> Counter:
    """Рекурсивно собрать кратности (observer:имя_функции) по дереву роутера."""
    counter: Counter = Counter()
    for observer_name in ("message", "callback_query"):
        observer = getattr(router, observer_name)
        for handler in observer.handlers:
            counter[f"{observer_name}:{handler.callback.__name__}"] += 1
    for sub in router.sub_routers:
        counter.update(_collect(sub))
    return counter


def test_servers_router_matches_snapshot():
    current = _collect(servers.router)

    # Регенерация снимка: REGEN_SERVERS_SNAPSHOT=1 pytest ...
    if os.environ.get("REGEN_SERVERS_SNAPSHOT"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(dict(sorted(current.items())), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    expected = Counter(json.loads(GOLDEN.read_text(encoding="utf-8")))
    missing = expected - current
    extra = current - expected
    assert current == expected, (
        f"servers.router изменился. Потеряно: {dict(missing)}; лишнее/дубли: {dict(extra)}"
    )
