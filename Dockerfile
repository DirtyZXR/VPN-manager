# syntax=docker/dockerfile:1

# --- Стадия сборки зависимостей (изолированный venv) ---
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt

# --- Финальный образ ---
FROM python:3.11-slim AS final

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# tzdata — чтобы метки времени в логах учитывали зону из переменной TZ
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь (контейнер ходит по SSH наружу — root не нужен)
RUN useradd --create-home --uid 10001 app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
# content/ — рантайм-ассеты (YAML-инструкции + картинки для пользовательского меню)
COPY content ./content
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /app/data /app/logs \
    && chown -R app:app /app

USER app

# Тома: SQLite-БД и логи переживают пересоздание контейнера
VOLUME ["/app/data", "/app/logs"]

# entrypoint прогоняет миграции, затем exec'ает CMD (сигналы доходят до Python)
ENTRYPOINT ["entrypoint.sh"]
CMD ["python", "-m", "app.main"]
