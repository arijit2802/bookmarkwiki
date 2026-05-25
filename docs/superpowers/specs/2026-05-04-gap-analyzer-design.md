# DKE Design Spec — Feature 3: Semantic Gap Analyzer
**Date:** 2026-05-04
**Status:** Approved (updated: Celery replaced with SQL job queue + asyncio worker)

---

## 1. Problem Statement

The wiki compiler builds knowledge from what the user has already bookmarked, but gives no signal about what they're missing. The Semantic Gap Analyzer maps the user's existing wiki against an LLM-generated domain taxonomy, identifies uncovered topics, scores them by learning priority, and generates an ordered learning path — turning unknown unknowns into an actionable research agenda.

---

## 2. Scope

### In scope
- Groq infers the user's domain from existing wiki nodes and generates a full topic taxonomy
- pgvector cosine similarity maps wiki nodes against taxonomy topics (gap threshold: similarity < 0.75)
- Gap scoring based on personal context: adjacency to strong knowledge clusters + wiki link frequency
- Groq generates recommended reading (2-3 search queries per gap) and an ordered learning path
- Auto-trigger: gap analysis runs automatically after every N successfully processed bookmarks (default N=10, configurable via env var)
- On-demand trigger: `POST /gaps/analyze`
- Auto-trigger inserts a job record into `gap_analysis_jobs` table — decoupled from the bookmark BackgroundTask
- A lightweight asyncio worker (started at FastAPI lifespan) polls `gap_analysis_jobs` and runs analysis out-of-band
- `SELECT FOR UPDATE SKIP LOCKED` prevents duplicate concurrent runs even with multiple FastAPI workers

### Out of scope
- Industry signal scoring (external RSS/arxiv/trends) — future enhancement
- Gap Auto-Population (auto-search + scrape to fill gaps) — Feature 5
- Frontend gaps compass UI — Feature 4
- Email/webhook notifications for new gaps — future

---

## 3. Architecture

```
processor.py (FastAPI BackgroundTask)
  ├─ extract → synthesize → write wiki node → embed + conflict check  [existing]
  ├─ mark bookmark status=done                                         [existing]
  └─ query COUNT(done bookmarks) — if count % N == 0                  [NEW]
       └─ INSERT INTO gap_analysis_jobs (status='pending')            [NEW]
          ON CONFLICT DO NOTHING  ← deduplication via unique index

gap_analysis_worker (asyncio.create_task in FastAPI lifespan)        [NEW]
  ├─ poll every 5s
  ├─ UPDATE gap_analysis_jobs SET status='running'
  │    WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED)
  └─ if job claimed → await run_gap_analysis(db)
       ├─ collect all wiki node titles + summaries
       ├─ Groq: infer domain + generate full taxonomy
       ├─ for each taxonomy topic → pgvector similarity search
       │    └─ cosine similarity < 0.75 → mark as GAP
       ├─ score gaps (adjacency + wiki link frequency)
       ├─ Groq: generate learning path + recommended reading per gap
       ├─ upsert gaps table in PostgreSQL
       └─ UPDATE gap_analysis_jobs SET status='done' | 'failed'
```

No extra infrastructure. Uses only PostgreSQL (already in place). The bookmark BackgroundTask returns as soon as it inserts the job row — gap analysis runs fully decoupled in the worker loop.

---

## 4. Data Model

### New `gaps` table
```sql
CREATE TABLE gaps (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  topic           TEXT NOT NULL,        -- e.g. "LLM Evaluation Frameworks"
  domain          TEXT NOT NULL,        -- e.g. "LLM Engineering"
  score           FLOAT,                -- 0.0–1.0, higher = higher priority
  score_reasons   JSONB,                -- { "adjacency": 0.8, "link_frequency": 0.6 }
  recommended     TEXT[] NOT NULL DEFAULT '{}',  -- 2-3 search queries / article suggestions
  learning_path   TEXT[] NOT NULL DEFAULT '{}',  -- ordered list of gap topics to tackle before this one
  status          TEXT DEFAULT 'open',  -- 'open' | 'filled'
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
);
```

### New `gap_analysis_jobs` table
```sql
CREATE TABLE gap_analysis_jobs (
  id           SERIAL PRIMARY KEY,
  status       TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
  triggered_at TIMESTAMPTZ DEFAULT now(),
  started_at   TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  error        TEXT
);

-- Prevent queuing a second job while one is already pending or running
CREATE UNIQUE INDEX gap_jobs_one_active
  ON gap_analysis_jobs (status)
  WHERE status IN ('pending', 'running');
```

The unique partial index is the deduplication mechanism — an `INSERT ... ON CONFLICT DO NOTHING` from `processor.py` is a no-op if a job is already queued or running.

Gap analysis reads from `wiki_nodes` and `bookmarks`. No other table changes.

---

## 5. Gap Detection Design

### Trigger
After each bookmark reaches `status=done`, `processor.py` queries:
```sql
SELECT COUNT(*) FROM bookmarks WHERE status = 'done'
```
If `count % N == 0` → inserts a job row and returns immediately (does not block the bookmark task):
```python
await db.execute(text("""
    INSERT INTO gap_analysis_jobs (status)
    VALUES ('pending')
    ON CONFLICT DO NOTHING
"""))
await db.commit()
```
N is configurable via `GAP_ANALYSIS_THRESHOLD` env var (default: 10).

### Worker
`gap_analysis_worker()` is an `asyncio.Task` started in FastAPI's lifespan. It polls every 5 seconds, claims one pending job atomically with `SELECT FOR UPDATE SKIP LOCKED`, runs `run_gap_analysis(db)`, then marks the job `done` or `failed`. Because the unique partial index prevents two active jobs, the worker will never run two gap analyses concurrently even with multiple FastAPI processes.

`POST /gaps/analyze` (manual trigger) uses the same `INSERT ... ON CONFLICT DO NOTHING` — the worker picks it up on the next poll.

### Domain + taxonomy generation prompt (`prompts/taxonomy.md`)
```
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
Output ONLY the JSON. No preamble.
```

### Coverage check (pgvector)
For each taxonomy topic, generate its embedding via sentence-transformers, then query:
```sql
SELECT MAX(1 - (embedding <=> :topic_embedding)) as best_similarity
FROM wiki_nodes
WHERE embedding IS NOT NULL;
```
If `best_similarity < 0.75` → topic is a GAP.

### Gap scoring
```
score = (adjacency_score × 0.6) + (link_frequency_score × 0.4)

adjacency_score:   cosine similarity of gap topic to user's strongest wiki cluster centroid
link_frequency:    count of [[wiki links]] in existing nodes referencing this topic / max count
```

### Learning path + recommended reading prompt (`prompts/learning_path.md`)
```
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
Output ONLY the JSON. No preamble.
```

---

## 6. API Endpoints

```
GET   /gaps                  List all gaps ordered by score descending (default: status=open)
POST  /gaps/analyze          Trigger gap analysis on-demand
PATCH /gaps/{id}/fill        Mark gap as 'filled'
```

---

## 7. New Files & Changes

| File | Type | Purpose |
|---|---|---|
| `backend/pipeline/gap_analyzer.py` | New | Domain inference, taxonomy generation, coverage mapping, gap scoring, learning path |
| `backend/models/gap.py` | New | SQLAlchemy Gap model |
| `backend/models/gap_analysis_job.py` | New | SQLAlchemy GapAnalysisJob model |
| `backend/api/routes/gaps.py` | New | Gap CRUD endpoints + manual trigger |
| `backend/api/main.py` | Modified | Start `gap_analysis_worker` as asyncio task in lifespan |
| `backend/prompts/taxonomy.md` | New | Groq prompt to infer domain + generate taxonomy |
| `backend/prompts/learning_path.md` | New | Groq prompt to generate ordered learning path + recommended reading |
| `backend/pipeline/processor.py` | Modified | Add bookmark count check + insert `gap_analysis_jobs` row |
| `backend/config.py` | Modified | Add `GAP_ANALYSIS_THRESHOLD` env var (default: 10) |

---

## 8. Tech Stack

| Layer | Technology |
|---|---|
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (local, CPU) |
| Vector store | pgvector on Neon PostgreSQL |
| Domain inference + gap analysis LLM | Groq — `llama-3.3-70b-versatile` |
| Task queue | PostgreSQL `gap_analysis_jobs` table (no Redis / Celery) |
| Worker | `asyncio.create_task(gap_analysis_worker())` in FastAPI lifespan |
| Concurrency control | `SELECT FOR UPDATE SKIP LOCKED` + unique partial index |

---

## 9. Environment Variables

```
GAP_ANALYSIS_THRESHOLD=10   # trigger gap analysis every N processed bookmarks
```

---

## 10. Verification Checklist

1. Process 10 bookmarks → verify a row appears in `gap_analysis_jobs` with `status='pending'`
2. Wait 5–10s → verify job transitions to `status='done'` (worker picked it up)
3. `GET /gaps` → verify gaps list returned ordered by score descending
4. Verify gap topics are NOT already covered in `wiki_nodes` (no false positives)
5. Verify `score_reasons` JSONB contains `adjacency` + `link_frequency` values
6. Verify `recommended` array contains 2-3 search queries per gap
7. Verify `learning_path` array is ordered (foundational topics first)
8. `POST /gaps/analyze` → verify a new job row is inserted and picked up by the worker
9. Process bookmarks rapidly near a threshold → verify only one job is queued (deduplication via unique index)
10. `PATCH /gaps/{id}/fill` → verify status updated to `filled`
