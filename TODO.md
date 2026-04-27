# TODO

## Баг: sync_service ломается на AWGInbound/MTProxyInbound — нет xui_id

**Приоритет:** высокий
**Файл:** `app/services/sync_service.py:247`

### Ошибки

```
AttributeError: 'MTProxyInbound' object has no attribute 'xui_id'
AttributeError: 'AWGInbound' object has no attribute 'xui_id'
XUIError: Failed to get inbound: Obtain (record not found)
```

### Суть

Синхронизация клиентов перебирает **все** inbound'ы сервера, включая MTProxy и AWG. Эти модели не имеют `xui_id`. Попытка обратиться к `xui_id` вызывает `AttributeError`, XUI API возвращает 404.

### Фикс

В `sync_service.sync_server()` фильтровать inbound'ы по типу — синхронизировать только XUI-inbound'ы (модель `Inbound` с `xui_id`), пропускать `MTProxyInbound` и `AWGInbound`. Либо фильтровать query: `select(Inbound).where(Inbound.xui_id.isnot(None))`.

---

## Баг: сгенерированный пароль XUI не работает

**Приоритет:** высокий

### Суть

При подключении существующей 3x-ui с генерацией нового пароля — пароль не подходит для входа в панель. SQL с bcrypt-хешем передаётся через stdin (`input_data=`), но результат в 3x-ui DB не соответствует ожидаемому. Нужно проверить: фактически ли хеш записывается корректно, перезапускается ли контейнер, и совпадает ли bcrypt rounds с тем что ожидает 3x-ui.

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

## Инсталлеры: progress bar при установке

**Приоритет:** низкий

### Суть

Установка сервисов занимает 1-3 минуты. Сейчас показывается статичное сообщение «Установка...». Нужно пошагово обновлять сообщение в Telegram по мере выполнения шагов.

### Что нужно

1. В `BaseInstaller` добавить `_progress(step, total, text)` callback
2. Инсталлеры вызывают `self._progress()` на каждом шаге (prepare_host, compose, configure, verify)
3. Handler передаёт callback при создании инсталлера, который делает `msg.edit_text()`
4. Обновлять не чаще 1 раза в секунду (rate limit Telegram)

### Пример

```
⏳ [3/6] Запись docker-compose.yml...
```

---

## Инсталлеры: автопоиск сервисов на сервере

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

