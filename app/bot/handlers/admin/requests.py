"""Admin handlers for subscription requests."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger

from app.database import async_session_factory
from app.services.subscription_request_service import SubscriptionRequestService
from app.services.subscription_template_service import SubscriptionTemplateService
from app.services.notification_service import NotificationService
from app.utils.texts import t

router = Router()


@router.callback_query(F.data.startswith("admin_req_approve_"))
async def approve_request(callback: CallbackQuery, is_admin: bool):
    """Approve subscription request."""
    if not is_admin:
        await callback.answer(
            t("admin.requests.access_denied", "⛔ Доступ запрещен"), show_alert=True
        )
        return

    req_id = int(callback.data.split("_")[3])

    async with async_session_factory() as session:
        req_service = SubscriptionRequestService(session)
        request = await req_service.get_request(req_id)

        if not request:
            await callback.answer(
                t("admin.requests.already_processed", "Запрос уже обработан"), show_alert=True
            )
            return

        template_service = SubscriptionTemplateService(session)

        name = request.requested_name or t(
            "admin.requests.template_name", "Подписка из шаблона {name}", name=request.template.name
        )
        telegram_id = request.client.telegram_id

        try:
            subscription, connections = await template_service.create_subscription_from_template(
                template_id=request.template_id, client_id=request.client_id, subscription_name=name
            )

            await req_service.delete_request(req_id)
            await session.commit()

            notification_service = NotificationService(session)
            if telegram_id:
                await notification_service.notify_subscription_created(
                    client=request.client, subscription=subscription, connections=connections
                )

            await callback.message.edit_text(t("admin.requests.approved", "✅ Запрос одобрен."))
            await callback.answer()
        except Exception as e:
            logger.error(f"Failed to approve request {req_id}: {e}")
            await callback.answer(
                t("admin.requests.approve_error", "❌ Ошибка: {error}", error=str(e)),
                show_alert=True,
            )


@router.callback_query(F.data.startswith("admin_req_reject_"))
async def reject_request(callback: CallbackQuery, is_admin: bool):
    """Reject subscription request."""
    if not is_admin:
        await callback.answer(
            t("admin.requests.access_denied", "⛔ Доступ запрещен"), show_alert=True
        )
        return

    req_id = int(callback.data.split("_")[3])

    async with async_session_factory() as session:
        req_service = SubscriptionRequestService(session)
        request = await req_service.get_request(req_id)

        if not request:
            await callback.answer(
                t("admin.requests.already_processed", "Запрос уже обработан"), show_alert=True
            )
            return

        template_name = (
            request.template.name if request.template else t("admin.requests.unknown", "Неизвестно")
        )
        sub_name = request.requested_name or t("admin.requests.not_specified", "Не указано")
        telegram_id = request.client.telegram_id

        await req_service.delete_request(req_id)
        await session.commit()

        notification_service = NotificationService(session)
        if telegram_id:
            await notification_service.notify_user_request_decision(
                telegram_id=telegram_id,
                is_approved=False,
                sub_name=sub_name,
                template_name=template_name,
            )

        await callback.message.edit_text(t("admin.requests.rejected", "❌ Запрос отклонен."))
        await callback.answer()
