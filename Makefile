.PHONY: up down logs build migrate revision shell-backend shell-db test ensure-test-db lint format clean

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

test: ensure-test-db
	docker compose exec backend pytest

# Idempotent: creates docstore_test if missing, then applies migrations
# against it. Keeps the dev DB untouched.
ensure-test-db:
	@docker compose exec -T db psql -U docstore -d postgres -tAc \
	  "SELECT 1 FROM pg_database WHERE datname='docstore_test'" | grep -q 1 \
	  || docker compose exec -T db psql -U docstore -d postgres -c \
	  "CREATE DATABASE docstore_test OWNER docstore"
	docker compose exec -T -e DATABASE_URL=postgresql+psycopg://docstore:docstore@db:5432/docstore_test backend alembic upgrade head

lint:
	cd backend && ruff check . && mypy app/
	cd frontend && npm run lint

format:
	cd backend && black . && ruff format .
	cd frontend && npm run format

clean:
	docker compose down -v
