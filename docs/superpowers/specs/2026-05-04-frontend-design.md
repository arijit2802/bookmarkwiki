# DKE Design Spec — Feature 4: Frontend + Web UI
**Date:** 2026-05-04
**Status:** Approved

---

## 1. Problem Statement

The DKE backend produces wiki nodes, conflict alerts, and knowledge gaps — but has no visual interface. Users currently rely on Obsidian to view the wiki and have no way to view or act on alerts and gaps. The Frontend replaces Obsidian as the primary interface, delivering the full dialectical experience in a single web application.

---

## 2. Scope

### In scope
- Knowledge graph: read-only React Flow visualization of wiki nodes + relationships
- Wiki node side panel: full `.md` content rendered as Markdown on node click
- Bookmarks view: submission form + status tracking table
- Alerts dashboard: conflict cards with Resolve / Accept Tension workflow
- Gaps compass: scored gap cards with recommended reading + learning path
- Single user, no authentication (auth added in future Feature 6)
- Nullable `user_id` fields added to all tables for future multi-user support
- Deployed on Vercel, frontend calls FastAPI backend directly

### Out of scope
- Authentication / multi-user (Feature 6)
- Gap Auto-Population UI (Feature 5)
- Mobile-specific layouts (responsive basics only)
- Dark mode
- Obsidian sync (replaced by this UI)

---

## 3. Architecture

```
Vercel (Next.js 15 App Router)
  ├─ /                    Knowledge Graph (React Flow, read-only)
  ├─ /bookmarks           Bookmark list + URL submission form
  ├─ /alerts              Dialectical alerts + resolve workflow
  └─ /gaps                Knowledge gaps compass + learning path

        ↓ fetch()
Railway (FastAPI backend)
  ├─ GET  /wiki/nodes          Graph nodes + linked_slugs as edges
  ├─ POST /bookmarks           Submit new bookmark
  ├─ GET  /bookmarks           Bookmark status list
  ├─ GET  /alerts              Conflict alerts
  ├─ PATCH /alerts/{id}/resolve
  ├─ GET  /gaps                Gap list ordered by score
  └─ POST /gaps/analyze        Trigger gap analysis on-demand
```

Frontend calls FastAPI directly via `fetch()` — no Next.js API route proxy.

---

## 4. Views & Components

### Knowledge Graph (`/`)
- React Flow canvas: wiki nodes as nodes, `[[wiki links]]` parsed into edges
- Click a node → `WikiPanel` slides in from the right showing full `.md` content rendered as Markdown
- Controls: zoom in/out, fit-to-view, search node by name
- Node colour coding:
  - Grey: standard node
  - Red: node has one or more open alerts
  - Yellow: node is referenced by an open gap

### Bookmarks (`/bookmarks`)
- URL input form at top → `POST /bookmarks` on submit
- Table: URL, title, status badge (pending / processing / done / failed)
- Failed rows show error message on hover

### Alerts (`/alerts`)
- One `AlertCard` per alert: source node title vs conflicting node title, contradiction description, confidence badge (HIGH / MEDIUM)
- Action buttons: **Resolve** / **Accept Tension** → `PATCH /alerts/{id}/resolve`
- Filter tabs: Open / Resolved / Accepted

### Gaps Compass (`/gaps`)
- `GapCard` per gap ordered by score descending: topic, domain, score bar, recommended search queries, learning path position
- **Trigger Analysis** button → `POST /gaps/analyze`
- Status badge: Open / Filled

---

## 5. Data Model Changes

### Backend: expose wiki links as edges
```sql
-- Add to wiki_nodes (populated by wiki_writer.py on each write)
ALTER TABLE wiki_nodes ADD COLUMN linked_slugs TEXT[];
-- e.g. ["rag-architecture", "multi-agent-systems"]
```

### Future multi-user: nullable user_id on all tables
```sql
ALTER TABLE wiki_nodes ADD COLUMN user_id UUID;
ALTER TABLE bookmarks  ADD COLUMN user_id UUID;
ALTER TABLE alerts     ADD COLUMN user_id UUID;
ALTER TABLE gaps       ADD COLUMN user_id UUID;
-- All nullable — unused in Feature 4, enforced in Feature 6
```

---

## 6. Tech Stack

| Layer | Technology |
|---|---|
| Framework | Next.js 15 (App Router) |
| Styling | Tailwind CSS + shadcn/ui |
| Graph | React Flow (read-only) |
| Markdown rendering | `react-markdown` |
| Data fetching | `fetch()` + React Server Components |
| Deployment | Vercel (auto-deploy on push to `main`) |

---

## 7. New Files

### Backend changes
| File | Type | Purpose |
|---|---|---|
| `backend/pipeline/wiki_writer.py` | Modified | Parse + store `[[wiki links]]` as `linked_slugs` |
| `backend/api/routes/wiki.py` | Modified | Include `linked_slugs` in `GET /wiki/nodes` response |
| `backend/models/wiki_node.py` | Modified | Add `linked_slugs`, `user_id` columns |
| `backend/models/bookmark.py` | Modified | Add `user_id` column |
| `backend/models/alert.py` | Modified | Add `user_id` column |
| `backend/models/gap.py` | Modified | Add `user_id` column |

### Frontend (new)
| File | Purpose |
|---|---|
| `frontend/app/page.tsx` | Knowledge graph view |
| `frontend/app/bookmarks/page.tsx` | Bookmark list + submit form |
| `frontend/app/alerts/page.tsx` | Alerts dashboard |
| `frontend/app/gaps/page.tsx` | Gaps compass |
| `frontend/components/KnowledgeGraph.tsx` | React Flow graph + node click handler |
| `frontend/components/WikiPanel.tsx` | Slide-in panel rendering wiki `.md` as Markdown |
| `frontend/components/AlertCard.tsx` | Alert card with resolve/accept buttons |
| `frontend/components/GapCard.tsx` | Gap card with score bar + recommendations |
| `frontend/lib/api.ts` | Typed fetch functions for all FastAPI endpoints |
| `frontend/package.json` | Next.js 15, React Flow, shadcn/ui, react-markdown |

---

## 8. Environment Variables

```
NEXT_PUBLIC_API_URL=https://your-railway-backend-url
```

---

## 9. Verification Checklist

1. Load `/` → verify React Flow graph renders all wiki nodes with edges between linked concepts
2. Click a node → verify `WikiPanel` slides in with rendered Markdown content
3. Node with open alert → verify it renders red; node linked to open gap → verify yellow
4. Load `/bookmarks` → submit a URL → verify it appears in table with `pending` status, transitions to `done`
5. Load `/alerts` → verify conflict cards show both node titles + contradiction description
6. Click **Resolve** on an alert → verify status updates to `resolved` and card moves to Resolved tab
7. Load `/gaps` → verify gaps ordered by score descending with recommended queries visible
8. Click **Trigger Analysis** → verify gaps list refreshes after analysis completes
9. Deploy to Vercel → verify all views load correctly against Railway backend
