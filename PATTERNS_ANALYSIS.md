# VPN Manager - Основные паттерны и архитектура

## Обзор архитектуры

Проект представляет собой Telegram бота для управления VPN подписками через несколько 3x-ui панелей на разных серверах.

**Технологический стек:**
- Python 3.11+ с asyncio
- aiogram 3.x - Telegram Bot Framework с FSM
- SQLAlchemy 2.0 - Async ORM с aiosqlite
- aiohttp - HTTP клиент для 3x-ui API
- pydantic-settings - Конфигурация из .env
- cryptography (Fernet) - Шифрование паролей
- loguru - Структурированное логирование

## Иерархия данных

```
Client (реальный пользователь с Telegram)
└── Subscription (группа подписок, логическая группировка)
    └── InboundConnection (конкретное подключение к inbound)
        └── Inbound (кешированная конфигурация из 3x-ui)
            └── Server (конфигурация панели 3x-ui)
```

**Ключевая концепция:** Токен подписки привязан к паре (Subscription, Server). При добавлении нового профиля к существующей паре группа-сервер следует использовать существующую Subscription и её токен.

## Паттерны работы с подписками

### Создание подписки

**Процесс:**
1. Администратор выбирает клиента → сервер → inbound
2. Если Subscription уже существует для (client, server), используется существующая
3. Генерируется уникальный токен подписки: `generate_subscription_token()`
4. Для каждого inbound генерируется уникальный email: `_generate_unique_email()`
5. Создаётся клиент в XUI панели с UUID и email
6. Создаётся запись InboundConnection с inbound и subscription foreign keys

**URL подписки:** `https://{host}/{urlsub}/{token}`

**Поддержка форматов:**
- Обычный URL: `https://{host}/{urlsub}/{token}`
- JSON URL: `https://{host}/{urlsubjson}/{token}`

### Управление подключениями

**Независимость подключений:** Каждое InboundConnection может иметь свои собственные лимиты трафика и даты истечения.

**Операции:**
- `toggle_inbound_connection()` - включение/выключение подключения
- `toggle_client_all_connections()` - массовое переключение всех подключений клиента
- Bulk operations - массовые операции enable/disable для нескольких inbounds

## Работа с серверами и 3x-ui

### XUI Клиент

**Архитектура:**
- Использует `aiohttp.ClientSession` для HTTP соединений
- Реализует паттерн async context manager (`__aenter__`/`__aexit__`)
- Управление сессионными куками с поддержкой персистентности

**Аутентификация:**
- Эндпоинт: `POST /login` с username/password
- Сессионные куки сохраняются и переиспользуются
- Метод `_test_session()` валидирует сохранённые куки перед полной аутентификацией
- Пароли шифруются через Fernet

**SSL конфигурация:**
- Гибкая настройка верификации SSL (можно отключить для разработки)
- Контекст SSL с обратной совместимостью для OpenSSL 3.0
- Комплексный набор шифров с fallback механизмами

### API Эндпоинты XUI

**Управление inbounds:**
- `GET /panel/api/inbounds/list` - список всех inbounds
- `GET /panel/api/inbounds/get/{id}` - конкретный inbound
- `GET /panel/api/inbounds/getClientTraffics/{id}` - трафик клиентов

**Управление клиентами:**
- `POST /panel/api/inbounds/addClient` - добавить клиента
- `POST /panel/api/inbounds/updateClient/{id}` - обновить клиента
- `POST /panel/api/inbounds/{id}/delClient/{uuid}` - удалить клиента
- `POST /panel/api/inbounds/{id}/resetClientTraffic/{email}` - сбросить трафик

## Кеширование и синхронизация

### Многоуровневое кеширование

**Service-level кеширование XUI клиентов:**
```python
class XUIService:
    self._clients: dict[int, XUIClient] = {}

class NewSubscriptionService:
    self._xui_clients: dict[int, XUIClient] = {}
```

**Стратегия ключа:** Используется ID сервера как ключ кеша для быстрого поиска.

**Переиспользование сессий:**
```python
async def _get_client(self, server: Server) -> XUIClient:
    if server.id in self._clients:
        client = self._clients[server.id]
        # Проверка активности сессии
        if client._session and not client._session.closed:
            return client
        # Удаление устаревшего клиента и создание нового
        del self._clients[server.id]
```

**Сохранение кук:** Зашифрованные сессионные куки сохраняются в базу данных и переиспользуются.

### База данных как кеш

**Inbound конфигурации:** Кешируются в базе данных для избежания повторных API вызовов.

**Счётчик клиентов:** База данных отслеживает количество клиентов на каждый inbound.

### Синхронизация

**Фоновая синхронизация:**
```python
class SyncService:
    SYNC_INTERVAL = timedelta(minutes=5)

    async def start_background_sync(self) -> None:
        while self._is_running:
            await self._sync_cycle()
            await asyncio.sleep(self.SYNC_INTERVAL.total_seconds())
```

**Lock-based контроль параллелизма:**
```python
self._sync_lock = asyncio.Lock()  # Предотвращает параллельные синхронизации
async with self._sync_lock:
    # Логика синхронизации
```

**Трёхфазная синхронизация:**
1. Синхронизация Server/Inbound
2. Синхронизация Client (трафик/использование)
3. Проверка целостности

**Умная стратегия синхронизации:**
```python
def _needs_sync(self, model: object) -> bool:
    if model.sync_status in ["offline", "error"]:
        return True
    if model.last_sync_at is None:
        return True
    if datetime.now(timezone.utc) - model.last_sync_at > self.SYNC_INTERVAL:
        return True
    return False
```

## База данных

### Модели и связи

**Базовые миксины:**
- `TimestampMixin` - отслеживание created_at, updated_at
- `SyncMixin` - отслеживание sync_status, last_sync_at, sync_error

**Ключевые модели:**

1. **Client** - реальные пользователи
   - `telegram_id`, `telegram_username`, `email`, `name`
   - `is_admin`, `is_active`

2. **Server** - конфигурации панелей 3x-ui
   - `url`, `username`, `password_encrypted`
   - `verify_ssl`, `session_cookies_encrypted`

3. **Inbound** - кешированные конфигурации inbound
   - `xui_id`, `remark`, `protocol`, `port`
   - `settings_json`, `client_count`

4. **Subscription** - группы подписок клиентов
   - `subscription_token`, `total_gb`, `expiry_date`
   - Связи с Client и InboundConnection

5. **InboundConnection** - конкретные подключения
   - `xui_client_id`, `email`, `uuid`
   - Уникальное ограничение на (`subscription_id`, `inbound_id`)

### Связи и каскады

**Foreign Key связи:**
- Server → Inbound: один-ко-многим с cascade delete
- Client → Subscription: один-ко-многим с cascade delete
- Subscription → InboundConnection: один-ко-многим с cascade delete
- Inbound → InboundConnection: один-ко-многим с cascade delete

**Cascade поведение:** Все отношения используют `cascade="all, delete-orphan"`

### Eager Loading паттерны

**Использование selectinload():**
```python
result = await session.execute(
    select(Subscription)
    .where(Subscription.id == subscription_id)
    .options(
        selectinload(Subscription.client),
        selectinload(Subscription.inbound_connections)
    )
)
```

**Преимущества:**
- Полностью устраняет N+1 запросы
- Предоставляет полные данные о связях в одном запросе
- Эффективная загрузка для сложных вложенных структур

## Транзакции и работа с базой данных

### Flush vs Commit паттерны

**Services используют `flush()` для немедленной генерации ID:**
```python
# В создании подписки
self.session.add(subscription)
await self.session.flush()  # Немедленная генерация ID
return await self.get_subscription(subscription.id)  # Перезагрузка со связями
```

**Handlers используют `commit()` для контроля транзакций:**
```python
# В handlers бота (управление границами транзакций)
await session.commit()  # Финальный коммит транзакций
```

**Граница транзакций:** Services обрабатывают бизнес-логику, а handlers управляют границами транзакций.

## Обработка ошибок

### Иерархия исключений

```python
class XUIError(Exception):          # Базовое исключение
class XUIAuthError(XUIError)       # Ошибки аутентификации (HTTP 401)
class XUIConnectionError(XUIError) # Проблемы с соединением
class XUINotFoundError(XUIError)   # Ресурс не найден (HTTP 404)
class XUIValidationError(XUIError) # Ошибки валидации
class XUIClientError(XUIError)     # Ошибки клиентов
```

**Стратегия обработки:**
- Автоматическое обновление сессионных кук при 401 ошибках
- Graceful fallback от сохранённых кук к новой аутентификации
- Комплексная цепочка исключений с оригинальным контекстом

## Архитектура бота

### FSM состояния

**Admin States:**
- `ServerManagement` - управление серверами
- `UserManagement` - управление пользователями
- `ClientManagement` - управление клиентами
- `SubscriptionManagement` - управление подписками
- `ExportData` - экспорт данных

**User States:**
- `UserSubscription` - просмотр подписок пользователей

### Middleware и аутентификация

**AuthMiddleware паттерн:**
```python
async def __call__(self, handler, event, data):
    tg_user = data.get("event_from_user")

    # Проверка статуса админа из конфига
    is_admin = settings.is_admin(tg_user.id)

    # Авто-создание админов
    if not client and is_admin:
        client = await client_service.create_client(
            name=tg_user.full_name,
            telegram_id=tg_user.id,
            is_admin=True,
        )

    # Обновление данных с информацией об аутентификации
    data.update({
        "client": client,
        "is_admin": is_admin,
    })
```

### Клавиатуры и навигация

**Иерархия клавиатур:**
1. Главное меню - динамический админ/пользовательский вид
2. Списки сущностей - для серверов, клиентов, inbounds
3. Меню действий - контекстно-зависимые
4. Подтверждения - для деструктивных действий
5. Навигация - последовательная навигация "назад"

**Консистентность паттернов:**
- Все клавиатуры используют `InlineKeyboardBuilder`
- Последовательный текст кнопок (статус + имя + действие)
- Callback данные следуют паттерну `action_entity_id`

## Управление трафиком

**Модели трафика:**
```python
class XUIClient:
    total_gb: int = 0          # Лимит трафика в байтах (0 = безлимит)
    expiry_time: int = 0       # Время истечения в ms (0 = никогда)
```

**Статистика трафика:**
- `up`/`down` байты для текущего использования
- `totalGB` для лимитов трафика
- `expiryTime` для временных меток истечения
- `enable` статус для активации клиента

**Конвертация:** Автоматическая конвертация байтов в GB в сервисном слое.

## Генерация уникальных идентификаторов

**UUID:** `generate_uuid()` - генерация UUID для XUI клиентов
**Email:** `generate_email()` - генерация email для XUI клиентов
**Токен:** `generate_subscription_token()` - уникальный токен для подписки

**Стратегия уникальности email:**
```python
async def _generate_unique_email(self, inbound_id: int, base_email: str) -> str:
    # Обеспечивает уникальность email на inbound с генерацией суффиксов
```

## Поиск и фильтрация

**Умная обработка текста:**
```python
def _normalize_search_query(query: str, is_email: bool = False) -> str:
    # Удаляет знаки препинания, сохраняет @ и . для emails
```

**Поддержка многословного поиска:**
```python
# Поддерживает "John Doe" для совпадения любого слова в имени
name_conditions = []
for word in name_words:
    name_conditions.append(text("LOWER(clients.name) LIKE LOWER(:name)").params(name=f"%{word}%"))
```

## Управление сессиями

**Graceful cleanup:**
```python
async def close_all_clients(self) -> None:
    for client_id in list(self._clients.keys()):
        try:
            if client._session and not client._session.closed:
                await client.close()
        finally:
            self._clients.pop(client_id, None)
```

**Auto-registration:** Автоматическая регистрация пользователей из Telegram
**Admin detection:** Проверка статуса админа из конфигурации

## URL генерация

**Регулярный URL:**
```python
url = urljoin(server.url, f"{subscription_path}{subscription_token}")
```

**JSON URL:**
```python
json_url = urljoin(server.url, f"{subscription_json_path}{subscription_token}")
```

**Поддержка путей:** Настройка путей через конфигурацию сервера (`subscription_path`, `subscription_json_path`, `panel_path`)

## Шифрование

**Service-level шифрование:**
```python
class XUIService:
    def __init__(self, session: AsyncSession):
        self._cipher = Fernet(settings.encryption_key.encode())

    def _encrypt_password(self, password: str) -> str:
        return self._cipher.encrypt(password.encode()).decode()

    def _decrypt_password(self, encrypted: str) -> str:
        return self._cipher.decrypt(encrypted.encode()).decode()
```

**Хранение:** Зашифрованные пароли и сессионные куки хранятся в базе данных

## Конфигурация

**Загрузка:** Из `.env` через `app/config.py`

**Обязательные поля:**
- `BOT_TOKEN` - токен Telegram бота
- `ADMIN_TELEGRAM_IDS` - список админских Telegram IDs
- `DATABASE_URL` - строка подключения SQLite
- `ENCRYPTION_KEY` - ключ Fernet для шифрования
- `LOG_LEVEL` - уровень логирования (по умолчанию: INFO)
- `XUI_TIMEOUT` - таймаут XUI клиента в секундах (по умолчанию: 30)

## Архитектурные сильные стороны

1. **Разделение ответственности:** Чёткое разделение между доступом к данным, бизнес-логикой и интеграцией с внешними API
2. **Стратегия кеширования:** Многоуровневое кеширование уменьшает API вызовы и улучшает производительность
3. **Управление транзакциями:** Правильное разделение flush/commit для немедленной генерации ID vs финального контроля транзакций
4. **Устойчивость к ошибкам:** Комплексная обработка ошибок с иерархией кастомных исключений
5. **Фоновая обработка:** Автоматическая синхронизация с надлежащим контролем параллелизма
6. **Консистентность данных:** Проверки целостности и graceful degradation паттерны
7. **Масштабируемость:** Service-based архитектура позволяет независимое масштабирование и тестирование

## Важные паттерны для будущих сессий

1. **Всегда используйте `selectinload()`** для вложенных отношений для предотвращения N+1 запросов
2. **XUI клиенты должны кешироваться на уровне сервиса**, не создаваться для каждого запроса
3. **Services используют `flush()` для немедленного получения ID**, handlers используют `commit()` для контроля транзакций
4. **Всегда используйте async context managers** для сессий базы данных и XUI клиентов
5. **Обработка ошибок должна использовать кастомные исключения** из `app/xui_client/exceptions.py`
6. **Токены подписок должны быть уникальными** для каждой (client, server) пары
7. **Всегда предоставляйте обработчики отмены** для многошаговых диалогов
8. **Cascade delete настроены** для сиротских записей - следите за побочными эффектами
9. **Пароли серверов зашифрованы** через Fernet - должны быть дешифрованы перед созданием XUI клиентов
10. **Inbound настройки кешируются** в базе данных - обновляйте при изменениях в XUI
