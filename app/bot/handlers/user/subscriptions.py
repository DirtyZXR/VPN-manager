"""User subscription management handlers."""

from collections import defaultdict
from urllib.parse import urljoin

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from loguru import logger

from app.bot.keyboards import get_back_keyboard
from app.bot.keyboards.inline import get_public_templates_keyboard, get_cancel_keyboard
from app.database import async_session_factory
from app.services.new_subscription_service import NewSubscriptionService
from app.services.subscription_request_service import SubscriptionRequestService
from app.services.subscription_template_service import SubscriptionTemplateService
from app.services.notification_service import NotificationService
from app.bot.states.user import UserRequestSubscription
from app.utils.texts import t

router = Router()


@router.callback_query(F.data == "my_subscriptions")
async def show_my_subscriptions(callback: CallbackQuery, client) -> None:
    """Show user's subscriptions."""
    if not client:
        await callback.answer(
            t("user.errors.client_not_found", "❌ Клиент не найден."), show_alert=True
        )
        return

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService

        service = NewSubscriptionService(session)
        subscriptions = await service.get_client_subscriptions(client.id)

    logger.info(
        f"User {client.id} subscriptions: found {len(subscriptions) if subscriptions else 0} subscriptions"
    )

    if not subscriptions:
        await callback.message.edit_text(
            t(
                "user.subs.empty",
                "📝 У вас пока нет подписок.\n\nСвяжитесь с администратором для создания подписки.",
            ),
            reply_markup=get_back_keyboard("admin_menu"),
        )
        await callback.answer()
        return

    text = t("user.subs.list_header", "📝 Ваши подписки ({count}):\n\n", count=len(subscriptions))

    builder = InlineKeyboardBuilder()

    for sub in subscriptions:
        # Use new subscription status property
        status = sub.subscription_status

        text += t(
            "user.subs.list_item",
            "{status} <b>{name}</b>\n   Активных подключений: {active}/{total}\n\n",
            status=status,
            name=sub.name,
            active=sub.active_connections_count,
            total=len(sub.inbound_connections),
        )

        # Add button for each subscription
        builder.button(
            text=t("user.subs.btn_sub", "📝 {name}", name=sub.name),
            callback_data=f"user_sub_select_{sub.id}",
        )

    builder.button(
        text=t("user.subs.btn_urls", "🔗 Subscription URLs"), callback_data="all_sub_urls"
    )
    builder.button(
        text=t("user.subs.btn_status", "📊 Сроки и остатки"),
        callback_data="show_subscription_status",
    )
    builder.button(text=t("common.btn_back", "🔙 Назад"), callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "all_sub_urls")
async def show_all_subscription_urls(callback: CallbackQuery, client) -> None:
    """Show all subscription URLs for user."""
    if not client:
        await callback.answer(
            t("user.errors.client_not_found", "❌ Клиент не найден."), show_alert=True
        )
        return

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        urls = await service.get_subscription_urls(client.id)

    if not urls:
        await callback.answer(
            t("user.subs.no_active", "❌ Нет активных подписок."), show_alert=True
        )
        return

    # Group URLs by subscription ID (unique subscription = subscription_id)
    grouped_subs = defaultdict(list)
    for url_info in urls:
        sub_id = url_info["subscription_id"]
        grouped_subs[sub_id].append(url_info)

    max_length = 4096
    text = t("user.subs.urls_header", "🔗 Subscription URLs:\n\n")

    # Show subscription info with URLs
    for _sub_id, url_list in grouped_subs.items():
        sub_name = url_list[0]["subscription_name"]

        section = t("user.subs.url_group", "<b>Подписка: {name}</b>\n", name=sub_name)

        # Group by URL (different inbounds on same server have same URL)
        # Show unique URLs
        url_map = {}  # url -> server_name
        for url_info in url_list:
            url = url_info["url"]
            server_name = url_info["server_name"]
            if url not in url_map:
                url_map[url] = server_name

        # Add URLs as text (without code blocks)
        for url, _server_name in url_map.items():
            section += f"{url}\n"

        section += "\n"

        # Check if adding this section would exceed limit
        if len(text) + len(section) > max_length:
            section = t(
                "user.subs.urls_hidden",
                "\n... (остальные подписки скрыты из-за ограничений Telegram)",
            )
            text += section
            break

        text += section

    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("user.subs.btn_copy_urls", "📋 Скопировать все URL"), callback_data="copy_all_urls"
    )
    builder.button(text=t("common.btn_back", "🔙 Назад"), callback_data="my_subscriptions")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "copy_all_json_urls")
async def copy_all_json_urls(callback: CallbackQuery, client) -> None:
    """Copy all JSON subscription URLs to clipboard-friendly format."""
    if not client:
        await callback.answer(
            t("user.errors.client_not_found", "❌ Клиент не найден."), show_alert=True
        )
        return

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        urls = await service.get_subscription_json_urls(client.id)

    if not urls:
        await callback.answer(
            t("user.subs.no_active", "❌ Нет активных подписок."), show_alert=True
        )
        return

    # Group URLs by subscription ID (unique subscription = subscription_id)
    from collections import defaultdict

    grouped_subs = defaultdict(list)
    for url_info in urls:
        sub_id = url_info["subscription_id"]
        grouped_subs[sub_id].append(url_info)

    # Build text with all URLs
    max_length = 4096 - 20  # Reserve space for markdown formatting
    text = ""

    for _sub_id, url_list in grouped_subs.items():
        # Group unique URLs by server (same URL = same server)
        url_map = {}
        for url_info in url_list:
            url = url_info["url"]
            server_name = url_info["server_name"]
            if url not in url_map:
                url_map[url] = server_name

        for url, _server_name in url_map.items():
            # Check if adding this URL would exceed limit
            if len(text) + len(url) + 1 > max_length:  # +1 for newline
                break
            text += f"{url}\n"

    # Send as new message instead of callback answer for better copy support
    await callback.message.answer(f"```\n{text}\n```", parse_mode="MarkdownV2")


@router.callback_query(F.data.startswith("user_sub_select_"))
async def show_user_subscription_details(callback: CallbackQuery, client) -> None:
    """Show subscription details for user."""
    if not client:
        await callback.answer(
            t("user.errors.client_not_found", "❌ Клиент не найден."), show_alert=True
        )
        return

    subscription_id = int(callback.data.split("_")[-1])

    async with async_session_factory() as session:
        service = NewSubscriptionService(session)
        subscription = await service.get_subscription(subscription_id)

    if not subscription or subscription.client_id != client.id:
        await callback.answer(t("user.subs.not_found", "❌ Подписка не найдена."), show_alert=True)
        return

    # Use new subscription status property
    status = subscription.subscription_status

    text = t(
        "user.subs.details_header",
        "📝 Подписка: <b>{name}</b>\n\nСтатус: {status}\nСоздана: {created}\nАктивных подключений: {active}/{total}\nТокен: <code>{token}</code>\n\n",
        name=subscription.name,
        status=status,
        created=subscription.created_at.strftime("%d.%m.%Y %H:%M"),
        active=subscription.active_connections_count,
        total=len(subscription.inbound_connections),
        token=subscription.subscription_token,
    )

    # Group URLs by server to avoid duplicates
    server_urls = defaultdict(list)
    for conn in subscription.inbound_connections:
        if conn.is_enabled:
            server = conn.inbound.server
            # Prioritize JSON URL, fallback to standard URL
            subscription_path = getattr(server, "subscription_json_path", None)
            if not subscription_path:
                subscription_path = getattr(server, "subscription_path", "/sub/")
            subscription_url = urljoin(
                server.url, f"{subscription_path}{subscription.subscription_token}"
            )
            server_urls[subscription_url].append(
                {
                    "server_name": server.name,
                    "inbound": conn.inbound,
                    "connection": conn,
                }
            )

    if server_urls:
        text += t("user.subs.active_connections", "📢 Активные подключения:\n\n")
        for url, conn_list in server_urls.items():
            # Show URL once per group
            text += t("user.subs.conn_url", "  • URL: {url}\n", url=url)

            # Show per-inbound traffic and expiry
            for i, conn_data in enumerate(conn_list):
                conn = conn_data["connection"]
                inbound = conn_data["inbound"]

                # Per-inbound traffic
                traffic = (
                    t("user.subs.unlimited", "Безлимит")
                    if conn.is_unlimited
                    else t("user.subs.traffic_gb", "{gb} GB", gb=conn.total_gb)
                )

                # Per-inbound expiry
                from app.utils.date_utils import format_expiry_date

                expiry_info = format_expiry_date(conn.expiry_date, include_time=False)

                # Add empty line before each inbound for better readability (except first)
                if i > 0:
                    text += "\n"

                # Add connection status indicator with server name
                conn_status = "✅" if conn.is_connection_active else "❌"
                server_name = conn_data.get("server_name", "Unknown")
                text += t(
                    "user.subs.conn_info",
                    "    └ {status} {remark} ({protocol}) | {server}\n",
                    status=conn_status,
                    remark=inbound.remark,
                    protocol=inbound.protocol,
                    server=server_name,
                )
                text += t("user.subs.conn_traffic", "      Трафик: {traffic}\n", traffic=traffic)
                text += t("user.subs.conn_expiry", "      Срок: {expiry}\n", expiry=expiry_info)

            text += "\n"

    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("user.subs.btn_back_to_subs", "🔙 Назад к подпискам"),
        callback_data="my_subscriptions",
    )
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_export")
async def export_database(callback: CallbackQuery, client) -> None:
    """Export database to file and send to user (admin only)."""
    if not client or not client.is_admin:
        await callback.answer(
            t("user.errors.admin_only", "❌ Эта функция доступна только администраторам."),
            show_alert=True,
        )
        return

    try:
        # Get database file path from config
        import shutil
        from pathlib import Path

        from app.config import get_settings

        settings = get_settings()

        # Extract database path from connection URL
        db_path = Path(settings.database_url.replace("sqlite+aiosqlite:///", ""))

        # Check if database file exists
        if not db_path.exists():
            await callback.answer(
                t("admin.export.file_not_found", "❌ Файл базы данных не найден."), show_alert=True
            )
            return

        # Check file size (max 1.5 GB)
        file_size = db_path.stat().st_size
        if file_size > 1.5 * 1024 * 1024 * 1024:
            await callback.answer(
                t(
                    "admin.export.file_too_large",
                    "❌ Файл базы данных слишком большой ({size:.1f} MB). Максимум: 1.5 GB",
                    size=file_size / (1024 * 1024),
                ),
                show_alert=True,
            )
            return

        # Create temporary copy to avoid file locking issues
        import tempfile

        temp_dir = tempfile.gettempdir()
        temp_db_path = Path(temp_dir) / f"vpn_manager_export_{client.id}.db"

        try:
            # Show preparation message
            await callback.answer(t("admin.export.preparing", "⏳ Подготовка файла базы данных..."))

            # Copy database file to avoid locking issues
            shutil.copy2(db_path, temp_db_path)
            logger.info(f"Database copied to {temp_db_path} for export")

            # Send database file
            from datetime import datetime

            from aiogram.types import FSInputFile

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            document = FSInputFile(path=temp_db_path, filename=f"vpn_manager_{timestamp}.db")
            await callback.message.answer_document(
                document=document,
                caption=t(
                    "admin.export.caption",
                    "📄 Экспорт базы данных VPN Manager\nРазмер: {size:.2f} MB\nДата: {date}",
                    size=file_size / (1024 * 1024),
                    date=datetime.now().strftime("%d.%m.%Y %H:%M"),
                ),
            )

            await callback.answer(t("admin.export.success", "✅ База данных отправлена!"))
            logger.info(f"Database exported by admin {client.id}: {db_path}")

        finally:
            # Clean up temporary file
            if temp_db_path.exists():
                try:
                    temp_db_path.unlink()
                    logger.debug(f"Temporary database file removed: {temp_db_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove temporary file {temp_db_path}: {e}")

    except Exception as e:
        logger.error(f"Error exporting database for admin {client.id}: {e}", exc_info=True)
        await callback.answer(
            t("admin.export.error", "❌ Ошибка при экспорте базы данных."), show_alert=True
        )


@router.callback_query(F.data == "show_subscription_status")
async def show_subscription_status(callback: CallbackQuery, client) -> None:
    """Show subscription status including expiry and traffic information."""
    if not client:
        await callback.answer(
            t("user.errors.client_not_found", "❌ Клиент не найден."), show_alert=True
        )
        return

    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService

        service = NewSubscriptionService(session)
        subscriptions = await service.get_client_subscriptions(client.id)

    if not subscriptions:
        await callback.answer(
            t("user.subs.no_active", "❌ Нет активных подписок."), show_alert=True
        )
        return

    text = t("user.status.header", "📊 <b>Сроки и остатки подписок</b>\n\n")

    # Get XUI service for traffic data
    from app.services import XUIService

    xui_service = None
    xui_clients = {}

    for sub in subscriptions:
        # Get enabled connections (data is already eager loaded)
        enabled_connections = [conn for conn in sub.inbound_connections if conn.is_enabled]

        if not enabled_connections:
            text += t("user.status.sub_header_empty", "❌ <b>{name}</b>\n", name=sub.name)
            text += t("user.status.no_connections", "   Нет активных подключений\n\n")
            continue

        # Subscription-level expiry (from subscription or from connections)
        from app.utils.date_utils import format_expiry_date

        expiry_text = format_expiry_date(sub.expiry_date, include_time=True)

        text += t("user.status.sub_header", "📦 <b>{name}</b>\n", name=sub.name)
        text += t("user.status.sub_expiry", "   📅 Срок: {expiry}\n", expiry=expiry_text)
        text += t(
            "user.status.sub_connections",
            "   🔌 Активных подключений: {active}/{total}\n\n",
            active=sub.active_connections_count,
            total=len(enabled_connections),
        )

        # Show per-connection details
        text += t("user.status.connections_header", "   <b>Подключения:</b>\n")

        for conn in enabled_connections:
            inbound = conn.inbound
            server = inbound.server

            # Connection expiry
            conn_expiry = format_expiry_date(conn.expiry_date, include_time=True)

            # Connection traffic
            if conn.is_unlimited:
                traffic_text = t("user.subs.unlimited", "Безлимит")
            else:
                traffic_text = t("user.status.traffic_gb", "{gb} ГБ", gb=conn.total_gb)

                # Get actual traffic from XUI
                try:
                    async with async_session_factory() as traffic_session:
                        xui_service = XUIService(traffic_session)
                        if server.id not in xui_clients:
                            xui_clients[server.id] = await xui_service._get_client(server)

                        xui_client = xui_clients[server.id]
                        clients = await xui_client.get_clients(inbound.xui_id)

                        for xui_conn in clients:
                            if xui_conn.get("id") == conn.uuid:
                                used_gb = (xui_conn.get("up", 0) + xui_conn.get("down", 0)) / (
                                    1024**3
                                )
                                remaining_gb = conn.total_gb - used_gb

                                if remaining_gb <= 5:
                                    traffic_text += t(
                                        "user.status.traffic_low",
                                        " (⚠️ осталось {gb:.2f} ГБ)",
                                        gb=remaining_gb,
                                    )
                                else:
                                    traffic_text += t(
                                        "user.status.traffic_remaining",
                                        " (осталось {gb:.2f} ГБ)",
                                        gb=remaining_gb,
                                    )
                                break
                except Exception as e:
                    logger.warning(f"Failed to get traffic for connection {conn.id}: {e}")
                    traffic_text += t("user.status.traffic_error", " (ошибка получения данных)")

            # Add connection status indicator
            conn_status = "✅" if conn.is_connection_active else "❌"
            text += t(
                "user.status.conn_info",
                "      {status} {remark} ({server})\n",
                status=conn_status,
                remark=inbound.remark,
                server=server.name,
            )
            text += t("user.status.conn_expiry", "        📅 Срок: {expiry}\n", expiry=conn_expiry)
            text += t(
                "user.status.conn_traffic", "        📊 Трафик: {traffic}\n", traffic=traffic_text
            )

        text += "\n"

    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("user.subs.btn_back_to_subs", "🔙 Назад к подпискам"),
        callback_data="my_subscriptions",
    )
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

    # Close XUI clients
    for client_obj in xui_clients.values():
        try:
            await client_obj.close()
        except Exception as e:
            logger.warning(f"Error closing XUI client: {e}")


@router.callback_query(F.data == "request_subscription")
async def start_subscription_request(callback: CallbackQuery, client) -> None:
    """Start subscription request process for user."""
    if not client:
        await callback.answer(
            t("user.errors.client_not_found", "❌ Клиент не найден."), show_alert=True
        )
        return

    async with async_session_factory() as session:
        req_service = SubscriptionRequestService(session)
        pending_count = await req_service.get_pending_requests_count(client.id)
        if pending_count >= 5:
            await callback.answer(
                t("user.req.too_many", "У вас слишком много ожидающих заявок."), show_alert=True
            )
            return

        tpl_service = SubscriptionTemplateService(session)
        public_templates = await tpl_service.get_public_templates()

    if not public_templates:
        await callback.answer(
            t("user.req.unavailable", "В данный момент запросы недоступны."), show_alert=True
        )
        return

    text = t("user.req.choose_template", "Выберите шаблон для новой подписки:\n\n")
    for tpl in public_templates:
        desc = tpl.description or t("user.req.no_description", "Нет описания")
        text += t(
            "user.req.template_item", "📦 <b>{name}</b>\n   {desc}\n\n", name=tpl.name, desc=desc
        )

    keyboard = get_public_templates_keyboard(public_templates)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("user_req_tpl_"))
async def handle_template_selection(callback: CallbackQuery, state: FSMContext, client) -> None:
    """Handle template selection for subscription request."""
    if not client:
        await callback.answer(
            t("user.errors.client_not_found", "❌ Клиент не найден."), show_alert=True
        )
        return

    template_id = int(callback.data.split("_")[-1])
    await state.update_data(template_id=template_id)
    await state.set_state(UserRequestSubscription.waiting_for_name)

    await callback.message.answer(
        t(
            "user.req.enter_name",
            "Введите понятное название для вашей подписки (например: Мой Телефон):",
        ),
        reply_markup=get_cancel_keyboard(),
    )
    await callback.answer()


@router.message(UserRequestSubscription.waiting_for_name)
async def process_subscription_request_name(message: Message, state: FSMContext, client) -> None:
    """Process entered name and create subscription request."""
    if not client:
        return

    if not message.text:
        return

    requested_name = message.text.strip()
    if not requested_name:
        await message.answer(t("user.req.invalid_name", "Пожалуйста, введите корректное название."))
        return

    data = await state.get_data()
    template_id = data.get("template_id")

    async with async_session_factory() as session:
        req_service = SubscriptionRequestService(session)
        request = await req_service.create_request(
            client_id=client.id,
            template_id=template_id,
            requested_name=requested_name,
        )

        tpl_service = SubscriptionTemplateService(session)
        template = await tpl_service.get_template(template_id)

        await session.commit()

        notification_service = NotificationService(session)
        await notification_service.notify_admins_new_request(request, template.name)

    await message.answer(
        t(
            "user.req.success",
            "✅ Ваш запрос отправлен администратору. В ближайшее время вы получите ответ",
        )
    )
    await state.clear()
