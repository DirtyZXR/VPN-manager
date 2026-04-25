# TODO

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

