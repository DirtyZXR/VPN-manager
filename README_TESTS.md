# Руководство по тестированию

В этом проекте используются [pytest](https://docs.pytest.org/) и [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) для тестирования.

## Настройка

Установите зависимости для тестирования:

```bash
pip install -e ".[dev]"
```

## Запуск тестов

Запуск всех тестов:

```bash
pytest
```

Запуск с подробным выводом:

```bash
pytest -v
```

Запуск конкретного файла тестов:

```bash
pytest tests/test_utils.py
```

Запуск конкретного теста:

```bash
pytest tests/test_utils.py::test_generate_uuid
```

Запуск с покрытием кода:

```bash
pytest --cov=app --cov-report=html
```

## Структура тестов

```
tests/
├── conftest.py           # Конфигурация и фикстуры pytest
├── test_config.py         # Тесты конфигурации
├── test_utils.py          # Тесты утилит
├── test_services.py        # Тесты слоя сервисов
└── test_models.py         # Тесты моделей базы данных
```

## Фикстуры

Файл `conftest.py` предоставляет следующие фикстуры:

- `test_engine`: Движок базы данных в памяти
- `test_session`: Асинхронная сессия базы данных
- `mock_settings`: Мок объекта настроек
- `event_loop`: Асинхронный цикл событий для тестов

## Написание тестов

### Пример теста для утилит:

```python
def test_generate_uuid():
    """Проверка генерации UUID."""
    from app.utils import generate_uuid

    uuid = generate_uuid()

    assert isinstance(uuid, str)
    assert len(uuid) == 36
```

### Пример асинхронного теста для сервисов:

```python
import pytest

@pytest.mark.asyncio
async def test_user_service_create_user(test_session):
    """Проверка создания пользователя."""
    from app.services import UserService

    service = UserService(test_session)

    user = await service.create_user(
        name="Test User",
        telegram_id=123456,
    )

    assert user.id is not None
    assert user.name == "Test User"
```

## CI/CD

Тесты должны запускаться автоматически при push/PR. Добавьте это в ваш `.github/workflows/test.yml`:

```yaml
name: Тесты

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - run: pip install -e ".[dev]"
      - run: pytest
```

## Цели покрытия кода

- Стремитесь к покрытию >80% кода
- Фокусируйтесь на критических путях (services, utils)
- Обработчики UI/бота имеют меньший приоритет, но должны тестироваться
