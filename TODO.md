# TODO

## Баг: sync_service ломается на MTProxyInbound — нет атрибута xui_id

**Приоритет:** высокий
**Файл:** `app/services/sync_service.py:247`

### Ошибка

```
AttributeError: 'MTProxyInbound' object has no attribute 'xui_id'
XUIError: Failed to get inbound: Obtain (record not found)
```

### Суть

Синхронизация клиентов перебирает **все** inbound'ы сервера, включая MTProxy и AWG. Эти модели не имеют `xui_id` и не являются XUI-inbound'ами. Попытка обратиться к `xui_id` вызывает `AttributeError`, а затем XUI API возвращает «record not found» для несуществующего inbound.

### Фикс

В `sync_service.sync_server()` фильтровать inbound'ы по типу — синхронизировать только XUI-inbound'ы (модель `Inbound` с `xui_id`), пропускать `MTProxyInbound` и `AWGInbound`.

---

## Баг: sync_service пытается получить inbound по xui_id для не-XUI записей

**Приоритет:** высокий
**Файл:** `app/services/sync_service.py:247`

### Ошибка

```
XUIError - Failed to get inbound: Obtain (record not found)
```

### Суть

Inbound ID 17 в БД — это MTProxyInbound/AWGInbound, у него нет `xui_id` (или он None). Синхронизация пытается получить его из XUI панели и получает 404.

### Фикс

Добавить `isinstance` или `hasattr` проверку перед обращением к `xui_id`, либо фильтровать query на уровне SQLAlchemy (`select(Inbound).where(Inbound.xui_id.isnot(None))`).

---

## Инсталлеры: предпроверка «уже установлен» ДО мастера установки ✅ DONE

**Приоритет:** высокий

### Суть

Сейчас `check_already_installed()` вызывается внутри `install()` — пользователь проходит весь мастер (домен, порт, пути, логин, пароль) и только в конце узнаёт что сервис уже стоит. Трата времени.

### Правильный подход ✅ РЕАЛИЗОВАНО

1. При нажатии «Установить [сервис]» → сразу SSH-проверка `docker ps | grep vpnbot-xui`
2. Если контейнер есть → показать inline-кнопки:
   - **«Переустановить»** — пойти в мастер установки с `force=True`
   - **«Отмена»**
3. Если контейнера нет → обычный мастер установки

### Применимо ко всем трём инсталлерам

- XUI: `vpnbot-xui` / `vpnbot-caddy`
- AWG: `vpnbot-awg`
- MTProxy: `vpnbot-mtproxy`

---

## Инсталлеры: автопоиск сервисов на сервере

**Приоритет:** средний

### Суть

При добавлении сервера бот должен автоматически находить уже установленные VPN-сервисы (3x-ui, AWG, MTProxy) и предлагать подключить их. Сейчас автопоиск находит только MTProxy.

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

