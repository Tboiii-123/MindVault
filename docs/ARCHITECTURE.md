# Architecture & design decisions

## 1. Request flow: voice entry

```
POST /containers/{id}/entries/ (multipart audio)
  1. validate size / extension / content-type          (serializer)
  2. BEGIN
       INSERT entry(status=pending)  + audio -> S3
       UPDATE container SET entry_count=entry_count+1, last_activity_at=now()   (atomic F())
     COMMIT
  3. on_commit -> process_entry.delay(id)              (never enqueue before the row is visible)
  4. 202 Accepted {status: "pending"}                  (client polls GET /entries/{id}/)

Celery worker (queue "ai")
  pending -> transcribing : STT provider -> transcript saved + tsvector refreshed (searchable now)
          -> analyzing    : LLM -> summary, key points, action items, tags
          -> container.title AI-named once (only if title_is_auto)
          -> completed    : search_vector refreshed, public cache invalidated
  transient error (timeout/429/5xx) -> retry w/ exponential backoff + jitter (max 5)
  permanent error / retries exhausted -> failed (+ error_message), user can POST /retry/
```

## 2. Why these choices

| Decision | Reason |
|---|---|
| **Function-based views** with `@api_view` | Explicit, flat control flow; thin views delegate to `services.py` / `selectors.py`. |
| **Service layer** for writes | Transactions, counters, and enqueue-after-commit live in one place, not scattered across views/serializers. |
| **Postgres is the source of truth for job state** | `Entry.status` survives broker restarts; Celery results are disabled (`IGNORE_RESULT`). |
| **Idempotent tasks** | COMPLETED is a no-op; an existing transcript is never re-transcribed (STT costs money). Safe under `acks_late` redelivery. |
| **Sweeper (`requeue_stuck_entries`, beat)** | Recovers entries whose message was lost or worker was killed. Uses a *partial index* on in-flight statuses. |
| **Provider interfaces** (`STTProvider`, `LLMProvider`) | Swap OpenAI/Deepgram/local Whisper/Anthropic via an env var; fake providers keep dev/CI free and deterministic. |
| **UUID PKs** | Non-enumerable in URLs; safe to shard later. |
| **404 instead of 403 for others' objects** | Every query is filtered by `owner`, so private IDs never leak existence. |
| **Public links are random 128-bit tokens, rotated on re-publish** | Unguessable; unpublishing really kills the old URL. Only whitelisted fields are exposed (no emails). |

## 3. Query optimisation

| Access path | Technique |
|---|---|
| Home screen: containers by recent activity | Composite index `(owner, status, -last_activity_at)`; **denormalised** `entry_count`/`last_activity_at` so there is never a `COUNT(*)` or a join. `.defer("summary")` skips the large text column in lists. |
| Entry timeline | Index `(container, -created_at)` + **cursor (keyset) pagination**: constant cost on page 1 and page 10 000, unlike `OFFSET`. |
| Full-text search | Stored `tsvector` column (`A` = text/transcript, `B` = summary) + **GIN index**, refreshed by a single `UPDATE` computed inside Postgres. `websearch` syntax (`"phrases"`, `-exclude`). `SearchRank` and `SearchHeadline` run only on the LIMITed rows; `.values()` avoids model hydration. The query plan was verified to use `Bitmap Index Scan on en_search_gin`. |
| Tag filter | GIN index on the JSONB `tags` (`tags @> '["redis"]'`). |
| Public page | 2 queries on a cache miss (container+owner `JOIN`, one `Prefetch` for entries with `.only()`), 0 on a hit (Redis, 60 s TTL, invalidated on edits and unpublish). Asserted in tests with `django_assert_num_queries`. |
| Counter races | `F("entry_count") + 1` in one `UPDATE`: no read-modify-write. |
| Stuck-job sweeper | Partial index on `updated_at WHERE status IN (pending, transcribing, analyzing)`: tiny and fast even with millions of rows. |
| Container summary | Streams rows with `.iterator()`, uses stored per-entry summaries for long entries, stops at a character budget (map-reduce style). |
| Connections | `CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS`; put PgBouncer in front at scale. |

## 4. Scalability

* **API** is stateless (JWT) → scale horizontally behind a load balancer.
* **Workers** scale independently; separate queues (`default`, `ai`) so slow STT jobs never starve other work. `prefetch_multiplier=1` gives fair dispatch for long tasks.
* **Audio** lives in object storage; the API only stores a key and issues short-lived pre-signed URLs (bucket stays private).
* **Read replicas** can serve search and public pages if needed; the `selectors.py` layer is the natural seam.
* **Future direct-to-S3 upload**: client gets a pre-signed PUT URL and then calls "create entry", so large files bypass Django.

## 5. Security

* JWT access (15 min) + refresh rotation with blacklist; logout invalidates the refresh token.
* Per-scope throttling: `auth`, `uploads`, `ai`, `public`, `user`, `anon`.
* Password validators; password reset never reveals whether an email exists.
* Upload validation (size, extension *and* content type); server-generated storage paths.
* Prod settings: HTTPS redirect, HSTS, secure cookies, `SECRET_KEY` required, non-root container user.
* Public page sends `X-Robots-Tag: noindex`, `Referrer-Policy: no-referrer`; Django escapes all user content.

## 6. Known limits and next steps

* **Semantic search / Ask My Notes (Phase 2):** add `pgvector`, an `EntryChunk(embedding vector)` table with an HNSW index, an `embed_entry` Celery task after `analyzing`, and a retrieval endpoint feeding the LLM only the user's own chunks.
* **Real-time status:** swap polling for Django Channels/SSE using the same status transitions.
* **Selective entry sharing & collaborators:** add `Entry.visibility` and a `ContainerMember(container, user, role)` table; every query already goes through `owner` filters, which become `Q(owner=user) | Q(members__user=user)`.
* **Audio is public when its container is public** (pre-signed URL embedded in the page). For stricter control, proxy through an authorised endpoint.
* **Two simultaneous workers** on the same entry are harmless (idempotent) but could duplicate LLM spend; add a `SELECT ... FOR UPDATE SKIP LOCKED` claim if this matters.
* Docker images are defined and the compose/CI files are syntax-checked, but the image was not built in the authoring sandbox (no Docker daemon). CI builds it on first push.
