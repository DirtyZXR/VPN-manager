# Миграции базы данных

В этом проекте используется [Alembic](https://alembic.sqlalchemy.org/) для миграций базы данных.

## Настройка

После клонирования репозитория инициализируйте Alembic:

```bash
alembic init alembic
```

Эта команда создаст следующую структуру:
```
alembic/
├── env.py              # Окружение миграций
├── script.py.mako      # Шаблон для миграций
├── versions/           # Файлы миграций
└── README
```

Файл `alembic.ini` будет создан в корне проекта.

## Выполнение миграций

### Создание новой миграции

После изменения моделей создайте новую миграцию:

```bash
alembic revision --autogenerate -m "Описание изменений"
```

Это создаст новый файл миграции в `alembic/versions/`.

### Применение миграций

Примените ожидающие миграции к базе данных:

```bash
alembic upgrade head
```

### Откат миграций

Откат к предыдущей миграции:

```bash
alembic downgrade -1
```

Откат к конкретной миграции:

```bash
alembic downgrade <revision_id>
```

### Просмотр истории миграций

```bash
alembic history
```

### Просмотр текущей ревизии

```bash
alembic current
```

## Офлайн режим

Для генерации SQL без подключения к базе данных:

```bash
alembic upgrade head --sql
```

## Важные заметки

1. **Всегда проверяйте сгенерированные миграции** - `--autogenerate` полезен, но не идеален
2. **Тестируйте миграции** перед применением в продакшене
3. **Делайте резервную копию базы данных** перед запуском миграций
4. **Коммитьте файлы миграций** вместе с изменениями моделей

## Пример ручной миграции

Если autogenerate работает некорректно, создайте ручную миграцию:

```python
"""Добавление новой колонки в таблицу users.

Revision ID: 001
Revises:
Create Date: 2024-01-01 12:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('new_field', sa.String(100)))


def downgrade() -> None:
    op.drop_column('users', 'new_field')
```
