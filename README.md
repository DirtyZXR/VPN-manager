# VPN Manager

Telegram-бот для управления VPN подписками через несколько панелей 3x-ui на разных серверах.

## Возможности

### Для администратора:
- 📋 Управление серверами 3x-ui (добавление, редактирование, удаление)
- 👥 Управление пользователями
- 📝 Создание VPN подписок с автоматической генерацией UUID и email
- 🔄 Синхронизация inbounds с серверов
- 📊 Экспорт базы данных

### Для пользователя:
- 📋 Просмотр своих подписок
- 🔗 Получение subscription URLs для импорта в VPN клиенты
- 📋 Копирование ссылок в буфер обмена

## Архитектура

```
User (Пользователь)
  └── SubscriptionGroup (Группа подписок)
        └── ServerSubscription (Связь с сервером + subscription token)
              └── Profile (Конкретный профиль на inbound)
```

**Ключевая концепция**: Один subscription token на пару (группа + сервер).

## Установка

### 1. Клонирование

```bash
git clone <repository-url>
cd vpn-manager
```

### 2. Создание виртуального окружения

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# или
source .venv/bin/activate  # Linux/macOS
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка конфигурации

Скопируйте `.env.example` в `.env` и заполните параметры:

```bash
cp .env.example .env
```

Отредактируйте `.env`:

```env
# Telegram
BOT_TOKEN=your_bot_token_here

# Admin Telegram IDs (comma-separated)
ADMIN_TELEGRAM_IDS=123456789,987654321

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/vpn_manager.db

# Encryption key (generate with command below)
ENCRYPTION_KEY=your_fernet_key_here

# Logging
LOG_LEVEL=INFO
```

Генерация ключа шифрования:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 5. Создание директорий

```bash
mkdir data logs
```

## Запуск

```bash
python -m app.main
```

## Запуск в Docker

Самый простой способ для сервера — Docker Compose. Миграции применяются автоматически при старте контейнера, SQLite-БД и логи хранятся в именованных томах (переживают пересоздание контейнера).

### 1. Подготовка `.env`

```bash
cp .env.example .env
# заполнить BOT_TOKEN, ADMIN_TELEGRAM_IDS, ENCRYPTION_KEY (см. выше про генерацию ключа)
```

### 2. Сборка и запуск

```bash
docker compose build
docker compose up -d
```

Или через `make`:

```bash
make build && make up
make logs      # хвост логов
make ps        # статус
make down      # остановить
```

### Заметки

- **Тома:** `vpn_data` (БД `/app/data/vpn_manager.db`) и `vpn_logs` (`/app/logs`). Не удаляются при `docker compose down` (удалить вместе с данными — `docker compose down -v`).
- **Bind-mount вместо именованных томов** (если хочется видеть файлы на хосте, напр. `./data:/app/data`): контейнер работает под uid `10001`, поэтому хостовые каталоги нужно сделать записываемыми заранее — `mkdir -p data logs && sudo chown -R 10001:10001 data logs`, иначе миграции упадут при старте.
- **Миграции:** прогоняются в entrypoint (`alembic upgrade head`) при каждом старте, идемпотентно.
- **Часовой пояс:** задать `TZ` в `.env` (напр. `Europe/Moscow`) — влияет на метки времени в логах.
- **Образ** собирается без секретов: `.env`, `data/`, `logs/`, `tests/` исключены через `.dockerignore`; контейнер работает под непривилегированным пользователем.

## Использование

### Первый запуск

1. Запустите бота
2. Напишите `/start` в Telegram
3. Если ваш Telegram ID указан в `ADMIN_TELEGRAM_IDS`, вы автоматически станете администратором

### Добавление сервера

1. Меню администратора → ⚙️ Управление серверами
2. ➕ Добавить сервер
3. Введите название, URL панели, логин и пароль
4. После добавления синхронизируйте inbounds

### Создание подписки

1. Меню администратора → 📝 Создать подписку
2. Выберите пользователя
3. Выберите сервер
4. Выберите inbound
5. Выберите или создайте группу подписок
6. Укажите лимит трафика и срок действия

### Получение ссылок пользователем

1. /start → 📋 Мои подписки
2. 🔗 Все subscription URLs - получить все ссылки для импорта
3. Скопировать ссылки и вставить в VPN клиент (V2rayNG, Streisand, и т.д.)

## Структура проекта

```
vpn-manager/
├── app/
│   ├── main.py              # Точка входа
│   ├── config.py            # Конфигурация
│   ├── bot/                 # Telegram бот
│   │   ├── handlers/        # Обработчики команд
│   │   ├── keyboards/       # Клавиатуры
│   │   ├── middlewares/     # Middleware
│   │   ├── states/          # FSM состояния
│   │   └── filters/         # Фильтры
│   ├── database/            # База данных
│   │   └── models/          # SQLAlchemy модели
│   ├── services/            # Бизнес-логика
│   ├── xui_client/          # API клиент 3x-ui
│   └── utils/               # Утилиты
├── data/                    # SQLite база данных
├── logs/                    # Логи
├── .env                     # Конфигурация (не в git)
├── .env.example             # Пример конфигурации
├── requirements.txt         # Зависимости
└── pyproject.toml           # Метаданные проекта
```

## Технологии

- **Python 3.11+**
- **aiogram 3.x** - Telegram Bot Framework
- **SQLAlchemy 2.0** - ORM
- **SQLite + aiosqlite** - База данных
- **aiohttp** - HTTP клиент
- **pydantic-settings** - Конфигурация
- **cryptography** - Шифрование паролей
- **loguru** - Логирование

## Требования к 3x-ui

- Версия 3x-ui с поддержкой API
- Включённая подписка (sub) функция на серверах
- Доступ к API панели по HTTPS

## Лицензия

MIT
