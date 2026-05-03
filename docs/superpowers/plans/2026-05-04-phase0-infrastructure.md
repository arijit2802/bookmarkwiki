# Phase 0: Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Celery + Redis task queue and pgvector to the existing DKE backend, migrating FastAPI background tasks to Celery workers.

**Architecture:** Celery worker shares the same Python codebase as FastAPI. The `process_bookmark` async function is wrapped in a synchronous Celery task using `asyncio.run()`. Redis (Upstash in production, Docker locally) serves as broker and result backend. pgvector extension is enabled on Neon PostgreSQL with an `embedding vector(384)` column added to `wiki_nodes`.

**Tech Stack:** Celery 5.4, Redis 5, pgvector 0.2, sentence-transformers 2.7, Docker Compose

**Working directory:** `.worktrees/dke-phase1/dke`

---

### Task 1: Add Redis to docker-compose and update requirements

**Files:**
- Modify: `docker-compose.yml`
- Modify: `requirements.txt`

- [ ] **Step 1: Add Redis service to docker-compose.yml**

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

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

- [ ] **Step 2: Add new dependencies to requirements.txt**

Add these lines after `pydantic-settings>=2.3.0`:
```
celery>=5.4.0
redis>=5.0.0
pgvector>=0.2.0
sentence-transformers>=2.7.0
```

- [ ] **Step 3: Install new dependencies**

```bash
.venv/bin/pip install celery>=5.4.0 redis>=5.0.0 pgvector>=0.2.0 "sentence-transformers>=2.7.0"
```

Expected: All packages install without errors.

- [ ] **Step 4: Start Redis locally**

```bash
docker-compose up redis -d
```

Expected output: `Container dke-redis-1 Started`

- [ ] **Step 5: Verify Redis is running**

```bash
docker-compose exec redis redis-cli ping
```

Expected: `PONG`

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml requirements.txt
git commit -m "chore: add Redis to docker-compose and Celery/pgvector deps"
```

---

### Task 2: Update config with Redis URL and gap threshold

**Files:**
- Modify: `backend/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing test**

Create `tests/test_config.py`:
```python
import os
import pytest


def test_config_has_redis_url():
    os.environ["GROQ_API_KEY"] = "test"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    # Re-import to pick up env vars
    import importlib
    import backend.config as cfg
    importlib.reload(cfg)
    assert cfg.settings.redis_url == "redis://localhost:6379/0"


def test_config_gap_threshold_default():
    os.environ["GROQ_API_KEY"] = "test"
    os.environ.pop("GAP_ANALYSIS_THRESHOLD", None)
    import importlib
    import backend.config as cfg
    importlib.reload(cfg)
    assert cfg.settings.gap_analysis_threshold == 10
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: FAIL — `Settings` has no field `redis_url`

- [ ] **Step 3: Update config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    groq_api_key: str
    database_url: str = "postgresql+asyncpg://dke:dke@localhost:5432/dke"
    wiki_dir: str = "wiki"
    groq_model: str = "llama-3.3-70b-versatile"
    redis_url: str = "redis://localhost:6379/0"
    gap_analysis_threshold: int = 10

    model_config = {"env_file": ".env"}


settings = Settings()
```

- [ ] **Step 4: Update .env.example**

```
GROQ_API_KEY=your_groq_api_key_here
DATABASE_URL=postgresql+asyncpg://dke:dke@localhost:5432/dke
WIKI_DIR=wiki
REDIS_URL=redis://localhost:6379/0
GAP_ANALYSIS_THRESHOLD=10
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/config.py .env.example tests/test_config.py
git commit -m "feat: add redis_url and gap_analysis_threshold to config"
```

---

### Task 3: Create Celery app

**Files:**
- Create: `backend/tasks/__init__.py`
- Create: `backend/tasks/celery_app.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_celery_app.py`:
```python
def test_celery_app_name():
    from backend.tasks.celery_app import celery_app
    assert celery_app.main == "dke"


def test_celery_app_has_task_include():
    from backend.tasks.celery_app import celery_app
    assert "backend.tasks.tasks" in celery_app.conf.include
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_celery_app.py -v
```

Expected: FAIL — `backend.tasks.celery_app` not found

- [ ] **Step 3: Create `backend/tasks/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `backend/tasks/celery_app.py`**

```python
from celery import Celery

from backend.config import settings

celery_app = Celery(
    "dke",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["backend.tasks.tasks"],
)

celery_app.conf.task_serializer = "json"
celery_app.conf.result_expires = 3600
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True

# Retry policy: 3 retries with exponential backoff
celery_app.conf.task_annotations = {
    "*": {
        "max_retries": 3,
        "default_retry_delay": 60,
    }
}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_celery_app.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/tasks/__init__.py backend/tasks/celery_app.py tests/test_celery_app.py
git commit -m "feat: add Celery app configuration"
```

---

### Task 4: Create Celery tasks file wrapping processor

**Files:**
- Create: `backend/tasks/tasks.py`
- Modify: `backend/pipeline/processor.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_tasks.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4


def test_process_bookmark_task_exists():
    from backend.tasks.tasks import process_bookmark_task
    assert callable(process_bookmark_task)


def test_process_bookmark_task_calls_processor(mocker):
    mock_run = mocker.patch("backend.tasks.tasks.asyncio.run")
    from backend.tasks.tasks import process_bookmark_task
    bookmark_id = str(uuid4())
    process_bookmark_task(bookmark_id, "https://example.com")
    mock_run.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_tasks.py -v
```

Expected: FAIL — `backend.tasks.tasks` not found

- [ ] **Step 3: Create `backend/tasks/tasks.py`**

```python
import asyncio
from uuid import UUID

from backend.tasks.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_bookmark_task(self, bookmark_id: str, url: str) -> None:
    """Celery task wrapping the async process_bookmark pipeline."""
    from backend.pipeline.processor import process_bookmark
    try:
        asyncio.run(process_bookmark(UUID(bookmark_id), url))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_tasks.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tasks/tasks.py tests/test_tasks.py
git commit -m "feat: add process_bookmark_task Celery task"
```

---

### Task 5: Update bookmarks route to dispatch Celery task

**Files:**
- Modify: `backend/api/routes/bookmarks.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_bookmarks_celery.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_create_bookmark_dispatches_celery(mocker):
    mock_task = mocker.patch("backend.api.routes.bookmarks.process_bookmark_task")
    mock_task.delay = MagicMock()

    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/bookmarks", json={"url": "https://example.com"})

    assert resp.status_code == 200
    mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_bulk_create_dispatches_celery_for_each(mocker):
    mock_task = mocker.patch("backend.api.routes.bookmarks.process_bookmark_task")
    mock_task.delay = MagicMock()

    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/bookmarks/bulk",
            json={"urls": ["https://a.com", "https://b.com"]},
        )

    assert resp.json() == {"queued": 2}
    assert mock_task.delay.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_bookmarks_celery.py -v
```

Expected: FAIL — route still uses BackgroundTasks

- [ ] **Step 3: Update `backend/api/routes/bookmarks.py`**

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_db
from backend.models.bookmark import Bookmark
from backend.tasks.tasks import process_bookmark_task

router = APIRouter()


class BookmarkIn(BaseModel):
    url: str
    tags: list[str] = []
    source: str = "manual"


class BulkBookmarkIn(BaseModel):
    urls: list[str]


@router.post("/bookmarks")
async def create_bookmark(
    body: BookmarkIn,
    db: AsyncSession = Depends(get_db),
):
    bm = Bookmark(url=body.url, tags=body.tags, source=body.source)
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    process_bookmark_task.delay(str(bm.id), bm.url)
    return {"id": str(bm.id), "url": bm.url, "status": bm.status}


@router.post("/bookmarks/bulk")
async def bulk_create_bookmarks(
    body: BulkBookmarkIn,
    db: AsyncSession = Depends(get_db),
):
    created = []
    for url in body.urls:
        bm = Bookmark(url=url, source="bulk_import", tags=[])
        db.add(bm)
        created.append(bm)
    await db.commit()
    for bm in created:
        await db.refresh(bm)
        process_bookmark_task.delay(str(bm.id), bm.url)
    return {"queued": len(created)}


@router.get("/bookmarks")
async def list_bookmarks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Bookmark).order_by(Bookmark.created_at.desc()))
    bookmarks = result.scalars().all()
    return [
        {"id": str(b.id), "url": b.url, "title": b.title, "status": b.status}
        for b in bookmarks
    ]


@router.get("/bookmarks/{bookmark_id}")
async def get_bookmark(bookmark_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Bookmark).where(Bookmark.id == bookmark_id))
    bm = result.scalar_one_or_none()
    if not bm:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {
        "id": str(bm.id),
        "url": bm.url,
        "title": bm.title,
        "status": bm.status,
        "content_type": bm.content_type,
        "tags": bm.tags,
        "error": bm.error,
        "created_at": bm.created_at.isoformat(),
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_bookmarks_celery.py -v
```

Expected: PASS

- [ ] **Step 5: Start Celery worker and smoke test end-to-end**

In a second terminal:
```bash
cd .worktrees/dke-phase1/dke
.venv/bin/celery -A backend.tasks.celery_app worker --loglevel=info
```

Then:
```bash
curl -s -X POST http://localhost:8000/bookmarks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

Expected: Worker logs show `Task backend.tasks.tasks.process_bookmark_task received`

- [ ] **Step 6: Commit**

```bash
git add backend/api/routes/bookmarks.py tests/test_bookmarks_celery.py
git commit -m "feat: replace FastAPI BackgroundTasks with Celery task dispatch"
```

---

### Task 6: Enable pgvector on Neon and add embedding column

**Files:**
- Modify: `backend/models/wiki_node.py`

- [ ] **Step 1: Enable pgvector extension on Neon**

Connect to your Neon database (via psql or Neon console SQL editor) and run:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE wiki_nodes ADD COLUMN IF NOT EXISTS embedding vector(384);
CREATE INDEX IF NOT EXISTS wiki_nodes_embedding_idx
  ON wiki_nodes USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

Expected: No errors. Column `embedding` appears in `\d wiki_nodes`.

- [ ] **Step 2: Write failing test**

Create `tests/test_wiki_node_model.py`:
```python
def test_wiki_node_has_embedding_column():
    from backend.models.wiki_node import WikiNode
    from sqlalchemy import inspect
    cols = {c.key for c in inspect(WikiNode).mapper.column_attrs}
    assert "embedding" in cols
```

- [ ] **Step 3: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_wiki_node_model.py -v
```

Expected: FAIL — `embedding` not in WikiNode columns

- [ ] **Step 4: Update `backend/models/wiki_node.py`**

```python
from datetime import datetime, timezone
from uuid import uuid4, UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres import Base


class WikiNode(Base):
    __tablename__ = "wiki_nodes"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    bookmark_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_wiki_node_model.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/models/wiki_node.py tests/test_wiki_node_model.py
git commit -m "feat: add pgvector embedding column to WikiNode model"
```

---

### Task 7: Verify full infrastructure stack

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 2: Start full local stack**

```bash
docker-compose up -d
.venv/bin/uvicorn backend.api.main:app --reload --port 8000 &
.venv/bin/celery -A backend.tasks.celery_app worker --loglevel=info &
```

- [ ] **Step 3: Submit a test bookmark and verify Celery processes it**

```bash
curl -s -X POST http://localhost:8000/bookmarks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture"}'
sleep 30
curl -s http://localhost:8000/bookmarks | python3 -m json.tool
```

Expected: Bookmark shows `"status": "done"` and Celery worker logs show task completed.

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "chore: Phase 0 infrastructure complete — Celery + Redis + pgvector"
```
