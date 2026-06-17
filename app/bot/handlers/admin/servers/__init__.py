"""Админ-хэндлеры управления серверами (агрегатор под-роутеров)."""

from aiogram import Router

from app.bot.handlers.admin.servers import (
    awg,
    crud,
    first_setup,
    monitoring,
    mtproxy,
    services,
    ssh,
    xui_desync,
    xui_edit,
    xui_install,
)

router = Router()

for _module in (
    crud,
    ssh,
    monitoring,
    services,
    first_setup,
    xui_install,
    xui_edit,
    xui_desync,
    awg,
    mtproxy,
):
    router.include_router(_module.router)
