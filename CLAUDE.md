# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the bot
```bash
python -m app.main
```

### Setting up the environment
```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies for testing/linting
pip install -e ".[dev]"

# Create necessary directories
mkdir data logs

# Copy and configure environment
cp .env.example .env
# Edit .env with your values
```

### Generating encryption key
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Code quality (dev dependencies)
```bash
# Linting
ruff check .

# Type checking
mypy app/

# Testing
pytest
pytest -v  # verbose
pytest tests/test_utils.py  # specific file
pytest tests/test_utils.py::test_generate_uuid  # specific test
pytest --cov=app --cov-report=html  # coverage
```

### Database migrations (Alembic)
```bash
# Initialize Alembic (first time only)
alembic init alembic

# Create migration after model changes
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1

# View migration history
alembic history
```

## Architecture Overview

This is a Telegram bot for managing VPN subscriptions through multiple 3x-ui panels across different servers.

### Technology Stack
- **Python 3.11+** with asyncio throughout
- **aiogram 3.x** - Telegram Bot Framework with FSM (Finite State Machine) for dialog flows
- **SQLAlchemy 2.0** - Async ORM with aiosqlite driver
- **aiohttp** - HTTP client for 3x-ui panel API
- **pydantic-settings** - Configuration management from .env
- **cryptography (Fernet)** - Password encryption for server credentials
- **loguru** - Structured logging

### Key Concept: Subscription Model

The subscription model hierarchy is:
```
User (real person)
  └── SubscriptionGroup (logical grouping, e.g., "Main", "Work")
        └── ServerSubscription (1 group + 1 server = 1 subscription_token)
              └── Profile (specific VPN profile on a specific inbound)
```

**Critical**: Subscription token is tied to the (SubscriptionGroup + Server) pair. When adding a new profile to an existing group/server combination, reuse the existing ServerSubscription and its token.

### Project Structure

```
app/
├── main.py                    # Entry point, bot initialization
├── config.py                  # pydantic-settings, loads from .env
├── bot/
│   ├── router.py              # Main router including all handlers
│   ├── middlewares/auth.py    # Auto-registers users, checks admin status
│   ├── filters/admin.py       # Admin-only filter
│   ├── handlers/
│   │   ├── common.py          # /start, /help, cancellation
│   │   ├── admin/             # Server/user/subscription management
│   │   └── user/subscriptions.py  # User view of subscriptions
│   ├── states/                # FSM states (admin.py, user.py)
│   └── keyboards/inline.py    # Inline keyboards
├── database/
│   ├── models/                # SQLAlchemy models
│   │   ├── base.py            # Base class + TimestampMixin
│   │   ├── server.py          # 3x-ui panel info (encrypted password)
│   │   ├── inbound.py         # Cached inbound configs
│   │   ├── user.py            # Real users
│   │   ├── subscription_group.py  # User's subscription groups
│   │   ├── server_subscription.py # Group+Server with token
│   │   └── profile.py         # Actual VPN profiles
│   └── __init__.py            # init_db(), async_session_factory
├── services/
│   ├── user_service.py        # User CRUD
│   ├── subscription_service.py # Subscription management + XUI integration
│   └── xui_service.py         # Server management + inbound sync
├── xui_client/
│   ├── client.py              # HTTP client for 3x-ui API
│   ├── models.py              # Pydantic models for API requests/responses
│   └── exceptions.py          # Custom exceptions
└── utils/
    └── __init__.py            # generate_uuid(), generate_email(), generate_subscription_token()
```

### Database Layer

All models inherit from `Base` and use `TimestampMixin` for `created_at`. Use `selectinload()` for eager loading relationships to avoid N+1 queries. Database operations in services should use `flush()` within transactions and let handlers call `commit()`.

**Key patterns:**
- Use `selectinload()` for nested relationships: `selectinload(User.subscription_groups).selectinload(SubscriptionGroup.server_subscriptions)`
- Services use `flush()` for immediate ID generation, handlers use `commit()` for transaction control
- Cascade deletes are configured for orphaned records

### XUI Client

The `XUIClient` in `app/xui_client/client.py` handles communication with 3x-ui panels:
- Sessions are managed via context manager (`async with`)
- Authentication: POST /login stores session cookies
- Key endpoints: inbounds list, add/update/delete clients, get traffic
- Use `XUIService` (in `app/services/xui_service.py`) to get cached clients with decrypted passwords

**Important:** XUI clients should be cached at service level (see `SubscriptionService._xui_clients`), not created per request.

### Bot Architecture

- **Middleware**: `AuthMiddleware` auto-registers users from Telegram and checks admin status
- **Handlers**: Organized by feature (admin vs user), use FSM states for multi-step dialogs
- **Services**: Business logic layer, orchestrates between database and XUI clients
- **Router**: Main router in `app/bot/router.py` includes all sub-routers
- **Filters**: `IsAdmin` filter in `app/bot/filters/admin.py` for admin-only handlers

**State Management:**
- FSM states are defined in `app/bot/states/admin.py` and `app/bot/states/user.py`
- Use state groups to organize related flows (e.g., server creation, subscription creation)
- Always provide cancellation handlers for multi-step dialogs

### Configuration

Settings are loaded from `.env` via `app/config.py`. Required fields:
- `BOT_TOKEN` - Telegram bot token
- `ADMIN_TELEGRAM_IDS` - Comma-separated admin Telegram IDs
- `DATABASE_URL` - SQLite connection string
- `ENCRYPTION_KEY` - Fernet key for encrypting server passwords
- `LOG_LEVEL` - Logging level (default: INFO)
- `XUI_TIMEOUT` - XUI client timeout in seconds (default: 30)

### Data Flow Examples

**Creating a subscription**:
1. Admin selects user → server → inbound → (existing/new) group
2. If group+server exists, get ServerSubscription, else create with new token
3. Generate UUID, email, create client in XUI panel
4. Create Profile record with inbound/server_subscription foreign keys

**User getting subscription URLs**:
1. User's SubscriptionGroups are loaded with eager loading of server_subscriptions
2. For each ServerSubscription, build URL: `https://{host}/sub/{token}`
3. Display grouped by subscription group name

### Important Notes

- Server passwords are encrypted using Fernet, must be decrypted before creating XUI clients
- Inbound settings are cached in database to avoid repeated API calls
- Use `selectinload()` for nested relationships to prevent N+1 queries
- FSM states are in `app/bot/states/` - maintain state diagrams when modifying flows
- XUI clients should be cached at service level, not created per request
- Subscription tokens should be unique per (group, server) pair
- Always use async context managers for database sessions and XUI clients
- Error handling should use custom exceptions from `app/xui_client/exceptions.py`

### Testing

Tests use pytest with pytest-asyncio. Key fixtures in `tests/conftest.py`:
- `test_session`: Async database session with in-memory SQLite
- `mock_settings`: Mocked configuration object
- `event_loop`: Async event loop for tests

**Test patterns:**
- Services are tested with mock database sessions
- Use `@pytest.mark.asyncio` for async tests
- Database models are tested with `test_session` fixture
- Avoid integration tests that require actual 3x-ui panels