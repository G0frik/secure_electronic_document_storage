# Secure Document Storage

A web app for storing documents where access is decided by their **content**, not just by who owns them. Upload a file, an ML classifier reads it and assigns a sensitivity tier (public / internal / confidential / restricted), and role-based access control uses that tier to decide who can see it. Every file is encrypted at rest with AES-256-GCM.

The 17-phase build plan is in [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md); the day-to-day notes live in [`wiki_notes/`](wiki_notes/).

---

## What it does

**Documents**
- Upload anything. Text is extracted from 20+ formats: txt, md, pdf, docx, pptx, xlsx, csv, json, yaml, html, rtf, plus source-code extensions.
- 30-day soft-delete trash with restore.
- File versioning. Upload a new version, the old one stays downloadable for 30 days, then a reaper purges it.
- Inline text preview for txt / pdf / docx (no download needed).
- Per-user storage quota, 2 GiB default.

**Classification**
- Zero-shot NLI via HuggingFace (DeBERTa-v3 by default; `bge-m3` for multilingual).
- Microsoft Presidio for structured PII (PERSON, EMAIL, IBAN, credit cards, API keys), with custom recognizers for Ukrainian РНОКПП, passport numbers, and +380 phones.
- Final tier = max(NLI tier, Presidio tier). Patterns can escalate but never lower the semantic decision.
- Runs async on Celery; the UI polls until done.

**Access control**
- 3 roles × 4 tiers gives a 12-cell policy matrix. The default policies are: admin reads everything, user reads up to confidential, guest reads public only.
- Department-scoped overrides ("HR may read restricted files in HR categories").
- Group-targeted policies (assign users to ad-hoc groups, point a policy at the group).
- Every decision logged to `policy_evaluations` for audit, with a stable `reason` code (`tier_exceeds_policy`, `denied_category`, `classification_pending`, etc).

**Sharing**
- Internal shares between users. Cloud-drive semantics: a share elevates the recipient over their tier ceiling. Admin-set category bans still apply ("medical records" cannot be shared into a department that denies them).
- Folder shares cascade to every file inside.
- External magic links — token hashed at rest, configurable expiry + max-uses, RESTRICTED files blocked unless admin force-opts.

**Auth**
- Argon2id passwords with the NIST SP 800-63B policy (length-only, no symbol-class theatrics).
- HIBP k-anonymity check on register and change.
- TOTP 2FA with recovery codes. TOTP secrets are KEK-encrypted at rest.
- Server-side sessions in Redis. CSRF via double-submit cookie.
- Force-logout from the admin panel via session-invalid-before timestamps.

**Encryption**
- AES-256-GCM envelope encryption. Each file has its own DEK; DEKs are wrapped with a system-level KEK.
- Every encrypted blob records its `kek_version`. KEK rotation re-wraps DEKs without re-encrypting content.
- Plaintext bytes never go to disk on the upload/download path.
- Production refuses to start with an empty KEK; dev derives one from `SECRET_KEY` with a loud warning.

**Operations**
- SIEM-friendly NDJSON event stream at `logs/events.jsonl`, ECS (Elastic Common Schema) mapped, ready for Filebeat → Elastic or a Wazuh agent. Example configs in [`docs/siem/`](docs/siem/).
- HTTP pull endpoint `/api/admin/events` for air-gapped setups that prefer polling over file tail.
- In-app notification bell with severity coloring. Email path for critical events (SMTP, Mailhog in dev).
- Background reaper tasks for trash and old file versions (Celery + `flask reap-trash` / `flask reap-file-versions` CLI).
- Storage quota drift safety: `flask recompute-quota` re-sums every user's usage from `files.size_bytes`.

---

## Quick start

```bash
cp .env.example .env
docker compose up -d --build

# Wait ~30s for Postgres + MinIO to settle, then:
docker compose exec backend flask seed-dev    # 3 departments + 5 users
docker compose exec backend flask seed-demo   # sample files + folders + shares + override
```

Open http://localhost:5173 and log in:

| Email | Password | Role |
|---|---|---|
| admin@example.com | `ChangeMeNow123!` | admin |
| alice@example.com | `AlicePassword123!` | user (marketing) |
| bob@example.com | `BobPassword123!` | user, manager (hr) |
| carol@example.com | `CarolPassword123!` | user (engineering) |
| dave@example.com | `DavePassword123!` | guest |

Change the passwords before doing anything beyond local development.

## Service URLs

| Service | URL | Auth |
|---|---|---|
| Frontend | http://localhost:5173 | session cookie |
| Backend API | http://localhost:8000 | session cookie |
| MinIO console | http://localhost:9001 | minioadmin / minioadmin |
| Mailhog (outgoing email in dev) | http://localhost:8025 | none |
| Postgres | localhost:5432 | docstore / docstore |
| Redis | localhost:6379 | none |

## Make targets

```bash
make up                 # docker compose up -d
make down               # docker compose down
make logs               # tail
make seed-dev           # users + departments
make seed-demo          # files + folders + shares + share-link + pending override
make test               # pytest (autocreates docstore_test on first run)
make coverage           # pytest + coverage XML + terminal report
make lint               # ruff + mypy + eslint
make shell-backend      # bash inside the backend container
make shell-db           # psql inside the db container
make migrate            # alembic upgrade head
make revision           # alembic revision --autogenerate (prompts for message)
make clean              # stop stack and drop volumes
```

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Flask 3 + SQLAlchemy 2.0 + Alembic | Pragmatic; standard for this kind of app |
| Async | Celery + Redis | Classifier takes ~10s on first model load; can't block HTTP |
| Database | Postgres 16 | citext for case-insensitive emails, JSONB for audit metadata, partial unique indexes |
| Object store | MinIO (S3-compatible) | Metadata in Postgres, ciphertext blobs in MinIO; encryption is applied app-side |
| Frontend | React 18 + TypeScript + Vite | Standard SPA, no SSR needed |
| Sessions | Flask-Session backed by Redis | Server-side, so revocation is immediate; no JWT claim drift |
| Crypto | `cryptography` (AES-256-GCM) + `argon2-cffi` (passwords) | NIST-recommended primitives |
| Classifier | HuggingFace transformers + MoritzLaurer zero-shot NLI + Presidio + spaCy `en_core_web_lg` | Zero-shot avoids needing a labeled corpus per organization |

## Project layout

```
secure_document_storage/
├── backend/
│   ├── app/
│   │   ├── api/                  # Route blueprints (files, auth, admin_*, public_share_links, …)
│   │   ├── models/               # SQLAlchemy 2.0 declarative models
│   │   ├── services/             # All business logic (the PDP lives in policy.py)
│   │   ├── tasks/                # Celery tasks (classification, cleanup, notifications)
│   │   ├── classifier_core/      # ML pipeline (extract → zero_shot → presidio → tier)
│   │   ├── schemas/              # Pydantic request/response shapes
│   │   └── utils/                # auth_decorators, format helpers
│   ├── migrations/               # Alembic (14 migrations, one per phase that touched schema)
│   └── tests/                    # 316 pytest tests
├── frontend/
│   └── src/
│       ├── api/                  # Axios clients per domain
│       ├── components/           # Dialogs, tables, file list, notification bell
│       ├── pages/                # Top-level routes (Home, Login, Folders, Trash, /admin/*)
│       ├── routes/               # ProtectedRoute, AdminRoute guards
│       └── state/                # AuthProvider context
├── classify_sensitivity_data/    # Test + blind corpora for classifier evaluation
├── docker-compose.yml            # 7 services: db, redis, minio, mailhog, backend, worker, frontend
├── docs/siem/                    # Filebeat + Wazuh ingestion snippets for the NDJSON event stream
├── logs/                         # NDJSON event stream (bind-mounted from backend + worker containers)
├── wiki_notes/                   # Obsidian wiki: design notes, ADRs, phase tracker, RBAC docs
├── DEVELOPMENT_PLAN.md           # The 17-phase plan this project follows
└── .github/workflows/ci.yml      # GitHub Actions: backend tests + coverage, frontend build
```

## Tests and CI

316 pytest tests covering every API endpoint, every policy decision, every encryption-tampering path, every share-link expiry condition, the full 12-cell RBAC matrix, file versioning, and the demo seed.

```bash
make test       # 316 tests, ~85s
make coverage   # adds coverage.xml + terminal report (~86% line coverage)
```

GitHub Actions runs the backend tests with coverage and the frontend lint/typecheck/build on every push and PR. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Status

16 of 17 phases shipped. See [`wiki_notes/Roadmap/Phase Tracker.md`](wiki_notes/Roadmap/Phase%20Tracker.md) for the full per-phase breakdown with file paths and test counts.

| Phase | What | Status |
|---|---|---|
| 0 | Infrastructure (Docker, healthchecks, structured logging) | ✅ |
| 1 | Auth, users, audit log | ✅ |
| 2 | Files: upload, download, list | ✅ |
| 3 | AES-256-GCM envelope encryption at rest | ✅ |
| 4 | Classifier integration via Celery | ✅ |
| 5 | RBAC enforced by tier (PDP at `services/policy.py`) | ✅ |
| 6 | TOTP 2FA | ✅ |
| 7 | Folders + internal sharing | ✅ |
| 8 | External magic links | ✅ |
| 9 | Trash (soft delete + 30-day reaper) | ✅ |
| 10 | Tags + tier-override workflow | ✅ |
| 11 | Notifications + SIEM event stream | ✅ |
| 12 | Storage quota | ✅ |
| 13 | Admin panel (users, groups, departments, policies, events) | ✅ |
| 14 | Text / PDF / DOCX preview | ✅ |
| 15 | File versioning | ✅ |
| 16 | Demo seed + RBAC matrix tests + GitHub Actions CI | ✅ |
| 17 | Documentation polish (threat model, ADRs, OpenAPI, screenshots) | ⏳ |

## Reading more

- [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md) — the 17-phase build plan
- [`wiki_notes/Home.md`](wiki_notes/Home.md) — wiki entry point (architecture, security, API reference, ADRs)
- [`wiki_notes/Roadmap/Phase Tracker.md`](wiki_notes/Roadmap/Phase%20Tracker.md) — what shipped in each phase, with file paths
- [`wiki_notes/Security/RBAC & Access Control.md`](wiki_notes/Security/RBAC%20&%20Access%20Control.md) — how the policy decision point works
- [`wiki_notes/Backend/API Reference.md`](wiki_notes/Backend/API%20Reference.md) — every endpoint, request/response shapes, deny reasons
- [`docs/siem/`](docs/siem/) — Filebeat and Wazuh snippets for ingesting the NDJSON event stream

## Known limitations

These are documented as future work rather than bugs:

- The classifier loads the full plaintext into memory. Multi-gigabyte files need streaming AES-GCM (e.g., GCM-SIV in chunks), not implemented.
- Scanned PDFs return "no text extracted" — OCR fallback isn't wired.
- KEK rotation hooks exist (every blob records its `kek_version`) but there's no CLI to perform a rotation yet.
- Session-ID rotation on login isn't implemented (Flask doesn't ship it out of the box; documented as a gap).
- `mypy` is report-only in CI. The older modules have noisy type errors that haven't been cleaned up.
- The text-preview extractor renders the extracted text as plain mono-spaced text. No syntax highlighting yet.
- Old file versions don't display their own tier badge — the current tier is always shown. Per-version classification rows exist in the DB but aren't surfaced in the UI.
