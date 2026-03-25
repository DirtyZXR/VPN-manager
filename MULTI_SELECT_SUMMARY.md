# Реализация множественного выбора Inbounds

## Что было сделано

### 1. Добавлен импорт `InlineKeyboardMarkup`
В файле `app/bot/handlers/admin/subscriptions.py` добавлен импорт:
```python
from aiogram.types import InlineKeyboardMarkup
```

### 2. Реализован режим множественного выбора

#### Обработчик входа в режим
`enter_multi_select_mode()` - обрабатывает кнопку `✅ Множественный выбор`
- Получает все подключения подписки
- Сохраняет subscription_id и пустой набор выбранных подключений
- Переключает состояние в `inbounds_multi_select_mode`
- Отображает клавиатуру с чекбоксами

#### Обработчик выбора/снятия выбора
`toggle_multi_selection()` - обрабатывает клики по inbounds
- Добавляет/удаляет подключение из набора выбранных
- Обновляет клавиатуру с учетом текущего выбора
- Отображает счетчик выбранных inbounds

#### Обработчики массовых действий
`enable_selected_connections()` - включить все выбранные inbounds
- Проверяет наличие выбранных подключений
- Переключает состояние в `inbounds_multi_confirm_action`
- Отображает окно подтверждения

`disable_selected_connections()` - отключить все выбранные inbounds
- Проверяет наличие выбранных подключений
- Переключает состояние в `inbounds_multi_confirm_action`
- Отображает окно подтверждения

#### Обработчики подтверждения
`confirm_multi_select_action()` - выполнение выбранного действия
- Получает список выбранных подключений и тип действия
- Вызывает `service.toggle_inbound_connection()` для каждого подключения
- Отображает результат выполнения
- Очищает состояние FSM

`cancel_multi_select_action()` - отмена действия и возврат к выбору
- Восстанавливает состояние `inbounds_multi_select_mode`
- Обновляет клавиатуру выбора

`exit_multi_select_mode()` - выход из режима мультивыбора
- Очищает состояние FSM
- Перенаправляет к списку inbounds подписки

### 3. Вспомогательные функции

#### Клавиатура с чекбоксами
`get_multi_select_keyboard(connections, selected_ids)` - создает клавиатуру с чекбоксами
- Отображает каждый inbound с чекбоксом и статусом
- Добавляет кнопки для массовых действий
- Добавляет кнопку выхода

#### Клавиатура подтверждения
`get_multi_select_confirm_keyboard()` - создает клавиатуру подтверждения действия
- Кнопка "Подтвердить"
- Кнопка "Отмена"

## Интеграция с существующим кодом

### Использование существующих состояний
- `SubscriptionManagement.inbounds_multi_select_mode` - режим выбора
- `SubscriptionManagement.inbounds_multi_confirm_action` - подтверждение действия

### Использование существующих сервисов
- `NewSubscriptionService.get_subscription_inbounds()` - получение подключений
- `NewSubscriptionService.toggle_inbound_connection()` - включение/отключение

### Callback data
- `inbounds_multi_select_{subscription_id}` - вход в режим
- `multi_select_conn_{connection_id}` - выбор подключения
- `multi_select_enable_all` - включить выбранные
- `multi_select_disable_all` - отключить выбранные
- `multi_select_confirm` - подтвердить действие
- `multi_select_cancel` - отмена/выход

## Как это работает

### Пользовательский поток
1. Пользователь переходит в подписку → Inbounds
2. Нажимает кнопку `✅ Множественный выбор`
3. Отображается список inbounds с чекбоксами
4. Пользователь отмечает нужные inbounds
5. Выбирает действие: включить или отключить
6. Подтверждает действие
7. Возвращает к списку inbounds или выходит

### Хранение данных
- `subscription_id` - ID подписки
- `selected_connections` - набор ID выбранных подключений
- `action` - тип действия (enable/disable)

## Тестирование

### Базовый тест
```python
# Проверка входа в режим
callback_data = "inbounds_multi_select_1"

# Проверка выбора подключения
callback_data = "multi_select_conn_1"

# Проверка массового включения
callback_data = "multi_select_enable_all"

# Проверка подтверждения
callback_data = "multi_select_confirm"
```

## Примечания

- Кнопка `✅ Множественный выбор` уже существовала на строке 580
- Состояния FSM уже существовали в `app/bot/states/admin.py`
- Добавлена полная реализация функционала
- Все обработчики используют существующие сервисы и модели
