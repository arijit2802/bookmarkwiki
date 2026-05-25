# DKE Design Spec — Phase 0: Infrastructure (pgvector)
**Date:** 2026-05-04
**Status:** Approved (updated: Celery/Redis replaced with FastAPI BackgroundTasks)

---

## 1. Problem Statement

Features 2, 3, and 4 require infrastructure that does not exist in the current Phase 1 setup: pgvector on Neon PostgreSQL for vector similarity search. Async bookmark processing uses FastAPI's built-in `BackgroundTasks` — no separate broker, worker process, or Redis needed. This spec covers the one-time setup that must be completed before any of those features are implemented.

---

## 2. Scope

### In scope
- Use FastAPI `BackgroundTasks` for async bookmark processing (built-in, zero new deps)
- Enable pgvector extension on Neon PostgreSQL
- Add `embedding vector(384)` column to `wiki_nodes`
- Update `requirements.txt` (pgvector, sentence-transformers)

### Out of scope
- Redis / Celery (not needed — BackgroundTasks handles async processing)
- Flower monitoring dashboard
- Pinecone migration (not needed — using pgvector)

---

## 3. Architecture

```
Local dev (docker-compose)               Production (Railway)
┌─────────────────────────┐             ┌─────────────────────────┐
│  FastAPI app (:8000)    │             │  FastAPI app (Railway)  │
│  BackgroundTasks        │             │  BackgroundTasks        │
│  PostgreSQL (:5432)     │             │  Neon PostgreSQL        │
└─────────────────────────┘             └─────────────────────────┘
```

No separate worker process. Background tasks run inside the FastAPI process after the HTTP response is sent.

---

## 4. BackgroundTasks Setup

### Task flow
```
POST /bookmarks → FastAPI route → background_tasks.add_task(process_bookmark, bookmark_id, url)
                                              ↓
                                 Response returned to client immediately
                                              ↓
                                 BackgroundTask runs in same process
                                              ↓
                                 processor.py: extract → synthesize → write → embed → conflict check
```

### Pattern
```python
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_db
from backend.models.bookmark import Bookmark
from backend.pipeline.processor import process_bookmark

router = APIRouter()

@router.post("/bookmarks")
async def create_bookmark(
    body: BookmarkIn,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    bm = Bookmark(url=body.url, tags=body.tags, source=body.source)
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    background_tasks.add_task(process_bookmark, bm.id, bm.url)
    return {"id": str(bm.id), "url": bm.url, "status": bm.status}
```

`process_bookmark` is an async function — FastAPI's `BackgroundTasks` supports async callables natively.

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

## 6. docker-compose.yml

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
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

No Redis service needed.

Note: pgvector extension is only needed on Neon (production). For local dev, PostgreSQL is used for relational data only — embedding similarity queries run against Neon.

---

## 7. Environment Variables

```
# Existing (unchanged)
GROQ_API_KEY=
DATABASE_URL=postgresql+asyncpg://...

# New
GAP_ANALYSIS_THRESHOLD=10
```

No `REDIS_URL` needed.

---

## 8. Requirements Changes

```
# Add
pgvector>=0.2.0
sentence-transformers>=2.7.0

# Remove / not needed
# celery, redis — replaced by FastAPI BackgroundTasks
```

---

## 9. Files Changed

| File | Type | Purpose |
|---|---|---|
| `backend/pipeline/processor.py` | Unchanged | Already async-callable; BackgroundTasks calls it directly |
| `backend/api/routes/bookmarks.py` | Modified | Inject `BackgroundTasks`, call `add_task(process_bookmark, ...)` |
| `backend/config.py` | Modified | Add `gap_analysis_threshold` |
| `requirements.txt` | Modified | Add pgvector, sentence-transformers |

---

## 10. Verification Checklist

1. `docker-compose up` → verify PostgreSQL starts cleanly
2. `POST /bookmarks` → verify 200 response returned immediately
3. Check FastAPI logs → verify background task starts and processes the bookmark
4. Verify bookmark reaches `status=done` via the background task
5. Connect to Neon → verify `vector` extension enabled + `embedding` column exists on `wiki_nodes`
6. Insert a test embedding → verify cosine similarity query returns correct results
