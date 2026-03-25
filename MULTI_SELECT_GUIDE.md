# Множественный выбор Inbounds

## Описание
Функционал позволяет включать и отключать несколько inbounds в подписке одновременно.

## Использование

### Вход в режим множественного выбора
1. Перейдите в подписку: `admin_menu` → `Список подписок` → выбрать подписку → `Inbounds`
2. Нажмите кнопку `✅ Множественный выбор`

### Режим множественного выбора
- Каждый inbound показывается с чекбоксом (✅ - выбран, ⭕ - не выбран)
- Статус подключения показывается цветом: 🟢 - включен, 🔴 - отключен
- Отображается счетчик выбранных inbounds

### Действия с выбранными inbounds
- **✅ Включить выбранные** - включает все выбранные inbounds
- **❌ Отключить выбранные** - отключает все выбранные inbounds
- **🔙 Выход** - возвращает к обычному списку inbounds

### Подтверждение действий
После выбора действия требуется подтверждение:
- **✅ Подтвердить** - выполнить выбранное действие
- **❌ Отмена** - вернуться к выбору inbounds

## Техническая реализация

### Состояния FSM
- `SubscriptionManagement.inbounds_multi_select_mode` - режим выбора inbounds
- `SubscriptionManagement.inbounds_multi_confirm_action` - подтверждение действия

### Callback data
- `inbounds_multi_select_{subscription_id}` - вход в режим мультивыбора
- `multi_select_conn_{connection_id}` - выбор/снятие выбора подключения
- `multi_select_enable_all` - включить выбранные
- `multi_select_disable_all` - отключить выбранные
- `multi_select_confirm` - подтвердить действие
- `multi_select_cancel` - отмена/выход

### Клавиатуры
- `get_multi_select_keyboard(connections, selected_ids)` - клавиатура с чекбоксами
- `get_multi_select_confirm_keyboard()` - клавиатура подтверждения действия

## Обработчики
1. `enter_multi_select_mode()` - вход в режим мультивыбора
2. `toggle_multi_selection()` - выбор/снятие выбора подключения
3. `enable_selected_connections()` - переход к подтверждению включения
4. `disable_selected_connections()` - переход к подтверждению отключения
5. `confirm_multi_select_action()` - выполнение выбранного действия
6. `cancel_multi_select_action()` - отмена действия
7. `exit_multi_select_mode()` - выход из режима мультивыбора
