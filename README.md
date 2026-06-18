# VPN Manager

Telegram-бот для управления VPN-подписками через **3x-ui**, **AmneziaWG** и **MTProxy** на нескольких серверах. Управление серверами идёт по SSH.

## Возможности

### Для администратора:
- 📋 Управление серверами по SSH: установка/подключение **3x-ui**, **AmneziaWG**, **MTProxy**
- 👥 Управление пользователями и их подписками
- 📝 Шаблоны подписок; автогенерация UUID/ключей/секретов, лимит трафика и срок действия
- 🔄 Фоновая синхронизация inbounds и автоотключение по истечении срока
- 📊 Экспорт базы данных

### Для пользователя:
- 📋 Просмотр своих подписок
- 🔗 Получение subscription URLs для импорта в VPN клиенты
- 📋 Копирование ссылок в буфер обмена

## Архитектура

```
Client (пользователь)
  └── Subscription (subscription_token, лимит трафика, срок) — может создаваться из шаблона
        └── InboundConnection (подключение на конкретном inbound: UUID/ключи/секрет по протоколу)

Server
  ├── XUIPanel / AWGService / MTProxyService (сервис протокола на сервере)
  └── Inbound (XUI / AWG / MTProxy)
        └── InboundConnection ←─── связь с подпиской
```

**Ключевая концепция**: у каждой `Subscription` свой `subscription_token`; подписка может иметь подключения (`InboundConnection`) на разных inbound'ах/серверах. Модели inbound'ов и подключений — полиморфные по протоколам (XUI / AWG / MTProxy).

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

Самый простой способ запустить на сервере.

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

- **Данные сохраняются** между перезапусками (БД и логи — в Docker-томах). Чтобы удалить всё вместе с данными: `docker compose down -v`.
- **Часовой пояс** в логах задаётся переменной `TZ` в `.env` (напр. `Europe/Moscow`).

## Использование

### Первый запуск

1. Запустите бота
2. Напишите `/start` в Telegram
3. Если ваш Telegram ID указан в `ADMIN_TELEGRAM_IDS`, вы автоматически станете администратором

### Добавление сервера

1. Меню администратора → управление серверами → добавить сервер (имя + IP).
2. Настроить SSH-доступ (пользователь, порт, пароль или ключ).
3. В меню сервиса установить или подключить нужный протокол (3x-ui / AmneziaWG / MTProxy).

### Создание подписки

1. Меню администратора → создать подписку.
2. Выберите пользователя.
3. Выберите сервер и inbound (или шаблон подписки).
4. Укажите лимит трафика и срок действия.

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
│   ├── logging_config.py    # Настройка логирования (loguru)
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
├── Dockerfile               # Docker-образ
├── docker-compose.yml       # Docker Compose
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
- **cryptography / bcrypt** - Шифрование секретов в БД (Fernet) и хеши паролей
- **asyncssh** - SSH-доступ к серверам (установка/управление протоколами)
- **qrcode / Pillow** - QR-коды подписок
- **loguru** - Логирование

## Требования к 3x-ui

- Версия 3x-ui с поддержкой API
- Включённая подписка (sub) функция на серверах
- Доступ к API панели по HTTPS

## Лицензия

MIT
