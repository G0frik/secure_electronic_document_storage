# Secure Document Storage

A document classification and access control system. Documents are auto-classified by sensitivity tier; the tier enforces RBAC at every access point.

See [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md) for the 17-phase build plan and [`wiki_notes/Home.md`](wiki_notes/Home.md) for the project wiki.

---

## Quick Start (Phase 0)

```bash
# 1. Copy env template
cp .env.example .env

# 2. Build and start the stack
docker compose up --build

# 3. Verify health
curl http://localhost:8000/healthz
# → {"status":"ok"}

# 4. Open the frontend
# http://localhost:5173
```

## Service URLs

| Service | URL |
|---|---|
| Backend API | http://localhost:8000 |
| Frontend (Vite dev) | http://localhost:5173 |
| MinIO Console | http://localhost:9001 (minioadmin / minioadmin) |
| Mailhog UI | http://localhost:8025 |
| PostgreSQL | localhost:5432 (docstore / docstore) |
| Redis | localhost:6379 |

## Common Commands

```bash
make up              # Start stack
make down            # Stop stack
make logs            # Tail logs
make migrate         # Apply Alembic migrations
make revision        # Create a new migration (prompts for message)
make shell-backend   # Bash inside the backend container
make shell-db        # psql inside the db container
make test            # Run pytest
make lint            # Lint backend + frontend
make format          # Format backend + frontend
make clean           # Stop stack and remove volumes
```

## Project Structure

```
secure_document_storage/
├── backend/                 # Flask + SQLAlchemy + Celery
│   ├── app/
│   │   ├── api/             # Route blueprints
│   │   ├── models/          # SQLAlchemy models
│   │   ├── services/        # Business logic
│   │   ├── tasks/           # Celery tasks
│   │   ├── classifier_core/ # (Phase 4) refactored classify_sensitivity
│   │   └── utils/
│   ├── migrations/          # Alembic
│   ├── tests/
│   └── pyproject.toml
├── frontend/                # React + TypeScript + Vite
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── pages/
│   │   └── routes/
│   └── package.json
├── docker-compose.yml
├── .env.example
├── DEVELOPMENT_PLAN.md      # 17-phase build plan
├── wiki_notes/              # Obsidian project wiki
└── classify_sensitivity.py  # Standalone classifier (to be refactored in Phase 4)
```

## Current Phase

**Phase 0 — Infrastructure foundation.** All containers start clean, `/healthz` returns OK. No business logic yet.

Next: [Phase 1 — Auth, users, audit log](DEVELOPMENT_PLAN.md#phase-1--auth-users-audit-log-size-l).
