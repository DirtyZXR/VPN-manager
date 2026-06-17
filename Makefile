.PHONY: build up down restart logs ps migrate shell

build:        ## Собрать образ
	docker compose build

up:           ## Запустить в фоне
	docker compose up -d

down:         ## Остановить и удалить контейнер
	docker compose down

restart:      ## Перезапустить
	docker compose restart

logs:         ## Хвост логов
	docker compose logs -f --tail=200

ps:           ## Статус
	docker compose ps

migrate:      ## Применить миграции вручную
	docker compose run --rm bot alembic upgrade head

shell:        ## Шелл внутри контейнера
	docker compose exec bot sh
