"""Восстановление 3x-ui после рассинхрона БД/контейнера."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message as TgMessage
from loguru import logger

from app.bot.handlers.admin.servers.services import show_server_services
from app.bot.keyboards import get_back_keyboard
from app.bot.states import ServerManagement
from app.database import async_session_factory

router = Router()


@router.callback_query(F.data.startswith("xui_desync_remove_db_"))
async def xui_desync_remove_db(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])
    async with async_session_factory() as session:
        from sqlalchemy import delete

        from app.database.models import Inbound, XUIPanel
        await session.execute(delete(XUIPanel).where(XUIPanel.server_id == server_id))
        await session.execute(delete(Inbound).where(Inbound.server_id == server_id, Inbound.protocol.in_(("vless", "vmess", "trojan", "shadowsocks", "wireguard", "socks", "http"))))
        await session.commit()
    await callback.answer("✅ 3x-ui панель и инбаунды удалены из БД", show_alert=True)
    await show_server_services(callback, state)

@router.callback_query(F.data.startswith("xui_desync_restore_db_"))
async def xui_desync_restore_db(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])

    msg = await callback.message.edit_text("🔄 <b>Аварийное восстановление 3x-ui из БД...</b>\n\nНачинаю переустановку панели...", parse_mode="HTML")

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            server = (await session.execute(select(Server).options(selectinload(Server.xui_panel)).where(Server.id == server_id))).scalar_one()
            panel = server.xui_panel

            from app.services.installers.xui_installer import XUIInstaller
            from app.services.ssh_service import SSHManager
            from app.utils import decrypt_password

            installer = XUIInstaller(SSHManager(server, session=session), progress_callback=lambda text: msg.edit_text(f"🔄 <b>Аварийное восстановление 3x-ui</b>\n\n{text}", parse_mode="HTML"))

            # Need to initialize sudo if needed
            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return


            pwd = decrypt_password(panel.password_encrypted) if panel.password_encrypted else "admin"
            domain = panel.url.split("://")[1].split(":")[0] if panel.url else server.ip_address

            await installer.install(
                domain=domain,
                caddy_port=panel.caddy_port or 8443,
                web_path=panel.panel_path or "/",
                sub_path=panel.subscription_path or "/sub/",
                sub_json_path=panel.subscription_json_path or "/json/",
                username=panel.username or "admin",
                password=pwd,
                inbound_ranges=panel.inbound_ranges or [(10000, 10100)],
                force=True
            )

            # Now restore inbounds and connections
            from app.database.models import Inbound, XUIInboundConnection
            from app.xui_client import XUIAddClientRequest, XUIClient

            await msg.edit_text("🔄 <b>Аварийное восстановление 3x-ui</b>\n\nВосстановление Inbound'ов и пользователей...", parse_mode="HTML")

            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(panel.url or "")
            _scheme = _parsed.scheme or "http"
            _hostname = _parsed.hostname or panel.url or ""
            _port = _parsed.port
            _base_path = panel.panel_path or "/"
            if _parsed.path and _parsed.path != "/" and not panel.panel_path:
                _base_path = _parsed.path
            _port_part = f":{_port}" if _port else ""
            _base_url = f"{_scheme}://{_hostname}{_port_part}{_base_path}"

            async with XUIClient(
                base_url=_base_url,
                username=panel.username or "",
                password=pwd,
                api_token=None,
            ) as client:
                inbounds = (await session.execute(select(Inbound).where(Inbound.server_id == server_id, Inbound.protocol.in_(("vless", "vmess", "trojan", "shadowsocks", "wireguard", "socks", "http"))))).scalars().all()
                for ib in inbounds:
                    payload = {
                        "up": 0, "down": 0, "total": 0, "remark": ib.remark or f"Inbound_{ib.port}",
                        "enable": True, "expiryTime": 0, "listen": "", "port": ib.port, "protocol": ib.protocol,
                        "settings": '{"clients": [], "fallbacks": []}',
                        "streamSettings": '{"network": "tcp", "security": "none", "tcpSettings": {"header": {"type": "none"}}}',
                        "sniffing": '{"enabled": true, "destOverride": ["http", "tls", "quic"], "metadataOnly": false, "routeOnly": false}'
                    }
                    try:
                        await client.add_inbound(payload)
                    except Exception as e:
                        logger.warning(f"Failed to recreate inbound {ib.id} port {ib.port}: {e}")

                    # Add clients to this inbound
                    connections = (await session.execute(select(XUIInboundConnection).where(XUIInboundConnection.inbound_id == ib.id))).scalars().all()
                    for conn in connections:
                        if conn.is_enabled:
                            try:
                                p = conn.provider_payload or {}
                                req = XUIAddClientRequest(
                                    id=conn.uuid or p.get("uuid", ""),
                                    email=conn.email or p.get("email", f"conn-{conn.id}"),
                                    enable=True,
                                    flow=p.get("flow", "xtls-rprx-vision"),
                                    totalGB=p.get("totalGB", 0),
                                    expiryTime=p.get("expiryTime", 0),
                                    subId=p.get("subId", ""),
                                    tgId=p.get("tgId", 0),
                                )
                                await client.add_client(req, [ib.xui_id])
                            except Exception as e:
                                logger.warning(f"Failed to recreate client {conn.id}: {e}")

        await msg.edit_text("✅ <b>Аварийное восстановление 3x-ui завершено!</b>\n\nБазовые настройки и клиенты воссозданы. Тонкие настройки Xray (сертификаты/streamSettings) могли сброситься к значениям по умолчанию.", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to restore 3x-ui: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")

@router.callback_query(F.data.startswith("xui_desync_restore_file_"))
async def xui_desync_restore_file(callback: CallbackQuery, state: FSMContext) -> None:
    server_id = int(callback.data.split("_")[-1])
    await state.update_data(server_id=server_id)
    await state.set_state(ServerManagement.waiting_for_restore_file)

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data=f"server_services_{server_id}")]])

    await callback.message.edit_text(
        "📂 <b>Восстановление 3x-ui из бэкапа</b>\n\n"
        "Пожалуйста, отправьте файл <code>x-ui.db</code> в этот чат (как документ).\n"
        "⚠️ <i>Убедитесь, что это именно тот файл от панели, которая была привязана к боту.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(ServerManagement.waiting_for_restore_file, F.document)
async def process_xui_restore_file(message: TgMessage, state: FSMContext) -> None:
    document = message.document
    if not document.file_name.endswith(".db"):
        await message.answer("❌ Пожалуйста, отправьте файл с расширением .db (например, x-ui.db)")
        return

    data = await state.get_data()
    server_id = data.get("server_id")
    if not server_id:
        await message.answer("❌ Ошибка сессии. Начните заново.")
        await state.clear()
        return

    msg = await message.answer("🔄 Скачивание файла...")

    import base64

    from aiogram import Bot

    bot: Bot = message.bot
    file_id = document.file_id
    file_path_tg = (await bot.get_file(file_id)).file_path

    # Download file to memory
    file_bytes = await bot.download_file(file_path_tg)
    db_content = file_bytes.read()

    # Encode to base64 for safe transfer
    b64_db = base64.b64encode(db_content).decode("ascii")

    await msg.edit_text("🔄 <b>Восстановление 3x-ui из файла x-ui.db...</b>\n\nЗагрузка БД на сервер для анализа...", parse_mode="HTML")

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.database.models import Server

            server = (await session.execute(select(Server).options(selectinload(Server.xui_panel)).where(Server.id == server_id))).scalar_one()
            panel = server.xui_panel

            from app.services.installers.xui_installer import XUIInstaller
            from app.services.ssh_service import SSHManager
            from app.utils import decrypt_password

            ssh = SSHManager(server, session=session)
            installer = XUIInstaller(ssh, progress_callback=lambda text: msg.edit_text(f"🔄 <b>Восстановление 3x-ui (Файл)</b>\n\n{text}", parse_mode="HTML"))

            ok, err_msg = await installer.preflight_check()
            if not ok:
                await msg.edit_text(f"❌ Ошибка проверки прав:\n<code>{err_msg}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
                return

            pwd = decrypt_password(panel.password_encrypted) if panel.password_encrypted else "admin"
            domain = panel.url.split("://")[1].split(":")[0] if panel.url else server.ip_address
            caddy_port = panel.caddy_port or 8443

            # 1. Сначала загружаем БД на сервер во временную папку
            tmp_db = "/tmp/x-ui_restore.db"
            # Для больших файлов echo 'huge_b64' ломает SSH сессию
            # Поэтому сначала пишем файл штатным методом asyncssh
            await ssh.write_file(tmp_db + ".b64", b64_db)
            # А затем декодируем его через sudo (чтобы права были нужные)
            await installer._cmd(f"base64 -d {tmp_db}.b64 > {tmp_db}")
            await installer._cmd(f"rm {tmp_db}.b64")

            # 2. Анализируем БД прямо на сервере с помощью sqlite3
            await msg.edit_text("🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nИзвлечение путей и портов из БД...", parse_mode="HTML")

            # Убедимся, что sqlite3 установлен
            await installer._cmd("apt-get update -yq && apt-get install -yq sqlite3 || yum install -yq sqlite || apk add --no-cache sqlite")

            # Читаем пути
            web_path = await installer._cmd(f"sqlite3 {tmp_db} \"SELECT value FROM settings WHERE key='webBasePath'\" 2>/dev/null || echo ''")
            sub_path = await installer._cmd(f"sqlite3 {tmp_db} \"SELECT value FROM settings WHERE key='subPath'\" 2>/dev/null || echo ''")
            sub_json_path = await installer._cmd(f"sqlite3 {tmp_db} \"SELECT value FROM settings WHERE key='subJsonPath'\" 2>/dev/null || echo ''")

            web_path = web_path.strip() or "/"
            sub_path = sub_path.strip() or "/sub/"
            sub_json_path = sub_json_path.strip() or "/json/"

            # Читаем порты инбаундов
            inbound_ports_raw = await installer._cmd(f"sqlite3 {tmp_db} \"SELECT port FROM inbounds\" 2>/dev/null || echo ''")
            inbound_ranges = []
            for port_str in inbound_ports_raw.strip().split('\n'):
                if port_str.strip().isdigit():
                    p = int(port_str.strip())
                    inbound_ranges.append((p, p))

            if not inbound_ranges:
                inbound_ranges = panel.inbound_ranges or [(10000, 10100)]

            await msg.edit_text(f"🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nПути: {web_path}\nИнбаунды: {len(inbound_ranges)} шт.\n\nНачинаю установку...", parse_mode="HTML")

            # 3. Выполняем установку с извлеченными параметрами
            await installer.install(
                domain=domain,
                caddy_port=caddy_port,
                web_path=web_path,
                sub_path=sub_path,
                sub_json_path=sub_json_path,
                username=panel.username or "admin",
                password=pwd,
                inbound_ranges=inbound_ranges,
                force=True
            )

            # 4. Переносим файл БД в контейнер
            await msg.edit_text("🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nЗамещение БД в контейнере...", parse_mode="HTML")
            await installer._cmd("docker stop vpnbot-xui")
            await installer._cmd(f"mv {tmp_db} /opt/vpnbot/xui/db/x-ui.db")
            await installer._cmd("docker start vpnbot-xui")
            import asyncio
            await asyncio.sleep(3)

            # 5. Принудительно перезаписываем пароль/домен в БД, чтобы гарантировать доступ бота к API
            await msg.edit_text("🔄 <b>Восстановление 3x-ui (Файл)</b>\n\nСинхронизация учетных данных бота...", parse_mode="HTML")
            await installer._configure_xui(
                username=panel.username or "admin",
                password=pwd,
                web_path=web_path,
                sub_path=sub_path,
                sub_json_path=sub_json_path,
                domain=domain,
                caddy_port=caddy_port
            )

            # 6. Обновляем пути и диапазоны в БД бота
            panel.panel_path = web_path
            panel.subscription_path = sub_path
            panel.subscription_json_path = sub_json_path
            panel.inbound_ranges = inbound_ranges
            await session.commit()

        await msg.edit_text("✅ <b>Панель 3x-ui успешно восстановлена из файла!</b>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
        await state.clear()
    except Exception as e:
        logger.error(f"Failed to restore 3x-ui from file: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка восстановления:\n<code>{e}</code>", reply_markup=get_back_keyboard(f"server_services_{server_id}"), parse_mode="HTML")
        await state.clear()
