.PHONY: up down logs build migrate revision shell-backend shell-db test lint format clean

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

migrate:
	docker compose exec backend alembic upgrade head

revision:
	@read -p "Migration message: " msg; \
	docker compose exec backend alembic revision --autogenerate -m "$$msg"

shell-backend:
	docker compose exec backend bash

shell-db:
	docker compose exec db psql -U docstore -d docstore

test:
	docker compose exec backend pytest

lint:
	cd backend && ruff check . && mypy app/
	cd frontend && npm run lint

format:
	cd backend && black . && ruff format .
	cd frontend && npm run format

clean:
	docker compose down -v
