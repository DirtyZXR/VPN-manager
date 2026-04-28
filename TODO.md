# TODO

## Баг: callback.answer() MESSAGE_TOO_LONG

**Приоритет:** высокий
**Файл:** `app/bot/handlers/admin/servers.py:405`
**Ошибка:** `TelegramBadRequest: Bad Request: MESSAGE_TOO_LONG`

### Суть

`test_server` handler вызывает `callback.answer(message, show_alert=True)` с полным текстом ошибки SSH-команды. Telegram ограничивает `callback.answer()` до 200 символов. Если SSH-команда возвращает длинный stderr — ответ превышает лимит.

### Фикс

Обрезать `message` до 190 символов перед передачей в `callback.answer()`, либо отправлять `callback.message.answer()` вместо alert если текст длинный.

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

## 3x-ui: синхронизация путей из панели в бота

**Приоритет:** средний

### Суть

При синхронизации сервера бот должен обновлять пути (webBasePath, subPath, subJsonPath) из 3x-ui панели в свою БД (`XUIPanel`). Если админ изменил пути через веб-интерфейс панели — бот должен подхватить изменения.

Аналогично — обновлять Caddyfile на сервере если пути в боте изменились.

### Что нужно

1. В `sync_server()` при синхронизации XUI — читать `settings` из SQLite панели через SSH
2. Сравнивать с `XUIPanel.panel_path`, `subscription_path`, `subscription_json_path`
3. Если различаются — обновлять БД бота и предлагать админу обновить Caddyfile
4. Кнопка «Обновить Caddyfile» — перезаписать Caddyfile на сервере из текущих данных бота

---

## 3x-ui: смена IP → domain и обратно

**Приоритет:** средний

### Суть

Админ должен иметь возможность сменить адрес сервера (IP ↔ domain) без переустановки. Например:
- Сервер сначала добавлен по IP → позже привязали домен
- Сервер перенесли на другой IP
- Домен сменился

### Что нужно

1. В настройках сервера (edit server menu) — кнопка «🌐 Сменить адрес»
2. Ввод нового адреса (IP или domain)
3. Обновить: `Server.ip_address`, `XUIPanel.url`, Caddyfile на сервере
4. Если был self-signed (IP) → стал domain → Caddy получит Let's Encrypt автоматически
5. Если был domain → стал IP → установить `verify_ssl=False`

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

---

## Фича: мониторинг трафика AWG

**Приоритет:** средний

### Суть

AWG (WireGuard) отдаёт per-peer трафик через `awg show awg0 transfer`:
```
peer_pubkey    rx_bytes    tx_bytes    last_handshake
```

Счётчики сырые — с момента старта интерфейса, сбрасываются при рестарте контейнера.

### Реализация

1. В `AWGProtocolSync.sync_clients()` — SSH `docker exec vpnbot-awg awg show awg0 transfer`
2. Парсить public_key → rx/tx bytes
3. Сравнить с предыдущим значением из `connection.provider_payload["last_rx"]`/`"last_tx"`
4. Если дельта > 0 — прибавить к `connection.used_gb` (нужна колонка)
5. Если `used_gb >= total_gb` → disable
6. Компенсация сброса: если текущие счётчики < предыдущих → перезапуск контейнера, прибавить текущие к accumulated

### Ограничения

- Точность ±5 минут (зависит от sync interval)
- Лёгкий SSH-вызов раз в 5 минут
- Нужна колонка `used_gb` в `AWGInboundConnection` + Alembic миграция

### Файлы

- `app/services/protocol_sync/awg_sync.py` — основная логика
- `app/services/vpn_providers/amnezia_awg.py` — `get_client_traffic()`
- `app/database/models/inbound_connection.py` — колонка `used_gb`
- `app/bot/handlers/user/subscriptions.py` — отображение трафика

---

## Баг: кнопка Inbounds в меню сервера не работает

**Приоритет:** высокий

Кнопка "Inbounds" в меню сервера (admin) не открывает список inbound'ов.

---

## Баг: Unclosed client session (aiohttp)

**Приоритет:** высокий

```
Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x...>
```

Найти все места где создаются aiohttp-сессии и убедиться что они закрываются (context manager / `finally`).

---

## Баг: TelegramBadRequest — query is too old

**Приоритет:** высокий

```
aiogram.exceptions.TelegramBadRequest: Telegram server says - Bad Request: query is too old and response timeout expired or query ID is invalid
```

Лечится early `callback.answer()` + graceful обработка исключения при `edit_text`/`edit_reply_markup`.

---

## Баг: greenlet_spawn error при создании AWG/XUI клиентов

**Приоритет:** высокий

```
ERROR | app.services.notification_checker:_get_connection_traffic:434 - Error getting traffic for connection 194: greenlet_spawn has not been called; can't call await_only() here.
```

Ошибка возникает при создании AWG и XUI клиентов. Попытка выполнить async DB операцию в sync контексте. Проверить `_get_connection_traffic()` и все вызовы DB в процессе создания подключения.

---

## Фича: уведомления о нескольких протоколах

**Приоритет:** средний

Если у подписки несколько протоколов (XUI + AWG), уведомление клиента показывает только один. Нужно сообщать обо всех.

---

## Баг: QR-кнопка для vless ссылок бесполезна

**Приоритет:** средний

Кнопка "📱 QR" для vless/XUI ссылок отправляет ту же ссылку текстом. Заменить на кнопку "📋 Скопировать" или убрать.

---

## Баг: токен показывается для подписок без XUI

**Приоритет:** средний

AWG-подписка показывает "Токен: vs9KM7rOR9naZi_0" хотя у AWG нет подписочного URL. Токен показывается если хотя бы один connection в подписке XUI — нужно скрывать для чисто AWG/MTProxy подписок. Проверка: `has_xui` в `show_user_subscription_details()`.

---

## Баг: некорректная группировка подключений в подписке

**Приоритет:** средний

Подписка с 4 подключениями (2 XUI + 2 AWG) показывает некорректную группировку:
- XUI сгруппированы правильно (по URL)
- AWG подключения показаны под первым XUI URL вместо отдельной группы
- Два XUI на одном сервере разделены на разные группы

Нужно проверить логику `config_groups` — AWG должен быть отдельной группой с кнопками, XUI — с URL.

---

## Рефакторинг: поддержка domain для AWG Endpoint

**Приоритет:** низкий

`get_client_config()` использует `self.server.ip_address` для Endpoint. Поддерживает домены, но поле называется `ip_address`. Добавить отдельное поле `domain` в Server или в UI выбор IP/domain при настройке.

---

## Фича: автообновление Docker-образов

**Приоритет:** низкий

Раз в день проверять и обновлять Docker-образы на всех серверах (vpnbot-awg, vpnbot-xui, vpnbot-caddy и т.д.).

### Реализация

1. Background task в боте — раз в сутки обходит все серверы
2. SSH `docker pull <image>` → сравнить с текущим → `docker compose up -d` если обновился
3. Логировать результат, уведомлять админа при обновлении
4. Кнопка «Обновить образы» в меню сервера для ручного запуска

---

## Баг: sync_service пытается синхронизировать удалённые с панели inbound'ы

**Приоритет:** средний

```
ERROR | app.services.sync_service:sync_server:248 - [ERROR] Ошибка синхронизации клиентов для inbound 16: XUIError - Failed to get inbound: Obtain (record not found)
```

Inbound был удалён с 3x-ui панели через веб-интерфейс, но бот продолжает попытки синхронизации. Нужна обработка: при `record not found` — помечать inbound как `is_active=False` и уведомлять админа.
