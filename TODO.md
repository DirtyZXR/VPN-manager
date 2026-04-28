# TODO

## Баг: sync_service ломается на AWGInbound/MTProxyInbound — нет xui_id ✅ DONE

**Приоритет:** высокий
**Коммит:** `bf38764`

Рефакторинг в protocol_sync registry. Каждый протокол — свой `ProtocolSyncBase`.

---

## Баг: сгенерированный пароль XUI не работает

**Приоритет:** высокий

### Суть

При подключении существующей 3x-ui с генерацией нового пароля — пароль не подходит для входа в панель. SQL с bcrypt-хешем передаётся через stdin (`input_data=`), но результат в 3x-ui DB не соответствует ожидаемому. Нужно проверить: фактически ли хеш записывается корректно, перезапускается ли контейнер, и совпадает ли bcrypt rounds с тем что ожидает 3x-ui.

---

## Баг: callback.answer() MESSAGE_TOO_LONG

**Приоритет:** высокий
**Файл:** `app/bot/handlers/admin/servers.py:405`
**Ошибка:** `TelegramBadRequest: Bad Request: MESSAGE_TOO_LONG`

### Суть

`test_server` handler вызывает `callback.answer(message, show_alert=True)` с полным текстом ошибки SSH-команды. Telegram ограничивает `callback.answer()` до 200 символов. Если SSH-команда возвращает длинный stderr — ответ превышает лимит.

### Фикс

Обрезать `message` до 190 символов перед передачей в `callback.answer()`, либо отправлять `callback.message.answer()` вместо alert если текст длинный.

---

## Баг: XUI не синхронизируется после добавления ✅ FIXED

**Приоритет:** высокий
**Коммит:** (pending)

### Корневые причины

1. **Пароль хранился plain text** — 3 handler'а записывали `password_encrypted = password` без Fernet-шифрования. `_decrypt_password` молча возвращал `""`.
2. **`verify_ssl = True`** — default в модели, handler'ы не устанавливали при создании XUIPanel. Caddy self-signed → `SSLCertVerificationError`.
3. **Handler игнорировал `sync_server()` return** — всегда показывал «✅ Синхронизация завершена» даже при `False`.

### Фикс

1. Добавлен `encrypt_password()` в `app/utils/__init__.py`. Все 3 handler'а шифруют пароль перед записью.
2. `verify_ssl=False` при создании XUIPanel через инсталлер.
3. `_decrypt_password` теперь кидает `ValueError` вместо возврата `""`.
4. `sync_server` handler проверяет результат и показывает ошибку при `False`

---

## Баг: callback.answer() после долгих операций (Telegram 30с timeout)

**Приоритет:** высокий

### Суть

Telegram callback queries живут ~30 секунд. Если handler выполняет долгую операцию (SSH sync, Docker install) и затем вызывает `callback.answer()` — получаем `Bad Request: query is too old`. Также `callback.answer()` имеет лимит 200 символов для `text` — длинные ошибки SSH вызывают `MESSAGE_TOO_LONG`.

### Места где это происходит

1. **`sync_server` handler** — `sync_server()` делает SSH + API calls (5-30 сек). **FIXED**: теперь `callback.answer()` вызывается до sync, результат отправляется через `message.answer()`.
2. **`test_server` handler** — SSH ping/connection test. Нужен аналогичный фикс.
3. **Все installer handlers** — `install()` может занимать 1-3 мин. Используют `msg.edit_text()` (OK, это не callback), но прогресс-бар может упасть при `TelegramBadRequest`.

### Паттерн для исправления

```python
# 1. Ответить на callback СРАЗУ (до долгой операции)
await callback.answer("🔄 Начинаю...", show_alert=False)

# 2. Выполнить долгую операцию
result = await long_operation()

# 3. Результат отправить через message.answer() (не callback)
await callback.message.answer("✅ Результат: ...")
```

### Осталось исправить

- `test_server` handler (`servers.py:385`) — обрезать error message до 190 символов + early `callback.answer()`
- Проверить все handler'ы где `callback.answer()` вызывается после SSH/API операций

---

## Инсталлеры: предпроверка «уже установлен» ДО мастера установки ✅ DONE

**Коммит:** `4c78942`

---

## Инсталлеры: progress bar при установке ✅ DONE

**Коммит:** `7ddbc22`

`BaseInstaller._progress(step, total, text)` с rate limiting 1/сек. Все 3 инсталлера + 6 handlers.

---

## Архитектура: полный CRUD через BaseVPNProvider

**Приоритет:** высокий

### Суть

Привести `BaseVPNProvider` к единому контракту CRUD для всех 3 протоколов (XUI, AWG, MTProxy). Сейчас `update_client` и `reset_client_traffic` не в абстрактном интерфейсе — вызываются через duck typing. AWG/MTProxy disable — деструктивный (remove вместо мягкого переключения).

### Предлагаемый контракт

```python
class BaseVPNProvider(ABC):
    # CRUD
    async def add_client(inbound, subscription, ...) -> dict
    async def remove_client(inbound, connection) -> bool
    async def update_client(inbound, connection, **kwargs) -> bool
    async def enable_client(inbound, connection) -> bool
    async def disable_client(inbound, connection) -> bool

    # Config
    async def get_client_config(inbound, connection, ...) -> dict

    # Traffic
    async def reset_client_traffic(inbound, connection) -> bool
    async def get_client_traffic(inbound, connection) -> dict | None

    # Lifecycle
    async def close() -> None
```

### Реализация по протоколам

| Метод | XUI | AWG | MTProxy |
|-------|-----|-----|---------|
| `add_client` | REST API ✅ | SSH + awg ✅ | SSH + config ✅ |
| `remove_client` | REST API ✅ | SSH + awg ✅ | SSH + config ✅ |
| `update_client` | REST API ✅ | no-op | no-op |
| `enable_client` | REST API ✅ | SSH (re-add peer) | SSH (re-add secret) |
| `disable_client` | REST API ✅ | SSH (remove from kernel, сохранить данные) | SSH (remove secret) |
| `reset_client_traffic` | REST API ✅ | no-op | no-op |
| `get_client_traffic` | REST API ✅ | no-op (None) | no-op (None) |
| `get_client_config` | sub URL ✅ | .conf + QR ✅ | tg:// link ✅ |

### Дизайн AWG: резервирование данных при отключении

Для AWG критично, чтобы при отключении клиента (disable/expire) его данные **оставались зарезервированными**:
- IP-адрес не освобождался — остаётся за клиентом
- Public/private ключи сохраняются в БД
- Peer удаляется из ядра WG (`awg set wg0 peer ... remove`), но **конфиг не перезаписывается**

При включении (enable/renew):
- Peer добавляется обратно с **теми же** ключами и IP
- Конфиг клиента (`.conf`) не нужно перегенерировать — те же данные

Это позволяет:
- Время истекло → клиент выключился (peer removed from kernel)
- Админ обновил подписку → клиент включился (peer re-added, тот же конфиг)
- Админ очистил → данные удаляются, IP освобождается

### Проверка expiry на стороне бота (AWG)

AWG не имеет API для проверки лимитов. Бот должен:
1. При фоновой синхронизации проверять `connection.expiry_date` и `connection.is_enabled`
2. Если `expiry_date < now()` и `is_enabled` → вызвать `provider.disable_client()`
3. Если админ обновил подписку → вызвать `provider.enable_client()`
4. Это аналогично XUI, но проверка на стороне бота, не панели

MTProxy (классический) — такого функционала не будет.
MTProxy (multi) — будет в будущем, через API mtg-multi.

### План

1. Обновить `BaseVPNProvider` — добавить `update_client`, `reset_client_traffic`, `get_client_traffic`
2. Обновить `XUIProvider` — привести в соответствие
3. Обновить `AmneziaAWGProvider` — реализовать enable/disable с резервированием, no-op для traffic
4. Обновить `MTProxyProvider` — no-op для traffic, enable/disable
5. Обновить `NewSubscriptionService` — убрать duck typing
6. Обновить handlers — убрать хардкод XUI в toggle/rebuild
7. Добавить expiry checker для AWG в sync_service / отдельный background task

### Файлы

- `app/services/vpn_providers/base.py`
- `app/services/vpn_providers/xui_provider.py`
- `app/services/vpn_providers/amnezia_awg.py`
- `app/services/vpn_providers/mtproxy.py`
- `app/services/vpn_providers/factory.py`
- `app/services/new_subscription_service.py`
- `app/bot/handlers/admin/subscriptions.py`
- `app/services/protocol_sync/awg_sync.py` (будущий expiry checker)

---

## Фича: восстановление сервисов из дампа БД

**Приоритет:** средний

### Суть

При установке новых сервисов на сервер предложить восстановить конфигурацию из дампа БД бота. Админ отправляет файл дампа (.sql / .json / .db), бот парсит и восстанавливает привязки серверов, inbounds, подписки.

### Применение

- Переустановка бота на новом сервере — не нужно заново добавлять все серверы и настраивать подписки
- Миграция между инстансами бота

### Что нужно

1. Команда /backup — экспорт БД в файл
2. Команда /restore — приём файла, парсинг, восстановление
3. При первом запуске (нет серверов) — предложить восстановить из дампа

---

## Инсталлеры: автопоиск сервисов на сервере

**Приоритет:** средний

### Что нужно

1. Проверять `docker ps -a --filter name=vpnbot-` — находит все vpnbot-контейнеры
2. Для 3x-ui: дополнительно проверять `docker ps -a` на предмет контейнеров с образами `mhsanaei/3x-ui`, `3x-ui` и т.д. (могут быть установлены не через бота)
3. Для AWG: проверять `awg` интерфейс или порт 51820/udp
4. При обнаружении — предлагать подключить (запросить credentials) или пропустить

---

## Архитектура: миграция хендлеров на session-per-request

**Приоритет:** средний
**Масштаб:** ~157 вызовов `async_session_factory()` в `app/bot/handlers/`

### Суть

Middleware (`app/bot/middlewares/auth.py`) уже передаёт `db_session` в `data` и держит сессию открытой на всё время обработки запроса. Хендлеры по-прежнему открывают свои сессии через `async_session_factory()`, что создаёт параллельные сессии в рамках одного запроса.

### Зачем

- Объект `client` из middleware привязан к сессии middleware, а хендлеры работают в своих сессиях — нет гарантии консистентности
- Лишние подключения к БД на каждый запрос
- `db_session` из `data` позволяет убрать дублирование

### План

1. В каждом хендлере заменить:
   ```python
   async with async_session_factory() as session:
       service = SomeService(session)
       ...
   ```
   на:
   ```python
   session = data["db_session"]
   service = SomeService(session)
   ...
   ```
2. Убрать `from app.database import async_session_factory` из хендлеров после полной миграции
3. Внутренние фоновые задачи (`bg_session`) оставить на `async_session_factory()` — у них нет middleware-контекста

### Файлы для миграции

- `app/bot/handlers/admin/templates.py`
- `app/bot/handlers/admin/subscriptions.py`
- `app/bot/handlers/admin/servers.py`
- `app/bot/handlers/admin/clients.py`
- `app/bot/handlers/user/subscriptions.py`
- Остальные хендлеры, использующие `async_session_factory()`
