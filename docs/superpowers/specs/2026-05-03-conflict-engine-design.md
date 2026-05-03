# DKE Design Spec — Feature 2: Conflict & Friction Engine
**Date:** 2026-05-03
**Status:** Approved

---

## 1. Problem Statement

The wiki compiler (Phase 1) creates and merges nodes but has no awareness of contradictions between sources. Two articles may make opposing claims about the same topic and both get silently merged. The Conflict & Friction Engine detects these contradictions and surfaces them as Dialectical Alerts, forcing the user to reconcile conflicting knowledge rather than passively accumulate it.

---

## 2. Scope

### In scope
- Generate and store embeddings for wiki nodes using sentence-transformers (`all-MiniLM-L6-v2`)
- Store embeddings in Neon PostgreSQL via pgvector extension (no ChromaDB)
- Similarity search: find top-5 most semantically similar nodes for each new node
- Conflict detection: Groq (Llama 3.3 70B) compares node pairs and identifies contradictions
- Alert creation: persist conflicts as `alerts` records in PostgreSQL
- Alert API: list, view, and resolve alerts
- Runs as additional steps inside existing FastAPI background task pipeline (no Celery)

### Out of scope
- Email/webhook notifications for alerts (future)
- Frontend alert dashboard (Feature 4)
- Celery task queue (added only if volume exceeds ~200 concurrent bookmarks)

---

## 3. Architecture

```
processor.py (existing background task)
  ├─ extract content                            [existing]
  ├─ synthesize wiki node                       [existing]
  ├─ write .md + upsert wiki_nodes in DB        [existing]
  ├─ embed node summary (sentence-transformers) → store in wiki_nodes.embedding  [NEW]
  ├─ query top-5 similar nodes via pgvector cosine similarity                    [NEW]
  └─ for each similar pair → Groq conflict check → write Alert if found         [NEW]
```

No new infrastructure services. Everything runs against existing Neon PostgreSQL.

---

## 4. Data Model

### Migration: enable pgvector and add embedding column
```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE wiki_nodes ADD COLUMN embedding vector(384);
-- 384 dimensions matches all-MiniLM-L6-v2 output
```

### New `alerts` table
```sql
alerts (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_node_id      UUID REFERENCES wiki_nodes(id),
  conflicting_node_id UUID REFERENCES wiki_nodes(id),
  description         TEXT,        -- Groq's plain-English explanation of the contradiction
  confidence          TEXT,        -- 'HIGH' | 'MEDIUM'
  status              TEXT DEFAULT 'open',  -- 'open' | 'resolved' | 'accepted_tension'
  created_at          TIMESTAMP DEFAULT now()
)
```

---

## 5. Embedding Design

**Model:** `sentence-transformers/all-MiniLM-L6-v2`
- 80MB, CPU-only, no API key, runs in-process
- Output: 384-dimensional float vector
- Input: wiki node `summary` field (short description stored in `wiki_nodes.summary`)

**Similarity search query (pgvector cosine distance):**
```sql
SELECT id, title, summary
FROM wiki_nodes
WHERE id != :current_node_id
  AND embedding IS NOT NULL
ORDER BY embedding <=> :query_embedding
LIMIT 5;
```

---

## 6. Conflict Detection Design

### Groq prompt (`prompts/conflict.md`)
```
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

### Conflict threshold
Only create an alert if:
- `CONFLICT: YES`
- `CONFIDENCE: HIGH` or `MEDIUM`

LOW confidence conflicts are discarded to reduce noise.

### Deduplication
Before creating an alert, check if an `open` alert already exists for the same `(source_node_id, conflicting_node_id)` pair. Skip if duplicate.

---

## 7. API Endpoints

```
GET   /alerts                    List all alerts (default: status=open)
GET   /alerts/{id}               Single alert with both wiki node details
PATCH /alerts/{id}/resolve       Body: { "status": "resolved" | "accepted_tension" }
```

---

## 8. New Files & Changes

| File | Type | Purpose |
|---|---|---|
| `backend/pipeline/conflict_engine.py` | New | Embed node, similarity search, Groq conflict check, create alert |
| `backend/models/alert.py` | New | SQLAlchemy Alert model |
| `backend/api/routes/alerts.py` | New | Alert CRUD endpoints |
| `backend/prompts/conflict.md` | New | Groq conflict detection prompt template |
| `backend/pipeline/processor.py` | Modified | Add embed + conflict check steps after wiki write |
| `backend/models/wiki_node.py` | Modified | Add `embedding` vector(384) column |
| `backend/requirements.txt` | Modified | Add `sentence-transformers`, `pgvector` |

---

## 9. Tech Stack

| Layer | Technology |
|---|---|
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (local, CPU) |
| Vector store | pgvector on Neon PostgreSQL |
| Conflict detection LLM | Groq — `llama-3.3-70b-versatile` |
| Task execution | FastAPI background tasks (existing) |

---

## 10. Verification Checklist

1. Submit two bookmarks with known contradictory claims → verify `alerts` record created with `status=open`
2. Submit two bookmarks on unrelated topics → verify no alert created
3. Submit the same contradicting pair twice → verify no duplicate alert created
4. `GET /alerts` → verify alert appears with both node titles
5. `PATCH /alerts/{id}/resolve` with `"resolved"` → verify status updated
6. `PATCH /alerts/{id}/resolve` with `"accepted_tension"` → verify status updated
