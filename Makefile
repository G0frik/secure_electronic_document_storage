.PHONY: up down logs build migrate revision shell-backend shell-db test coverage seed-dev seed-demo ensure-test-db lint format clean certs

certs: docker/nginx/certs/selfsigned.key

docker/nginx/certs/selfsigned.key:
	docker run --rm -v "$(shell cd)\\docker\\nginx\\certs:/certs" alpine sh -c "\
		apk add --no-cache openssl > /dev/null 2>&1; \
		openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
		-keyout /certs/selfsigned.key -out /certs/selfsigned.crt \
		-subj '/CN=localhost/O=DocStore-Dev' \
		-addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'"

up: certs
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

# Phase 16 — same as test, with branch coverage + terminal report.
# CI uploads coverage.xml as an artifact; locally just inspect stdout.
coverage: ensure-test-db
	docker compose exec backend pytest --cov=app --cov-report=term-missing --cov-report=xml

# Phase 1 — idempotent dev user/department seed.
seed-dev:
	docker compose exec backend flask seed-dev

# Phase 16 — richer demo seed (users + files + folders + shares + link + override).
# Requires `make seed-dev` to have run at least once.
seed-demo:
	docker compose exec backend flask seed-demo

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
