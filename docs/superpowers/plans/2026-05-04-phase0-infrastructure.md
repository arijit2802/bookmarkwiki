# Phase 0: Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pgvector to the existing DKE backend and wire up FastAPI `BackgroundTasks` for async bookmark processing. No Redis or Celery needed.

**Architecture:** `BackgroundTasks` runs inside the FastAPI process after each response. `process_bookmark` is an async function called directly via `background_tasks.add_task(...)`. pgvector extension is enabled on Neon PostgreSQL with an `embedding vector(384)` column added to `wiki_nodes`.

**Tech Stack:** FastAPI BackgroundTasks (built-in), pgvector 0.2, sentence-transformers 2.7, Docker Compose

**Working directory:** `.worktrees/dke-phase1/dke`

---

### Task 1: Update config with gap threshold and install new deps

**Files:**
- Modify: `backend/config.py`
- Modify: `.env.example`
- Modify: `requirements.txt`

- [ ] **Step 1: Write failing test**

Create `tests/test_config.py`:
```python
import os
import pytest


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

Expected: FAIL — `Settings` has no field `gap_analysis_threshold`

- [ ] **Step 3: Update config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    groq_api_key: str
    database_url: str = "postgresql+asyncpg://dke:dke@localhost:5432/dke"
    wiki_dir: str = "wiki"
    groq_model: str = "llama-3.3-70b-versatile"
    gap_analysis_threshold: int = 10

    model_config = {"env_file": ".env"}


settings = Settings()
```

- [ ] **Step 4: Update .env.example**

```
GROQ_API_KEY=your_groq_api_key_here
DATABASE_URL=postgresql+asyncpg://dke:dke@localhost:5432/dke
WIKI_DIR=wiki
GAP_ANALYSIS_THRESHOLD=10
```

- [ ] **Step 5: Add new dependencies to requirements.txt**

Add these lines:
```
pgvector>=0.2.0
sentence-transformers>=2.7.0
```

- [ ] **Step 6: Install new dependencies**

```bash
.venv/bin/pip install "pgvector>=0.2.0" "sentence-transformers>=2.7.0"
```

Expected: All packages install without errors.

- [ ] **Step 7: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/config.py .env.example requirements.txt tests/test_config.py
git commit -m "feat: add gap_analysis_threshold to config and pgvector/sentence-transformers deps"
```

---

### Task 2: Update bookmarks route to use BackgroundTasks

**Files:**
- Modify: `backend/api/routes/bookmarks.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_bookmarks_background.py`:
```python
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_create_bookmark_queues_background_task(mocker):
    mock_process = mocker.patch("backend.api.routes.bookmarks.process_bookmark", new_callable=AsyncMock)

    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/bookmarks", json={"url": "https://example.com"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_bulk_create_queues_background_task_for_each(mocker):
    mock_process = mocker.patch("backend.api.routes.bookmarks.process_bookmark", new_callable=AsyncMock)

    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/bookmarks/bulk",
            json={"urls": ["https://a.com", "https://b.com"]},
        )

    assert resp.json() == {"queued": 2}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_bookmarks_background.py -v
```

Expected: FAIL — route doesn't import `process_bookmark` yet

- [ ] **Step 3: Update `backend/api/routes/bookmarks.py`**

```python
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_db
from backend.models.bookmark import Bookmark
from backend.pipeline.processor import process_bookmark

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
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    bm = Bookmark(url=body.url, tags=body.tags, source=body.source)
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    background_tasks.add_task(process_bookmark, bm.id, bm.url)
    return {"id": str(bm.id), "url": bm.url, "status": bm.status}


@router.post("/bookmarks/bulk")
async def bulk_create_bookmarks(
    body: BulkBookmarkIn,
    background_tasks: BackgroundTasks,
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
        background_tasks.add_task(process_bookmark, bm.id, bm.url)
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
.venv/bin/pytest tests/test_bookmarks_background.py -v
```

Expected: PASS

- [ ] **Step 5: Smoke test end-to-end**

```bash
# Terminal 1 — start FastAPI
cd .worktrees/dke-phase1/dke
.venv/bin/uvicorn backend.api.main:app --reload --port 8000

# Terminal 2 — submit a bookmark
curl -s -X POST http://localhost:8000/bookmarks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

Expected: Immediate 200 response + FastAPI logs show background task starting.

- [ ] **Step 6: Commit**

```bash
git add backend/api/routes/bookmarks.py tests/test_bookmarks_background.py
git commit -m "feat: replace Celery dispatch with FastAPI BackgroundTasks in bookmarks route"
```

---

### Task 3: Enable pgvector on Neon and add embedding column

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

### Task 4: Verify full infrastructure stack

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 2: Start local stack**

```bash
docker-compose up -d
.venv/bin/uvicorn backend.api.main:app --reload --port 8000
```

- [ ] **Step 3: Submit a test bookmark and verify it processes**

```bash
curl -s -X POST http://localhost:8000/bookmarks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture"}'
sleep 30
curl -s http://localhost:8000/bookmarks | python3 -m json.tool
```

Expected: Bookmark shows `"status": "done"` and FastAPI logs show background task completed.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "chore: Phase 0 infrastructure complete — BackgroundTasks + pgvector"
```
