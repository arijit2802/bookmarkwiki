# DKE Design Spec — Phase 0: Infrastructure (Celery + Redis + pgvector)
**Date:** 2026-05-04
**Status:** Approved

---

## 1. Problem Statement

Features 2, 3, and 4 require infrastructure that does not exist in the current Phase 1 setup: a distributed task queue (Celery + Redis) for safe multi-worker processing, and pgvector on Neon PostgreSQL for vector similarity search. This spec covers the one-time setup that must be completed before any of those features are implemented.

---

## 2. Scope

### In scope
- Add Redis (Upstash in production, Docker in local dev) as Celery broker + result backend
- Add Celery worker process alongside FastAPI app
- Migrate existing FastAPI background tasks in `processor.py` to Celery tasks
- Enable pgvector extension on Neon PostgreSQL
- Add `embedding vector(384)` column to `wiki_nodes`
- Update `docker-compose.yml` for local dev
- Update `requirements.txt` and environment variables

### Out of scope
- Celery beat scheduler (added in Feature 3)
- Flower monitoring dashboard (added in deployment/polish phase)
- Pinecone migration (not needed — using pgvector)

---

## 3. Architecture

```
Local dev (docker-compose)               Production (Railway)
┌─────────────────────────┐             ┌─────────────────────────┐
│  FastAPI app (:8000)    │             │  FastAPI app (Railway)  │
│  Celery worker          │             │  Celery worker (Railway)│
│  PostgreSQL (:5432)     │             │  Neon PostgreSQL        │
│  Redis (:6379)          │             │  Upstash Redis (free)   │
└─────────────────────────┘             └─────────────────────────┘
```

FastAPI app and Celery worker share the same codebase — different entry points.

---

## 4. Celery Setup

### Task flow
```
POST /bookmarks → FastAPI route → dispatch process_bookmark.delay(bookmark_id)
                                          ↓
                              Celery worker picks up task
                                          ↓
                              processor.py: extract → synthesize → write → embed → conflict check
```

### Entry points
```bash
# FastAPI
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# Celery worker
celery -A backend.tasks.celery_app worker --loglevel=info
```

### `backend/tasks/celery_app.py`
```python
from celery import Celery
from backend.config import settings

celery_app = Celery(
    "dke",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["backend.tasks.tasks"]
)

celery_app.conf.task_serializer = "json"
celery_app.conf.result_expires = 3600
```

### Retry policy
All tasks: max 3 retries, exponential backoff (60s, 120s, 240s). Failed after 3 retries → bookmark `status=failed`.

---

## 5. pgvector Setup

### Enable extension on Neon (run once)
```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE wiki_nodes ADD COLUMN embedding vector(384);
CREATE INDEX ON wiki_nodes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

### Python dependency
```
pgvector>=0.2.0
sentence-transformers>=2.7.0
```

---

## 6. docker-compose.yml Changes

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: dke
      POSTGRES_PASSWORD: dke
      POSTGRES_DB: dke
    ports:
      - "5432:5432"

  redis:                          # NEW
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

Note: pgvector extension is only needed on Neon (production). For local dev, PostgreSQL is used for relational data only — embedding similarity queries run against Neon.

---

## 7. Environment Variables

```
# Existing
GROQ_API_KEY=
DATABASE_URL=postgresql+asyncpg://...

# New
REDIS_URL=redis://localhost:6379/0          # local dev
# REDIS_URL=rediss://...upstash.io:6379     # production (Upstash)
GAP_ANALYSIS_THRESHOLD=10
```

---

## 8. Requirements Changes

```
# Add
celery>=5.4.0
redis>=5.0.0
pgvector>=0.2.0
sentence-transformers>=2.7.0

# Remove
# (none — existing deps unchanged)
```

---

## 9. Files Changed

| File | Type | Purpose |
|---|---|---|
| `backend/tasks/celery_app.py` | New | Celery app + worker config |
| `backend/tasks/tasks.py` | New | `process_bookmark` Celery task (migrated from background task) |
| `backend/pipeline/processor.py` | Modified | Remove BackgroundTasks dependency, callable directly by Celery |
| `backend/api/routes/bookmarks.py` | Modified | Replace `BackgroundTasks` with `process_bookmark.delay()` |
| `backend/config.py` | Modified | Add `redis_url`, `gap_analysis_threshold` |
| `docker-compose.yml` | Modified | Add Redis service |
| `requirements.txt` | Modified | Add celery, redis, pgvector, sentence-transformers |

---

## 10. Verification Checklist

1. `docker-compose up` → verify PostgreSQL + Redis both start cleanly
2. Start Celery worker → verify it connects to Redis and shows `ready`
3. `POST /bookmarks` → verify task dispatched to Celery (visible in worker logs)
4. Verify bookmark reaches `status=done` via Celery worker (not FastAPI background task)
5. Verify retry: kill worker mid-task, restart → verify task retries automatically
6. Connect to Neon → verify `vector` extension enabled + `embedding` column exists on `wiki_nodes`
7. Insert a test embedding → verify cosine similarity query returns correct results
