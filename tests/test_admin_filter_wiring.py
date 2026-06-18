"""Тесты router-level AdminFilter: фильтр на 8 админ-роутерах, outer-middleware, fallback."""

from datetime import UTC, datetime

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.filters import AdminFilter
from app.bot.handlers import common, registration
from app.bot.handlers.admin import (
    broadcast,
    clients,
    dashboard,
    requests,
    servers,
    subscriptions,
    sync,
    templates,
)
from app.bot.handlers.user import subscriptions as user_subscriptions
from app.bot.middlewares import AuthMiddleware
from app.main import build_dispatcher

ADMIN_ROUTERS = {
    "dashboard": dashboard.router,
    "broadcast": broadcast.router,
    "servers": servers.router,
    "clients": clients.router,
    "subscriptions": subscriptions.router,
    "sync": sync.router,
    "templates": templates.router,
    "requests": requests.router,
}
USER_ROUTERS = {
    "common": common.router,
    "registration": registration.router,
    "user_subscriptions": user_subscriptions.router,
}


def _message() -> Message:
    return Message(
        message_id=1,
        date=datetime(2020, 1, 1, tzinfo=UTC),
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="x"),
        text="hi",
    )


def _callback() -> CallbackQuery:
    return CallbackQuery(
        id="1",
        from_user=User(id=1, is_bot=False, first_name="x"),
        chat_instance="ci",
        data="x",
    )


async def test_admin_filter_returns_is_admin():
    f = AdminFilter()
    assert await f(_message(), is_admin=True) is True
    assert await f(_message(), is_admin=False) is False


@pytest.mark.parametrize("name", list(ADMIN_ROUTERS))
async def test_admin_routers_block_non_admin(name):
    router = ADMIN_ROUTERS[name]
    for observer, event in (("message", _message()), ("callback_query", _callback())):
        obs = getattr(router, observer)
        passed_non_admin, _ = await obs.check_root_filters(event, is_admin=False)
        passed_admin, _ = await obs.check_root_filters(event, is_admin=True)
        assert passed_non_admin is False, f"{name}.{observer} пропустил не-админа"
        assert passed_admin is True, f"{name}.{observer} отсёк админа"


@pytest.mark.parametrize("name", list(USER_ROUTERS))
async def test_user_routers_not_filtered(name):
    router = USER_ROUTERS[name]
    for observer, event in (("message", _message()), ("callback_query", _callback())):
        passed, _ = await getattr(router, observer).check_root_filters(event, is_admin=False)
        assert passed is True, f"{name}.{observer} не должен фильтроваться по админу"


@pytest.fixture(scope="session")
def app_dispatcher():
    """Единый Dispatcher на сессию: create_router() вызывается ровно один раз
    (aiogram не позволяет переподключить singleton-роутеры к разным родителям)."""
    return build_dispatcher()


def test_auth_middleware_is_outer(app_dispatcher):
    dp = app_dispatcher
    assert any(isinstance(m, AuthMiddleware) for m in dp.message.outer_middleware)
    assert any(isinstance(m, AuthMiddleware) for m in dp.callback_query.outer_middleware)
    assert not any(isinstance(m, AuthMiddleware) for m in dp.message.middleware)
    assert not any(isinstance(m, AuthMiddleware) for m in dp.callback_query.middleware)


def test_fallback_router_registered_last_with_catchall(app_dispatcher):
    # build_dispatcher() включил create_router() как единственный под-роутер dp
    root = app_dispatcher.sub_routers[0]
    last = root.sub_routers[-1]
    assert last.name == "fallback"
    assert len(last.callback_query.handlers) >= 1
