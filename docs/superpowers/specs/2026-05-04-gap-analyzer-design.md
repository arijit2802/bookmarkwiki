# DKE Design Spec — Feature 3: Semantic Gap Analyzer
**Date:** 2026-05-04
**Status:** Approved

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
- Runs as a dedicated Celery task (dispatched from `processor.py` after threshold check)

### Out of scope
- Industry signal scoring (external RSS/arxiv/trends) — future enhancement
- Gap Auto-Population (auto-search + scrape to fill gaps) — Feature 5
- Frontend gaps compass UI — Feature 4
- Email/webhook notifications for new gaps — future

---

## 3. Architecture

```
processor.py (Celery task)
  ├─ extract → synthesize → write wiki node → embed + conflict check  [existing]
  ├─ mark bookmark status=done                                         [existing]
  └─ query COUNT(done bookmarks) — if count % N == 0                  [NEW]
       └─ dispatch analyze_gaps Celery task                           [NEW]

analyze_gaps (Celery task in gap_analyzer.py)
  ├─ collect all wiki node titles + summaries
  ├─ Groq: infer domain + generate full taxonomy
  ├─ for each taxonomy topic → pgvector similarity search
  │    └─ cosine similarity < 0.75 → mark as GAP
  ├─ score gaps (adjacency + wiki link frequency)
  ├─ Groq: generate learning path + recommended reading per gap
  └─ upsert gaps table in PostgreSQL
```

No new infrastructure services beyond Celery + Redis (Phase 0). Everything reads from existing `wiki_nodes` and `bookmarks` tables.

---

## 4. Data Model

### New `gaps` table
```sql
gaps (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  topic           TEXT NOT NULL,        -- e.g. "LLM Evaluation Frameworks"
  domain          TEXT NOT NULL,        -- e.g. "LLM Engineering"
  score           FLOAT,                -- 0.0–1.0, higher = higher priority
  score_reasons   JSONB,                -- { "adjacency": 0.8, "link_frequency": 0.6 }
  recommended     TEXT[],               -- 2-3 search queries / article suggestions
  learning_path   TEXT[],               -- ordered list of gap topics to tackle before this one
  status          TEXT DEFAULT 'open',  -- 'open' | 'filled'
  created_at      TIMESTAMP DEFAULT now(),
  updated_at      TIMESTAMP DEFAULT now()
)
```

No changes to existing tables. Gap analysis only reads from `wiki_nodes` and `bookmarks`.

---

## 5. Gap Detection Design

### Trigger
After each bookmark reaches `status=done`, `processor.py` queries:
```sql
SELECT COUNT(*) FROM bookmarks WHERE status = 'done'
```
If `count % N == 0` → dispatch `analyze_gaps` Celery task.
N is configurable via `GAP_ANALYSIS_THRESHOLD` env var (default: 10).

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
| `backend/api/routes/gaps.py` | New | Gap CRUD endpoints |
| `backend/prompts/taxonomy.md` | New | Groq prompt to infer domain + generate taxonomy |
| `backend/prompts/learning_path.md` | New | Groq prompt to generate ordered learning path + recommended reading |
| `backend/tasks/celery_app.py` | Modified | Add `analyze_gaps` Celery task |
| `backend/pipeline/processor.py` | Modified | Add bookmark count check + dispatch `analyze_gaps` |
| `backend/config.py` | Modified | Add `GAP_ANALYSIS_THRESHOLD` env var (default: 10) |

---

## 8. Tech Stack

| Layer | Technology |
|---|---|
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (local, CPU) |
| Vector store | pgvector on Neon PostgreSQL |
| Domain inference + gap analysis LLM | Groq — `llama-3.3-70b-versatile` |
| Task execution | Celery (dispatched from processor task) |
| Task broker | Redis (Upstash free tier in production) |

---

## 9. Environment Variables

```
GAP_ANALYSIS_THRESHOLD=10   # trigger gap analysis every N processed bookmarks
```

---

## 10. Verification Checklist

1. Process 10 bookmarks on LLM topics → verify `analyze_gaps` Celery task triggered automatically
2. `GET /gaps` → verify gaps list returned ordered by score descending
3. Verify gap topics are NOT already covered in `wiki_nodes` (no false positives)
4. Verify `score_reasons` JSONB contains `adjacency` + `link_frequency` values
5. Verify `recommended` array contains 2-3 search queries per gap
6. Verify `learning_path` array is ordered (foundational topics first)
7. `POST /gaps/analyze` → verify manual trigger works independently
8. `PATCH /gaps/{id}/fill` → verify status updated to `filled`
9. Process 20 bookmarks → verify gap analysis triggered at count=10 and count=20 (not both simultaneously)
