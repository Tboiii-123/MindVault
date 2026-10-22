# AI Personal Notes: Django backend

Self-chat style notes with **voice → text**, **AI naming/summaries**, **full-text search**, and **public sharing**.
Django 5 · DRF (function-based views only) · PostgreSQL · Redis · Celery · S3/MinIO · Docker · GitHub Actions.

```
Client ──► Django/DRF API ──► PostgreSQL        (state, FTS index)
                │  └────────► S3 / MinIO        (audio)
                └─ enqueue ─► Redis ─► Celery workers ─► STT + LLM providers
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design decisions.

## Quick start (Docker)

```bash
cp .env.example .env
make up                       # api :8000, worker, beat, postgres, redis, minio
make superuser                # optional, for /admin/
open http://localhost:8000/api/docs/   # Swagger UI
```

Runs fully offline by default using **fake AI providers**. To use OpenAI, set in `.env`:

```
AI_STT_PROVIDER=apps.ai.providers.openai_provider.OpenAISTTProvider
AI_LLM_PROVIDER=apps.ai.providers.openai_provider.OpenAILLMProvider
OPENAI_API_KEY=sk-...
```

## Local (no Docker)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements/dev.txt
cp .env.example .env          # point DATABASE_URL / REDIS_URL at local services
python manage.py migrate && python manage.py runserver
celery -A config worker -l info -Q default,ai      # second terminal
celery -A config beat -l info                      # third terminal (optional)
```

## Tests & quality

```bash
pytest --cov=apps             # needs Postgres (uses DATABASE_URL); Celery runs eagerly
ruff check . && ruff format --check .
```

## API (all under `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| POST | `auth/register/` `auth/login/` `auth/refresh/` `auth/logout/` | JWT auth (refresh rotation + blacklist) |
| GET/PATCH | `auth/me/` | Profile |
| POST | `auth/password-reset/` · `auth/password-reset/confirm/` | Reset flow |
| POST | `capture/` | **Capture first**: text or audio; creates + AI-names a container if none given |
| GET/POST | `containers/` | List (cursor-paginated) / create |
| GET/PATCH/DELETE | `containers/{id}/` | Rename, archive, delete |
| GET/POST | `containers/{id}/entries/` | Timeline / add text or audio (**202 Accepted**, poll `status`) |
| GET/PATCH/DELETE | `entries/{id}/` | Edit text/transcript (re-runs AI), delete |
| POST | `entries/{id}/retry/` | Retry a FAILED entry |
| POST | `containers/{id}/summary/` | Async AI summary: `today/yesterday/week/month/all/custom` |
| POST/DELETE | `containers/{id}/share/` | Publish / unpublish |
| GET | `public/{public_id}/` | Anonymous JSON of a public container |
| GET | `/share/{public_id}/` | Anonymous server-rendered web page |
| GET | `search/?q=&container=` | Full-text search with highlighted snippets |
| GET | `/health/live/` `/health/ready/` | Probes |

Entry lifecycle: `pending → transcribing → analyzing → completed | failed`.

## Deploy

CI (`.github/workflows/ci.yml`) runs lint → migrations check → tests (Postgres service, ≥80% coverage) → builds and pushes
the `runtime` image to GHCR on `main`. `deploy.yml` then rolls it out over SSH using `docker-compose.prod.yml`
(swap for ECS/Fly/K8s as needed). Required secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`.

## Layout

```
config/            settings (base/dev/prod/test), urls, celery app
apps/common/       base models, cursor pagination, throttles, error envelope, health
apps/users/        email-login User, JWT auth views
apps/containers/   Container & Entry models, services (transactions), views
apps/ai/           provider interfaces (fake/OpenAI), Celery pipeline tasks
apps/sharing/      publish/unpublish, public selectors, HTML template
apps/search/       Postgres full-text search
tests/             pytest suite
```
