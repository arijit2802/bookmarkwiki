# Feature 2: Conflict & Friction Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After each wiki node is written, embed it with sentence-transformers, find similar nodes via pgvector, detect contradictions using Groq, and persist Dialectical Alerts to PostgreSQL.

**Architecture:** `conflict_engine.py` is a pure async module called from the Celery `process_bookmark_task` after `write_node` completes. It embeds the new node's summary, queries pgvector for top-5 similar nodes, calls Groq for each pair, and creates Alert records for HIGH/MEDIUM confidence conflicts. A new `/alerts` route exposes CRUD for the frontend.

**Tech Stack:** sentence-transformers `all-MiniLM-L6-v2`, pgvector, Groq `llama-3.3-70b-versatile`, SQLAlchemy async, FastAPI

**Prerequisite:** Phase 0 infrastructure plan must be complete.

**Working directory:** `.worktrees/dke-phase1/dke`

---

### Task 1: Create Alert model and database table

**Files:**
- Create: `backend/models/alert.py`
- Create: `tests/test_alert_model.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_alert_model.py
def test_alert_model_columns():
    from backend.models.alert import Alert
    from sqlalchemy import inspect
    cols = {c.key for c in inspect(Alert).mapper.column_attrs}
    assert "id" in cols
    assert "source_node_id" in cols
    assert "conflicting_node_id" in cols
    assert "description" in cols
    assert "confidence" in cols
    assert "status" in cols
    assert "created_at" in cols


def test_alert_default_status():
    from backend.models.alert import Alert
    alert = Alert(
        source_node_id=None,
        conflicting_node_id=None,
        description="test",
        confidence="HIGH",
    )
    assert alert.status == "open"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_alert_model.py -v
```

Expected: FAIL — `backend.models.alert` not found

- [ ] **Step 3: Create `backend/models/alert.py`**

```python
from datetime import datetime, timezone
from uuid import uuid4, UUID

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_node_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    conflicting_node_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 'HIGH' | 'MEDIUM'
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 4: Create the alerts table on Neon**

Connect to Neon and run:
```sql
CREATE TABLE IF NOT EXISTS alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_node_id UUID REFERENCES wiki_nodes(id),
  conflicting_node_id UUID REFERENCES wiki_nodes(id),
  description TEXT,
  confidence VARCHAR(10),
  status VARCHAR(20) NOT NULL DEFAULT 'open',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_alert_model.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/models/alert.py tests/test_alert_model.py
git commit -m "feat: add Alert model and create alerts table"
```

---

### Task 2: Create embedder module

**Files:**
- Create: `backend/pipeline/embedder.py`
- Create: `tests/test_embedder.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_embedder.py
def test_embed_returns_384_dimensions():
    from backend.pipeline.embedder import embed
    result = embed("This is a test sentence about machine learning.")
    assert isinstance(result, list)
    assert len(result) == 384
    assert all(isinstance(v, float) for v in result)


def test_embed_different_texts_differ():
    from backend.pipeline.embedder import embed
    a = embed("RAG improves accuracy in LLMs.")
    b = embed("Docker is a containerization platform.")
    assert a != b
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_embedder.py -v
```

Expected: FAIL — `backend.pipeline.embedder` not found

- [ ] **Step 3: Create `backend/pipeline/embedder.py`**

```python
from functools import lru_cache

from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Load model once and cache it for the process lifetime."""
    return SentenceTransformer("all-MiniLM-L6-v2")


def embed(text: str) -> list[float]:
    """Return 384-dimensional embedding for text."""
    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_embedder.py -v
```

Expected: PASS (first run downloads ~80MB model)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/embedder.py tests/test_embedder.py
git commit -m "feat: add sentence-transformers embedder (all-MiniLM-L6-v2)"
```

---

### Task 3: Create conflict detection prompt

**Files:**
- Create: `backend/prompts/conflict.md`

- [ ] **Step 1: Create `backend/prompts/conflict.md`**

```markdown
You are a critical thinking assistant. Compare these two knowledge base entries.

Node A — "{title_a}":
{summary_a}

Node B — "{title_b}":
{summary_b}

Do these entries make contradictory claims? Answer in this exact format:
CONFLICT: YES or NO
CONFIDENCE: HIGH, MEDIUM, or LOW
DESCRIPTION: One sentence explaining the specific contradiction, or "None" if no conflict.
```

- [ ] **Step 2: Verify prompt loads correctly**

```bash
.venv/bin/python3 -c "
from pathlib import Path
p = Path('backend/prompts/conflict.md').read_text()
assert '{title_a}' in p
assert '{summary_a}' in p
assert 'CONFLICT:' in p
print('Prompt OK')
"
```

Expected: `Prompt OK`

- [ ] **Step 3: Commit**

```bash
git add backend/prompts/conflict.md
git commit -m "feat: add Groq conflict detection prompt"
```

---

### Task 4: Create conflict engine

**Files:**
- Create: `backend/pipeline/conflict_engine.py`
- Create: `tests/test_conflict_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_conflict_engine.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


@pytest.mark.asyncio
async def test_run_conflict_check_no_similar_nodes(mocker):
    """When no similar nodes exist, no alert is created."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

    from backend.pipeline.conflict_engine import run_conflict_check
    await run_conflict_check(mock_db, node_id=uuid4(), summary="test summary")

    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_parse_conflict_response_yes():
    from backend.pipeline.conflict_engine import _parse_conflict_response
    raw = "CONFLICT: YES\nCONFIDENCE: HIGH\nDESCRIPTION: Source A claims X is fast, Source B claims X is slow."
    result = _parse_conflict_response(raw)
    assert result["conflict"] is True
    assert result["confidence"] == "HIGH"
    assert "fast" in result["description"]


@pytest.mark.asyncio
async def test_parse_conflict_response_no():
    from backend.pipeline.conflict_engine import _parse_conflict_response
    raw = "CONFLICT: NO\nCONFIDENCE: LOW\nDESCRIPTION: None"
    result = _parse_conflict_response(raw)
    assert result["conflict"] is False


@pytest.mark.asyncio
async def test_run_conflict_check_creates_alert_on_conflict(mocker):
    """When Groq detects HIGH conflict, an Alert is added to the DB."""
    node_id = uuid4()
    similar_node_id = uuid4()

    # Mock DB returning one similar node
    mock_row = MagicMock()
    mock_row.id = similar_node_id
    mock_row.title = "Similar Node"
    mock_row.summary = "Opposing claim"

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]

    # First execute call = similarity search, subsequent = duplicate check
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        mock_result,
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no duplicate
    ])

    mocker.patch(
        "backend.pipeline.conflict_engine._call_groq_conflict",
        return_value="CONFLICT: YES\nCONFIDENCE: HIGH\nDESCRIPTION: Direct contradiction.",
    )

    from backend.pipeline.conflict_engine import run_conflict_check
    await run_conflict_check(mock_db, node_id=node_id, summary="Original claim")

    mock_db.add.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_conflict_engine.py -v
```

Expected: FAIL — `backend.pipeline.conflict_engine` not found

- [ ] **Step 3: Create `backend/pipeline/conflict_engine.py`**

```python
from pathlib import Path
from uuid import UUID

from openai import OpenAI
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.alert import Alert
from backend.pipeline.embedder import embed

_client = OpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "conflict.md"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def _call_groq_conflict(title_a: str, summary_a: str, title_b: str, summary_b: str) -> str:
    prompt = (
        _load_prompt()
        .replace("{title_a}", title_a)
        .replace("{summary_a}", summary_a)
        .replace("{title_b}", title_b)
        .replace("{summary_b}", summary_b)
    )
    response = _client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def _parse_conflict_response(raw: str) -> dict:
    lines = {line.split(":")[0].strip(): line.split(":", 1)[1].strip()
             for line in raw.strip().splitlines() if ":" in line}
    return {
        "conflict": lines.get("CONFLICT", "NO").upper() == "YES",
        "confidence": lines.get("CONFIDENCE", "LOW").upper(),
        "description": lines.get("DESCRIPTION", "None"),
    }


async def run_conflict_check(db: AsyncSession, node_id: UUID, summary: str) -> None:
    """Embed node summary, find similar nodes, detect conflicts, create alerts."""
    from backend.models.wiki_node import WikiNode

    node_embedding = embed(summary)

    # Query top-5 similar nodes (excluding current node)
    result = await db.execute(
        select(WikiNode.id, WikiNode.title, WikiNode.summary)
        .where(WikiNode.id != node_id)
        .where(WikiNode.embedding.is_not(None))
        .order_by(WikiNode.embedding.cosine_distance(node_embedding))
        .limit(5)
    )
    similar_nodes = result.fetchall()

    if not similar_nodes:
        return

    # Get current node title for the prompt
    node_result = await db.execute(select(WikiNode).where(WikiNode.id == node_id))
    current_node = node_result.scalar_one_or_none()
    if not current_node:
        return

    for row in similar_nodes:
        if not row.summary:
            continue

        raw = _call_groq_conflict(
            title_a=current_node.title,
            summary_a=summary,
            title_b=row.title,
            summary_b=row.summary,
        )
        parsed = _parse_conflict_response(raw)

        if not parsed["conflict"] or parsed["confidence"] not in ("HIGH", "MEDIUM"):
            continue

        # Deduplication: skip if open alert already exists for this pair
        dup_result = await db.execute(
            select(Alert).where(
                and_(
                    Alert.source_node_id == node_id,
                    Alert.conflicting_node_id == row.id,
                    Alert.status == "open",
                )
            )
        )
        if dup_result.scalar_one_or_none():
            continue

        alert = Alert(
            source_node_id=node_id,
            conflicting_node_id=row.id,
            description=parsed["description"],
            confidence=parsed["confidence"],
        )
        db.add(alert)

    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_conflict_engine.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/conflict_engine.py tests/test_conflict_engine.py
git commit -m "feat: add conflict engine with pgvector similarity search and Groq detection"
```

---

### Task 5: Wire conflict engine into Celery task

**Files:**
- Modify: `backend/tasks/tasks.py`
- Modify: `backend/pipeline/processor.py`

- [ ] **Step 1: Update `backend/pipeline/processor.py` to embed node and return it**

```python
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from backend.db.postgres import async_session_factory
from backend.models.bookmark import Bookmark
from backend.models.wiki_node import WikiNode
from backend.pipeline.embedder import embed
from backend.pipeline.extractor import extract
from backend.pipeline.synthesizer import synthesize
from backend.pipeline.utils import extract_title_from_markdown, slugify
from backend.pipeline.wiki_writer import write_node


async def process_bookmark(bookmark_id: UUID, url_or_path: str) -> UUID | None:
    """Full pipeline: extract → synthesize → write → embed. Returns wiki node ID."""
    async with async_session_factory() as db:
        result = await db.execute(select(Bookmark).where(Bookmark.id == bookmark_id))
        bookmark = result.scalar_one()
        bookmark.status = "processing"
        await db.commit()

        try:
            content = await extract(url_or_path)
            bookmark.title = content.title
            bookmark.content_type = content.content_type

            initial_markdown = synthesize(content)
            title = extract_title_from_markdown(initial_markdown)
            slug = slugify(title)

            existing_result = await db.execute(
                select(WikiNode).where(WikiNode.slug == slug)
            )
            existing_node = existing_result.scalar_one_or_none()

            if existing_node and existing_node.file_path:
                existing_markdown = Path(existing_node.file_path).read_text()
                final_markdown = synthesize(content, existing_node=existing_markdown)
                final_title = extract_title_from_markdown(final_markdown)
                final_slug = slugify(final_title)
            else:
                final_markdown = initial_markdown
                final_title = title
                final_slug = slug

            node = await write_node(db, final_title, final_slug, final_markdown, bookmark_id)

            # Store embedding on the wiki node
            if node.summary:
                node.embedding = embed(node.summary)
                await db.commit()

            bookmark.status = "done"
            await db.commit()
            return node.id

        except Exception as e:
            bookmark.status = "failed"
            bookmark.error = str(e)
            await db.commit()
            return None
```

- [ ] **Step 2: Update `backend/tasks/tasks.py` to run conflict check after processing**

```python
import asyncio
from uuid import UUID

from backend.tasks.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_bookmark_task(self, bookmark_id: str, url: str) -> None:
    """Celery task: run full bookmark pipeline then conflict check."""
    from backend.pipeline.processor import process_bookmark
    from backend.pipeline.conflict_engine import run_conflict_check
    from backend.db.postgres import async_session_factory

    async def _run():
        node_id = await process_bookmark(UUID(bookmark_id), url)
        if node_id is None:
            return
        # Run conflict check in a fresh session
        async with async_session_factory() as db:
            node_result = await db.execute(
                __import__("sqlalchemy", fromlist=["select"]).select(
                    __import__("backend.models.wiki_node", fromlist=["WikiNode"]).WikiNode
                ).where(
                    __import__("backend.models.wiki_node", fromlist=["WikiNode"]).WikiNode.id == node_id
                )
            )
            node = node_result.scalar_one_or_none()
            if node and node.summary:
                await run_conflict_check(db, node_id=node_id, summary=node.summary)

    try:
        asyncio.run(_run())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
```

Wait — the above has messy imports. Use this cleaner version instead:

```python
import asyncio
from uuid import UUID

from backend.tasks.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_bookmark_task(self, bookmark_id: str, url: str) -> None:
    """Celery task: run full bookmark pipeline then conflict check."""
    try:
        asyncio.run(_pipeline(bookmark_id, url))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


async def _pipeline(bookmark_id: str, url: str) -> None:
    from sqlalchemy import select

    from backend.db.postgres import async_session_factory
    from backend.models.wiki_node import WikiNode
    from backend.pipeline.conflict_engine import run_conflict_check
    from backend.pipeline.processor import process_bookmark

    node_id = await process_bookmark(UUID(bookmark_id), url)
    if node_id is None:
        return

    async with async_session_factory() as db:
        result = await db.execute(select(WikiNode).where(WikiNode.id == node_id))
        node = result.scalar_one_or_none()
        if node and node.summary:
            await run_conflict_check(db, node_id=node_id, summary=node.summary)
```

- [ ] **Step 3: Run existing tests to verify nothing is broken**

```bash
.venv/bin/pytest tests/ -v
```

Expected: All existing tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/pipeline/processor.py backend/tasks/tasks.py
git commit -m "feat: wire conflict engine into Celery pipeline after wiki node write"
```

---

### Task 6: Create alerts API routes

**Files:**
- Create: `backend/api/routes/alerts.py`
- Modify: `backend/api/main.py`
- Create: `tests/test_alerts_routes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_alerts_routes.py
import pytest
from httpx import AsyncClient, ASGITransport
from uuid import uuid4


@pytest.mark.asyncio
async def test_list_alerts_empty():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/alerts")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_resolve_alert_not_found():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/alerts/{uuid4()}/resolve",
            json={"status": "resolved"},
        )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_alerts_routes.py -v
```

Expected: FAIL — `/alerts` route not found

- [ ] **Step 3: Create `backend/api/routes/alerts.py`**

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_db
from backend.models.alert import Alert

router = APIRouter()


class ResolveIn(BaseModel):
    status: str  # 'resolved' | 'accepted_tension'


@router.get("/alerts")
async def list_alerts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Alert).order_by(Alert.created_at.desc())
    )
    alerts = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "source_node_id": str(a.source_node_id),
            "conflicting_node_id": str(a.conflicting_node_id),
            "description": a.description,
            "confidence": a.confidence,
            "status": a.status,
            "created_at": a.created_at.isoformat(),
        }
        for a in alerts
    ]


@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {
        "id": str(alert.id),
        "source_node_id": str(alert.source_node_id),
        "conflicting_node_id": str(alert.conflicting_node_id),
        "description": alert.description,
        "confidence": alert.confidence,
        "status": alert.status,
        "created_at": alert.created_at.isoformat(),
    }


@router.patch("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: UUID,
    body: ResolveIn,
    db: AsyncSession = Depends(get_db),
):
    if body.status not in ("resolved", "accepted_tension"):
        raise HTTPException(status_code=400, detail="status must be 'resolved' or 'accepted_tension'")

    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = body.status
    await db.commit()
    return {"id": str(alert.id), "status": alert.status}
```

- [ ] **Step 4: Register the alerts router in `backend/api/main.py`**

Open `backend/api/main.py` and add:
```python
from backend.api.routes.alerts import router as alerts_router
app.include_router(alerts_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_alerts_routes.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/api/routes/alerts.py backend/api/main.py tests/test_alerts_routes.py
git commit -m "feat: add /alerts CRUD endpoints"
```

---

### Task 7: End-to-end verification

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 2: Start stack and submit two contradicting bookmarks**

```bash
docker-compose up -d
.venv/bin/uvicorn backend.api.main:app --reload --port 8000 &
.venv/bin/celery -A backend.tasks.celery_app worker --loglevel=info &

curl -s -X POST http://localhost:8000/bookmarks/bulk \
  -H "Content-Type: application/json" \
  -d '{"urls": [
    "https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture",
    "https://www.langchain.com/blog/tuning-deep-agents-different-models"
  ]}'
```

- [ ] **Step 3: Wait for processing and check alerts**

```bash
sleep 60
curl -s http://localhost:8000/alerts | python3 -m json.tool
```

Expected: List of alerts (may be empty if no contradictions found — that's correct behaviour).

- [ ] **Step 4: Verify GET /alerts/{id} works**

```bash
ALERT_ID=$(curl -s http://localhost:8000/alerts | python3 -c "import sys,json; data=json.load(sys.stdin); print(data[0]['id']) if data else print('')")
[ -n "$ALERT_ID" ] && curl -s http://localhost:8000/alerts/$ALERT_ID | python3 -m json.tool
```

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: Feature 2 Conflict Engine complete"
```
