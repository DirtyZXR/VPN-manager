#!/bin/sh
# Точка входа контейнера: миграции БД, затем запуск приложения.
set -e

echo "[entrypoint] Применение миграций Alembic..."
alembic upgrade head

echo "[entrypoint] Запуск приложения..."
exec "$@"
