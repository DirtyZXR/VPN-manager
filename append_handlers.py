import os
import re

file_path = "app/bot/handlers/admin/subscriptions.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Add the new imports if not exist
if "SubscriptionRebuild" not in content:
    content = content.replace(
        "from app.bot.states.admin import (",
        "from app.bot.states.admin import (\n    SubscriptionRebuild,",
    )
    # also add keyboards
    content = content.replace(
        "get_subscription_details_keyboard,",
        "get_subscription_details_keyboard,\n    get_subscription_rebuild_mode_keyboard,",
    )

new_code = """

# ==========================================
# REBUILD SUBSCRIPTION FLOW (Reuse Token)
# ==========================================

@router.callback_query(F.data.startswith("admin_sub_rebuild_"))
async def start_rebuild_subscription(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    \"\"\"Start rebuild subscription flow (reuse token).\"\"\"
    if not is_admin:
        await callback.answer(t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[3])
    await state.clear()
    
    async with async_session_factory() as session:
        from app.services.new_subscription_service import NewSubscriptionService
        service = NewSubscriptionService(session)
        sub = await service.get_subscription(subscription_id)
        if not sub:
            await callback.answer("❌ Подписка не найдена", show_alert=True)
            return
            
    await state.update_data(subscription_id=subscription_id, old_name=sub.name)
    
    text = t(
        "admin.subscriptions.rebuild_mode",
        "🔄 <b>Переиспользование токена (Rebuild)</b>\n\n"
        "Вы собираетесь пересобрать подписку <b>{name}</b>.\n"
        "Токен доступа останется прежним, статистика трафика будет сброшена до нуля.\n\n"
        "Выберите режим настройки:",
        name=sub.name
    )
    await callback.message.edit_text(
        text, 
        reply_markup=get_subscription_rebuild_mode_keyboard(subscription_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rebuild_mode_template_"))
async def rebuild_mode_template(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    \"\"\"Select template for rebuilding.\"\"\"
    if not is_admin:
        await callback.answer(t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[3])
    
    async with async_session_factory() as session:
        from app.services.subscription_template_service import SubscriptionTemplateService
        tpl_service = SubscriptionTemplateService(session)
        templates = await tpl_service.get_all_templates()
        
    if not templates:
        await callback.answer(t("admin.subscriptions.no_templates", "❌ Нет доступных шаблонов"), show_alert=True)
        return
        
    builder = InlineKeyboardBuilder()
    for tpl in templates:
        builder.button(
            text=f"📦 {tpl.name}",
            callback_data=f"rebuild_tpl_{subscription_id}_{tpl.id}"
        )
    builder.button(text=t("common.back", "🔙 Назад"), callback_data=f"admin_sub_rebuild_{subscription_id}")
    builder.adjust(1)
    
    await state.set_state(SubscriptionRebuild.waiting_for_template_selection)
    await callback.message.edit_text(
        t("admin.subscriptions.rebuild_select_template", "📋 <b>Выберите шаблон для применения:</b>"),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(SubscriptionRebuild.waiting_for_template_selection, F.data.startswith("rebuild_tpl_"))
async def rebuild_with_template(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    \"\"\"Rebuild subscription using selected template.\"\"\"
    if not is_admin:
        await callback.answer(t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True)
        return

    parts = callback.data.split("_")
    subscription_id = int(parts[2])
    template_id = int(parts[3])
    
    await callback.message.edit_text(t("admin.subscriptions.rebuild_in_progress", "⏳ Применение шаблона... Пожалуйста, подождите."), reply_markup=None)
    
    data = await state.get_data()
    old_name = data.get("old_name", "Неизвестно")
    
    try:
        async with async_session_factory() as session:
            from app.services.subscription_template_service import SubscriptionTemplateService
            from app.services.new_subscription_service import NewSubscriptionService
            from app.services.notification_service import NotificationService
            
            tpl_service = SubscriptionTemplateService(session)
            template = await tpl_service.get_template(template_id)
            
            inbound_ids = [ti.inbound_id for ti in template.template_inbounds]
            
            service = NewSubscriptionService(session)
            # Rebuild using template parameters, but keeping old sub name (or rename to template name? usually keep sub name)
            # Let's keep the existing name to avoid confusion
            subscription = await service.get_subscription(subscription_id)
            client = subscription.client
            
            updated_sub, connections = await service.rebuild_subscription(
                subscription_id=subscription_id,
                new_name=subscription.name, # keeping old name
                new_total_gb=template.default_total_gb,
                new_expiry_days=template.default_expiry_days,
                new_inbound_ids=inbound_ids,
                template_id=template_id,
                notes=template.notes
            )
            
            # Send notification
            ns = NotificationService(session)
            await ns.notify_subscription_rebuilt(client, updated_sub, old_name)
            
            await session.commit()
            
        await callback.message.edit_text(
            t("admin.subscriptions.rebuild_success", "✅ <b>Подписка успешно пересобрана по шаблону!</b>"),
            reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}"),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error rebuilding subscription {subscription_id} with template {template_id}: {e}", exc_info=True)
        await callback.message.edit_text(
            t("admin.subscriptions.rebuild_error", "❌ Ошибка при пересоздании подписки: {error}", error=str(e)),
            reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}")
        )
    finally:
        await state.clear()


@router.callback_query(F.data.startswith("rebuild_mode_manual_"))
async def rebuild_mode_manual(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    \"\"\"Manual rebuild: Ask for traffic limit.\"\"\"
    if not is_admin:
        await callback.answer(t("errors.admin_only", "❌ У вас нет прав администратора."), show_alert=True)
        return

    subscription_id = int(callback.data.split("_")[3])
    
    await state.update_data(subscription_id=subscription_id)
    await state.set_state(SubscriptionRebuild.waiting_for_traffic_limit)
    
    await callback.message.edit_text(
        t("admin.subscriptions.rebuild_manual_traffic", "⚙️ <b>Ручная настройка</b>\n\nВведите новый лимит трафика в GB (0 для безлимита):"),
        reply_markup=get_back_keyboard(f"admin_sub_rebuild_{subscription_id}"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(SubscriptionRebuild.waiting_for_traffic_limit)
async def rebuild_process_traffic(message: Message, state: FSMContext) -> None:
    try:
        traffic = int(message.text.strip())
        if traffic < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное положительное число (0 для безлимита).")
        return
        
    await state.update_data(new_traffic=traffic)
    await state.set_state(SubscriptionRebuild.waiting_for_expiry_days)
    
    data = await state.get_data()
    sub_id = data.get("subscription_id")
    
    await message.answer(
        t("admin.subscriptions.rebuild_manual_expiry", "Введите новый срок действия в днях (0 для бессрочной):"),
        reply_markup=get_back_keyboard(f"admin_sub_rebuild_{sub_id}")
    )


@router.message(SubscriptionRebuild.waiting_for_expiry_days)
async def rebuild_process_expiry(message: Message, state: FSMContext) -> None:
    try:
        expiry = int(message.text.strip())
        if expiry < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное положительное число (0 для бессрочной).")
        return
        
    await state.update_data(new_expiry=expiry)
    data = await state.get_data()
    sub_id = data.get("subscription_id")
    
    await state.set_state(SubscriptionRebuild.inbounds_multi_select_mode)
    await state.update_data(selected_inbound_ids=set())
    
    async with async_session_factory() as session:
        from app.services.xui_service import XUIService
        xui_service = XUIService(session)
        inbounds = await xui_service.get_all_inbounds()
        
    builder = InlineKeyboardBuilder()
    from collections import defaultdict
    inbounds_by_server = defaultdict(list)
    for inbound in inbounds:
        inbounds_by_server[inbound.server.name].append(inbound)

    for server_name, server_inbounds in sorted(inbounds_by_server.items()):
        for inbound in server_inbounds:
            status = "✅" if inbound.is_active else "❌"
            builder.button(
                text=f"⭕ {status} {inbound.remark} ({server_name})",
                callback_data=f"rebuild_toggle_ib_{inbound.id}"
            )
            
    builder.button(text=t("admin.templates.btn_add_selected", "➡️ Подтвердить выбор"), callback_data="rebuild_confirm_ibs")
    builder.button(text=t("common.back", "🔙 Назад"), callback_data=f"admin_sub_rebuild_{sub_id}")
    builder.adjust(1)
    
    await message.answer(
        t("admin.subscriptions.rebuild_manual_inbounds", "Выберите подключения (inbounds) для подписки:"),
        reply_markup=builder.as_markup()
    )


@router.callback_query(SubscriptionRebuild.inbounds_multi_select_mode, F.data.startswith("rebuild_toggle_ib_"))
async def rebuild_toggle_inbound(callback: CallbackQuery, state: FSMContext) -> None:
    inbound_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    selected = data.get("selected_inbound_ids", set())
    
    if inbound_id in selected:
        selected.remove(inbound_id)
    else:
        selected.add(inbound_id)
        
    await state.update_data(selected_inbound_ids=selected)
    
    async with async_session_factory() as session:
        from app.services.xui_service import XUIService
        xui_service = XUIService(session)
        inbounds = await xui_service.get_all_inbounds()
        
    builder = InlineKeyboardBuilder()
    from collections import defaultdict
    inbounds_by_server = defaultdict(list)
    for inbound in inbounds:
        inbounds_by_server[inbound.server.name].append(inbound)

    for server_name, server_inbounds in sorted(inbounds_by_server.items()):
        for inbound in server_inbounds:
            status = "✅" if inbound.is_active else "❌"
            sel_icon = "🔘" if inbound.id in selected else "⭕"
            builder.button(
                text=f"{sel_icon} {status} {inbound.remark} ({server_name})",
                callback_data=f"rebuild_toggle_ib_{inbound.id}"
            )
            
    builder.button(text=t("admin.templates.btn_add_selected", "➡️ Подтвердить выбор"), callback_data="rebuild_confirm_ibs")
    builder.button(text=t("common.back", "🔙 Назад"), callback_data=f"admin_sub_rebuild_{data.get('subscription_id')}")
    builder.adjust(1)
    
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(SubscriptionRebuild.inbounds_multi_select_mode, F.data == "rebuild_confirm_ibs")
async def rebuild_confirm_inbounds(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        return
        
    data = await state.get_data()
    selected_ids = data.get("selected_inbound_ids", set())
    if not selected_ids:
        await callback.answer("❌ Выберите хотя бы одно подключение!", show_alert=True)
        return
        
    subscription_id = data.get("subscription_id")
    new_traffic = data.get("new_traffic", 0)
    new_expiry = data.get("new_expiry", 0)
    old_name = data.get("old_name", "Неизвестно")
    
    await callback.message.edit_text(t("admin.subscriptions.rebuild_in_progress", "⏳ Перестроение подписки... Пожалуйста, подождите."), reply_markup=None)
    
    try:
        async with async_session_factory() as session:
            from app.services.new_subscription_service import NewSubscriptionService
            from app.services.notification_service import NotificationService
            
            service = NewSubscriptionService(session)
            subscription = await service.get_subscription(subscription_id)
            client = subscription.client
            
            updated_sub, _ = await service.rebuild_subscription(
                subscription_id=subscription_id,
                new_name=subscription.name,
                new_total_gb=new_traffic,
                new_expiry_days=new_expiry if new_expiry > 0 else None,
                new_inbound_ids=list(selected_ids),
                template_id=None,
                notes=subscription.notes
            )
            
            # Send notification
            ns = NotificationService(session)
            await ns.notify_subscription_rebuilt(client, updated_sub, old_name)
            
            await session.commit()
            
        await callback.message.edit_text(
            t("admin.subscriptions.rebuild_success", "✅ <b>Подписка успешно пересобрана!</b>"),
            reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}"),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error rebuilding subscription manually: {e}", exc_info=True)
        await callback.message.edit_text(
            t("admin.subscriptions.rebuild_error", "❌ Ошибка при пересоздании подписки: {error}", error=str(e)),
            reply_markup=get_back_keyboard(f"admin_sub_detail_{subscription_id}")
        )
    finally:
        await state.clear()
"""

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content + new_code)

print("Done appending code!")
