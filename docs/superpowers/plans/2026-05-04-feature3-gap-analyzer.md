# Feature 3: Semantic Gap Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After every N successfully processed bookmarks, automatically infer the user's knowledge domain via Groq, generate a full topic taxonomy, identify uncovered topics using pgvector similarity, score gaps by adjacency and link frequency, and generate an ordered learning path with recommended reading.

**Architecture:** `gap_analyzer.py` is a pure async module. After each bookmark reaches `status=done`, `processor.py` inserts a row into `gap_analysis_jobs` (returning immediately). A `gap_analysis_worker` asyncio task — started in FastAPI's lifespan — polls that table every 5 seconds, claims a pending job with `SELECT FOR UPDATE SKIP LOCKED`, and runs `run_gap_analysis(db)`. A unique partial index prevents duplicate concurrent runs. The gaps route exposes results and manual trigger via the same job insert.

**Tech Stack:** Groq `llama-3.3-70b-versatile`, pgvector, sentence-transformers, SQLAlchemy async, FastAPI lifespan worker

**Prerequisite:** Phase 0 and Feature 2 plans must be complete.

**Working directory:** `.worktrees/dke-phase1/dke`

---

### Task 1: Create Gap model and database table

**Files:**
- Create: `backend/models/gap.py`
- Create: `tests/test_gap_model.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_gap_model.py
def test_gap_model_columns():
    from backend.models.gap import Gap
    from sqlalchemy import inspect
    cols = {c.key for c in inspect(Gap).mapper.column_attrs}
    assert "id" in cols
    assert "topic" in cols
    assert "domain" in cols
    assert "score" in cols
    assert "score_reasons" in cols
    assert "recommended" in cols
    assert "learning_path" in cols
    assert "status" in cols


def test_gap_default_status():
    from backend.models.gap import Gap
    gap = Gap(topic="LLM Evaluation", domain="LLM Engineering")
    assert gap.status == "open"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_gap_model.py -v
```

Expected: FAIL — `backend.models.gap` not found

- [ ] **Step 3: Create `backend/models/gap.py`**

```python
from datetime import datetime, timezone
from uuid import uuid4, UUID

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres import Base


class Gap(Base):
    __tablename__ = "gaps"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_reasons: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recommended: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    learning_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 4: Create gaps table on Neon**

Connect to Neon and run:
```sql
CREATE TABLE IF NOT EXISTS gaps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  topic TEXT NOT NULL,
  domain TEXT NOT NULL,
  score FLOAT,
  score_reasons JSONB,
  recommended TEXT[] NOT NULL DEFAULT '{}',
  learning_path TEXT[] NOT NULL DEFAULT '{}',
  status VARCHAR(20) NOT NULL DEFAULT 'open',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_gap_model.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/models/gap.py tests/test_gap_model.py
git commit -m "feat: add Gap model and create gaps table"
```

---

### Task 2: Create Groq prompts for taxonomy and learning path

**Files:**
- Create: `backend/prompts/taxonomy.md`
- Create: `backend/prompts/learning_path.md`

- [ ] **Step 1: Create `backend/prompts/taxonomy.md`**

```markdown
You are a knowledge mapping assistant.

Here are the titles and summaries of a user's personal knowledge base:
{wiki_node_summaries}

1. Infer the primary domain this person is studying (e.g. "LLM Engineering", "DevOps", "Product Management").
2. Generate a comprehensive taxonomy of that domain — all major topics and sub-topics a practitioner should know.

Output as JSON:
{
  "domain": "...",
  "taxonomy": ["topic 1", "topic 2", ...]
}
Output ONLY the JSON. No preamble. No explanation.
```

- [ ] **Step 2: Create `backend/prompts/learning_path.md`**

```markdown
Given these knowledge gaps in the domain "{domain}":
{gap_topics}

And the user's existing knowledge:
{wiki_node_titles}

1. Order the gaps from foundational to advanced (what to learn first).
2. For each gap, suggest 2-3 specific search queries to find good learning resources.

Output as JSON:
{
  "learning_path": ["gap topic in order", ...],
  "recommendations": {
    "gap topic": ["search query 1", "search query 2"],
    ...
  }
}
Output ONLY the JSON. No preamble. No explanation.
```

- [ ] **Step 3: Verify prompts load**

```bash
.venv/bin/python3 -c "
from pathlib import Path
t = Path('backend/prompts/taxonomy.md').read_text()
l = Path('backend/prompts/learning_path.md').read_text()
assert '{wiki_node_summaries}' in t
assert '{domain}' in l
assert '{gap_topics}' in l
print('Prompts OK')
"
```

Expected: `Prompts OK`

- [ ] **Step 4: Commit**

```bash
git add backend/prompts/taxonomy.md backend/prompts/learning_path.md
git commit -m "feat: add taxonomy and learning path Groq prompts"
```

---

### Task 3: Create gap analyzer module

**Files:**
- Create: `backend/pipeline/gap_analyzer.py`
- Create: `tests/test_gap_analyzer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gap_analyzer.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_parse_taxonomy_response_valid():
    from backend.pipeline.gap_analyzer import _parse_taxonomy_response
    raw = '{"domain": "LLM Engineering", "taxonomy": ["RAG", "Fine-tuning", "Evaluation"]}'
    result = _parse_taxonomy_response(raw)
    assert result["domain"] == "LLM Engineering"
    assert "RAG" in result["taxonomy"]


def test_parse_taxonomy_response_with_markdown_fence():
    from backend.pipeline.gap_analyzer import _parse_taxonomy_response
    raw = '```json\n{"domain": "DevOps", "taxonomy": ["CI/CD", "Docker"]}\n```'
    result = _parse_taxonomy_response(raw)
    assert result["domain"] == "DevOps"


def test_parse_learning_path_response_valid():
    from backend.pipeline.gap_analyzer import _parse_learning_path_response
    raw = '{"learning_path": ["Evaluation", "Alignment"], "recommendations": {"Evaluation": ["LLM eval frameworks tutorial"]}}'
    result = _parse_learning_path_response(raw)
    assert result["learning_path"][0] == "Evaluation"
    assert "Evaluation" in result["recommendations"]


@pytest.mark.asyncio
async def test_run_gap_analysis_no_nodes(mocker):
    """When no wiki nodes exist, gap analysis returns early."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )
    from backend.pipeline.gap_analyzer import run_gap_analysis
    await run_gap_analysis(mock_db)
    # Groq should not be called when there are no nodes
    mock_db.add.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_gap_analyzer.py -v
```

Expected: FAIL — `backend.pipeline.gap_analyzer` not found

- [ ] **Step 3: Create `backend/pipeline/gap_analyzer.py`**

```python
import json
import re
from pathlib import Path

from openai import OpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.gap import Gap
from backend.models.wiki_node import WikiNode
from backend.pipeline.embedder import embed

_client = OpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_SIMILARITY_THRESHOLD = 0.75  # topics below this cosine similarity are gaps


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text()


def _call_groq(prompt: str) -> str:
    response = _client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def _strip_json_fence(raw: str) -> str:
    """Remove ```json ... ``` fences if present."""
    return re.sub(r"^```(?:json)?\n?|```$", "", raw.strip(), flags=re.MULTILINE).strip()


def _parse_taxonomy_response(raw: str) -> dict:
    return json.loads(_strip_json_fence(raw))


def _parse_learning_path_response(raw: str) -> dict:
    return json.loads(_strip_json_fence(raw))


def _score_gap(topic: str, node_titles: list[str], linked_slugs_flat: list[str]) -> tuple[float, dict]:
    """Score a gap topic: adjacency to existing knowledge + wiki link frequency."""
    topic_embedding = embed(topic)

    # Adjacency: average similarity to all existing node embeddings (approximated by title match)
    topic_lower = topic.lower()
    adjacency = sum(1 for t in node_titles if any(word in t.lower() for word in topic_lower.split())) / max(len(node_titles), 1)
    adjacency = min(adjacency * 3, 1.0)  # normalize

    # Link frequency: how often this topic appears in existing [[wiki links]]
    link_count = sum(1 for slug in linked_slugs_flat if topic_lower.replace(" ", "-") in slug)
    link_freq = min(link_count / max(len(node_titles), 1), 1.0)

    score = round((adjacency * 0.6) + (link_freq * 0.4), 4)
    return score, {"adjacency": round(adjacency, 4), "link_frequency": round(link_freq, 4)}


async def run_gap_analysis(db: AsyncSession) -> None:
    """Infer domain, build taxonomy, detect gaps, score them, generate learning path."""
    # Fetch all wiki nodes
    result = await db.execute(select(WikiNode))
    nodes = result.scalars().all()

    if not nodes:
        return

    # Build input for taxonomy prompt
    summaries_text = "\n".join(
        f"- {n.title}: {n.summary[:150] if n.summary else 'No summary'}"
        for n in nodes
    )
    node_titles = [n.title for n in nodes]

    # Collect all linked_slugs for link frequency scoring
    linked_slugs_flat: list[str] = []
    for n in nodes:
        if n.linked_slugs:
            linked_slugs_flat.extend(n.linked_slugs)

    # Step 1: Infer domain + generate taxonomy
    taxonomy_prompt = _load_prompt("taxonomy.md").replace("{wiki_node_summaries}", summaries_text)
    taxonomy_raw = _call_groq(taxonomy_prompt)
    taxonomy_data = _parse_taxonomy_response(taxonomy_raw)
    domain = taxonomy_data["domain"]
    taxonomy_topics = taxonomy_data["taxonomy"]

    # Step 2: Find gaps (topics with no similar wiki node above threshold)
    gap_topics: list[str] = []
    for topic in taxonomy_topics:
        topic_embedding = embed(topic)
        sim_result = await db.execute(
            select(func.max(1 - WikiNode.embedding.cosine_distance(topic_embedding)))
            .where(WikiNode.embedding.is_not(None))
        )
        best_similarity = sim_result.scalar() or 0.0
        if best_similarity < _SIMILARITY_THRESHOLD:
            gap_topics.append(topic)

    if not gap_topics:
        return

    # Step 3: Generate learning path + recommended reading
    lp_prompt = (
        _load_prompt("learning_path.md")
        .replace("{domain}", domain)
        .replace("{gap_topics}", "\n".join(f"- {t}" for t in gap_topics))
        .replace("{wiki_node_titles}", "\n".join(f"- {t}" for t in node_titles))
    )
    lp_raw = _call_groq(lp_prompt)
    lp_data = _parse_learning_path_response(lp_raw)
    learning_path = lp_data.get("learning_path", gap_topics)
    recommendations = lp_data.get("recommendations", {})

    # Step 4: Upsert gaps
    for topic in gap_topics:
        score, score_reasons = _score_gap(topic, node_titles, linked_slugs_flat)
        recommended = recommendations.get(topic, [])
        lp_position = [t for t in learning_path if t != topic]  # topics to learn before this one

        # Check if gap already exists
        existing = await db.execute(
            select(Gap).where(Gap.topic == topic).where(Gap.status == "open")
        )
        existing_gap = existing.scalar_one_or_none()

        if existing_gap:
            existing_gap.score = score
            existing_gap.score_reasons = score_reasons
            existing_gap.recommended = recommended
            existing_gap.learning_path = lp_position
        else:
            gap = Gap(
                topic=topic,
                domain=domain,
                score=score,
                score_reasons=score_reasons,
                recommended=recommended,
                learning_path=lp_position,
            )
            db.add(gap)

    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_gap_analyzer.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/gap_analyzer.py tests/test_gap_analyzer.py
git commit -m "feat: add gap analyzer with domain inference, coverage mapping, and learning path"
```

---

### Task 4: SQL job queue — GapAnalysisJob model, worker, and processor trigger

**Files:**
- Create: `backend/models/gap_analysis_job.py`
- Modify: `backend/pipeline/processor.py`
- Modify: `backend/api/main.py`
- Create: `tests/test_gap_trigger.py`

- [ ] **Step 1: Create `gap_analysis_jobs` table on Neon**

Connect to Neon and run:
```sql
CREATE TABLE IF NOT EXISTS gap_analysis_jobs (
  id           SERIAL PRIMARY KEY,
  status       TEXT NOT NULL DEFAULT 'pending',
  triggered_at TIMESTAMPTZ DEFAULT now(),
  started_at   TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  error        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS gap_jobs_one_active
  ON gap_analysis_jobs (status)
  WHERE status IN ('pending', 'running');
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_gap_trigger.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch


def test_gap_analysis_job_model_columns():
    from backend.models.gap_analysis_job import GapAnalysisJob
    from sqlalchemy import inspect
    cols = {c.key for c in inspect(GapAnalysisJob).mapper.column_attrs}
    assert {"id", "status", "triggered_at", "started_at", "completed_at", "error"} <= cols


@pytest.mark.asyncio
async def test_maybe_trigger_inserts_job_at_threshold(mocker):
    mock_execute = AsyncMock()
    mock_db = AsyncMock()
    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()

    from backend.pipeline.processor import _maybe_trigger_gap_analysis
    await _maybe_trigger_gap_analysis(mock_db, done_count=10, threshold=10)

    mock_execute.assert_called_once()
    call_text = str(mock_execute.call_args)
    assert "gap_analysis_jobs" in call_text


@pytest.mark.asyncio
async def test_maybe_trigger_no_insert_below_threshold(mocker):
    mock_db = AsyncMock()

    from backend.pipeline.processor import _maybe_trigger_gap_analysis
    await _maybe_trigger_gap_analysis(mock_db, done_count=7, threshold=10)

    mock_db.execute.assert_not_called()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_gap_trigger.py -v
```

Expected: FAIL — `GapAnalysisJob` model and `_maybe_trigger_gap_analysis` don't exist yet

- [ ] **Step 4: Create `backend/models/gap_analysis_job.py`**

```python
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.postgres import Base


class GapAnalysisJob(Base):
    __tablename__ = "gap_analysis_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 5: Add `_maybe_trigger_gap_analysis` to `backend/pipeline/processor.py`**

Add this function (call it after marking bookmark `done`):
```python
from sqlalchemy import func, select, text

async def _maybe_trigger_gap_analysis(db: AsyncSession, done_count: int, threshold: int) -> None:
    if threshold > 0 and done_count % threshold == 0:
        await db.execute(text("""
            INSERT INTO gap_analysis_jobs (status)
            VALUES ('pending')
            ON CONFLICT DO NOTHING
        """))
        await db.commit()
```

In the main `process_bookmark` function, after the bookmark is marked `done`:
```python
count_result = await db.execute(
    select(func.count()).where(Bookmark.status == "done")
)
done_count = count_result.scalar() or 0
await _maybe_trigger_gap_analysis(db, done_count, settings.gap_analysis_threshold)
```

- [ ] **Step 6: Add `gap_analysis_worker` and wire into lifespan in `backend/api/main.py`**

```python
import asyncio
import logging
from sqlalchemy import text
from backend.db.postgres import async_session_factory

logger = logging.getLogger(__name__)

async def gap_analysis_worker() -> None:
    """Poll gap_analysis_jobs every 5s; claim and run one job at a time."""
    while True:
        try:
            async with async_session_factory() as db:
                result = await db.execute(text("""
                    UPDATE gap_analysis_jobs
                    SET status = 'running', started_at = now()
                    WHERE id = (
                        SELECT id FROM gap_analysis_jobs
                        WHERE status = 'pending'
                        ORDER BY id
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING id
                """))
                job_id = result.scalar_one_or_none()
                await db.commit()

                if job_id:
                    try:
                        from backend.pipeline.gap_analyzer import run_gap_analysis
                        await run_gap_analysis(db)
                        await db.execute(text(
                            "UPDATE gap_analysis_jobs SET status='done', completed_at=now() WHERE id=:id"
                        ), {"id": job_id})
                    except Exception as exc:
                        logger.exception("Gap analysis failed for job %s", job_id)
                        await db.execute(text(
                            "UPDATE gap_analysis_jobs SET status='failed', error=:err WHERE id=:id"
                        ), {"err": str(exc), "id": job_id})
                    await db.commit()
        except Exception:
            logger.exception("gap_analysis_worker error")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    worker_task = asyncio.create_task(gap_analysis_worker())
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_gap_trigger.py -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/models/gap_analysis_job.py backend/pipeline/processor.py backend/api/main.py tests/test_gap_trigger.py
git commit -m "feat: SQL job queue for gap analysis — GapAnalysisJob model, worker, processor trigger"
```

---

### Task 5: Create gaps API routes

**Files:**
- Create: `backend/api/routes/gaps.py`
- Modify: `backend/api/main.py`
- Create: `tests/test_gaps_routes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gaps_routes.py
import pytest
from httpx import AsyncClient, ASGITransport
from uuid import uuid4


@pytest.mark.asyncio
async def test_list_gaps_empty():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/gaps")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_fill_gap_not_found():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(f"/gaps/{uuid4()}/fill")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trigger_gap_analysis_inserts_job(mocker):
    mock_execute = mocker.AsyncMock()
    mocker.patch("backend.api.routes.gaps.AsyncSession.execute", mock_execute)
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/gaps/analyze")
    assert resp.status_code == 200
    assert resp.json() == {"status": "queued"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_gaps_routes.py -v
```

Expected: FAIL — `/gaps` route not found

- [ ] **Step 3: Create `backend/api/routes/gaps.py`**

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_db
from backend.models.gap import Gap

router = APIRouter()


@router.get("/gaps")
async def list_gaps(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Gap).order_by(Gap.score.desc().nulls_last())
    )
    gaps = result.scalars().all()
    return [
        {
            "id": str(g.id),
            "topic": g.topic,
            "domain": g.domain,
            "score": g.score,
            "score_reasons": g.score_reasons,
            "recommended": g.recommended,
            "learning_path": g.learning_path,
            "status": g.status,
            "created_at": g.created_at.isoformat(),
        }
        for g in gaps
    ]


@router.post("/gaps/analyze")
async def trigger_gap_analysis(db: AsyncSession = Depends(get_db)):
    """Insert a pending job — the background worker picks it up within 5s."""
    await db.execute(text("""
        INSERT INTO gap_analysis_jobs (status)
        VALUES ('pending')
        ON CONFLICT DO NOTHING
    """))
    await db.commit()
    return {"status": "queued"}


@router.patch("/gaps/{gap_id}/fill")
async def fill_gap(gap_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Gap).where(Gap.id == gap_id))
    gap = result.scalar_one_or_none()
    if not gap:
        raise HTTPException(status_code=404, detail="Gap not found")
    gap.status = "filled"
    await db.commit()
    return {"id": str(gap.id), "status": gap.status}
```

- [ ] **Step 4: Register gaps router in `backend/api/main.py`**

Add to `backend/api/main.py`:
```python
from backend.api.routes.gaps import router as gaps_router
app.include_router(gaps_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_gaps_routes.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/api/routes/gaps.py backend/api/main.py tests/test_gaps_routes.py
git commit -m "feat: add /gaps CRUD endpoints with manual trigger"
```

---

### Task 6: End-to-end verification

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 2: Process 10+ bookmarks and verify gap analysis auto-triggers**

```bash
docker-compose up -d
.venv/bin/uvicorn backend.api.main:app --reload --port 8000 &
# No separate worker needed — gap_analysis_worker starts automatically in FastAPI lifespan

# Submit 10 bookmarks (use varied URLs for good taxonomy)
curl -s -X POST http://localhost:8000/bookmarks/bulk \
  -H "Content-Type: application/json" \
  -d '{"urls": [
    "https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture",
    "https://www.langchain.com/blog/tuning-deep-agents-different-models",
    "https://www.langchain.com/blog/running-subagents-in-the-background",
    "https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture",
    "https://www.langchain.com/blog/tuning-deep-agents-different-models",
    "https://www.langchain.com/blog/running-subagents-in-the-background",
    "https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture",
    "https://www.langchain.com/blog/tuning-deep-agents-different-models",
    "https://www.langchain.com/blog/running-subagents-in-the-background",
    "https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture"
  ]}'
```

- [ ] **Step 3: Verify job was picked up and check gaps**

```bash
# Check the job table — should show status='done' within ~10s
curl -s http://localhost:8000/bookmarks | python3 -m json.tool  # confirm bookmarks done

sleep 10
curl -s http://localhost:8000/gaps | python3 -m json.tool
```

Expected: `gap_analysis_jobs` row transitions `pending → running → done`. Gaps list shows `topic`, `domain`, `score`, `recommended`, `learning_path`.

- [ ] **Step 4: Test manual trigger**

```bash
curl -s -X POST http://localhost:8000/gaps/analyze
```

Expected: `{"status": "queued"}`

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: Feature 3 Semantic Gap Analyzer complete"
```
