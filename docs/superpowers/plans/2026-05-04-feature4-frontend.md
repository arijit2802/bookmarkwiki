# Feature 4: Frontend + Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Next.js 15 web dashboard with a read-only React Flow knowledge graph, alerts conflict resolution workflow, gaps compass, and bookmark submission — replacing Obsidian as the primary interface.

**Architecture:** Next.js 15 App Router on Vercel. React Server Components fetch data directly from the FastAPI backend. Client components handle interactivity (graph, resolve buttons). Backend gets two changes: `wiki_writer.py` parses `[[wiki links]]` into a `linked_slugs` column, and all models gain nullable `user_id` fields for future multi-user support.

**Tech Stack:** Next.js 15, TypeScript, Tailwind CSS, shadcn/ui, React Flow, react-markdown

**Prerequisite:** Phase 0, Feature 2, and Feature 3 plans must be complete.

**Working directory:** `.worktrees/dke-phase1` (frontend lives alongside the `dke/` backend folder)

---

### Task 1: Backend — add linked_slugs and user_id to models

**Files:**
- Modify: `dke/backend/models/wiki_node.py`
- Modify: `dke/backend/models/bookmark.py`
- Modify: `dke/backend/models/alert.py`
- Modify: `dke/backend/models/gap.py`
- Modify: `dke/backend/pipeline/wiki_writer.py`

- [ ] **Step 1: Write failing test for linked_slugs parsing**

Create `dke/tests/test_wiki_writer_links.py`:
```python
import pytest


def test_parse_wiki_links_extracts_slugs():
    from backend.pipeline.wiki_writer import _parse_linked_slugs
    markdown = "# RAG\nSee also [[Vector Database]] and [[Prompt Engineering]]."
    result = _parse_linked_slugs(markdown)
    assert "vector-database" in result
    assert "prompt-engineering" in result


def test_parse_wiki_links_empty():
    from backend.pipeline.wiki_writer import _parse_linked_slugs
    result = _parse_linked_slugs("# No links here")
    assert result == []


def test_parse_wiki_links_deduplicates():
    from backend.pipeline.wiki_writer import _parse_linked_slugs
    markdown = "[[RAG]] and [[RAG]] again."
    result = _parse_linked_slugs(markdown)
    assert result.count("rag") == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd dke && .venv/bin/pytest tests/test_wiki_writer_links.py -v
```

Expected: FAIL — `_parse_linked_slugs` not defined

- [ ] **Step 3: Add `_parse_linked_slugs` to `dke/backend/pipeline/wiki_writer.py`**

```python
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.wiki_node import WikiNode
from backend.pipeline.utils import slugify


def _parse_linked_slugs(markdown: str) -> list[str]:
    """Extract [[wiki link]] references as slugs."""
    raw_links = re.findall(r"\[\[([^\]]+)\]\]", markdown)
    seen = set()
    result = []
    for link in raw_links:
        slug = slugify(link)
        if slug not in seen:
            seen.add(slug)
            result.append(slug)
    return result


async def write_node(
    db: AsyncSession,
    title: str,
    slug: str,
    markdown: str,
    bookmark_id: UUID,
    wiki_dir=None,
) -> WikiNode:
    """Write or update a wiki node on disk and in the database."""
    from backend.config import settings

    wiki_dir = Path(wiki_dir) if wiki_dir is not None else Path(settings.wiki_dir)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    file_path = str(wiki_dir / f"{slug}.md")
    summary = markdown[:300]
    linked_slugs = _parse_linked_slugs(markdown)

    result = await db.execute(select(WikiNode).where(WikiNode.slug == slug))
    existing = result.scalar_one_or_none()

    if existing:
        existing.bookmark_ids = list({*existing.bookmark_ids, bookmark_id})
        existing.summary = summary
        existing.linked_slugs = linked_slugs
        existing.updated_at = datetime.now(timezone.utc)
        Path(file_path).write_text(markdown)
        await db.commit()
        await db.refresh(existing)
        return existing

    node = WikiNode(
        title=title,
        slug=slug,
        file_path=file_path,
        summary=summary,
        linked_slugs=linked_slugs,
        bookmark_ids=[bookmark_id],
    )
    db.add(node)
    Path(file_path).write_text(markdown)
    await db.commit()
    await db.refresh(node)
    return node
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_wiki_writer_links.py -v
```

Expected: PASS

- [ ] **Step 5: Add `linked_slugs` and `user_id` to `dke/backend/models/wiki_node.py`**

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
    linked_slugs: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 6: Add `user_id` to bookmark, alert, and gap models**

In `dke/backend/models/bookmark.py`, add after the `error` field:
```python
user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
```

In `dke/backend/models/alert.py`, add after the `created_at` field:
```python
user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
```

In `dke/backend/models/gap.py`, add after the `updated_at` field:
```python
user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
```

- [ ] **Step 7: Run migrations on Neon**

Connect to Neon and run:
```sql
ALTER TABLE wiki_nodes ADD COLUMN IF NOT EXISTS linked_slugs TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE wiki_nodes ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE bookmarks  ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE alerts     ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE gaps       ADD COLUMN IF NOT EXISTS user_id UUID;
```

- [ ] **Step 8: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add dke/backend/models/ dke/backend/pipeline/wiki_writer.py dke/tests/test_wiki_writer_links.py
git commit -m "feat: add linked_slugs parsing and nullable user_id to all models"
```

---

### Task 2: Backend — update wiki API to expose graph edges

**Files:**
- Modify: `dke/backend/api/routes/wiki.py`
- Create: `dke/tests/test_wiki_routes_graph.py`

- [ ] **Step 1: Read current wiki.py**

```bash
cat dke/backend/api/routes/wiki.py
```

- [ ] **Step 2: Write failing test**

```python
# dke/tests/test_wiki_routes_graph.py
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_wiki_nodes_includes_linked_slugs():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/wiki/nodes")
    assert resp.status_code == 200
    nodes = resp.json()
    # Each node must have linked_slugs field
    for node in nodes:
        assert "linked_slugs" in node
        assert isinstance(node["linked_slugs"], list)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd dke && .venv/bin/pytest tests/test_wiki_routes_graph.py -v
```

Expected: FAIL — `linked_slugs` not in response

- [ ] **Step 4: Update `GET /wiki/nodes` in `dke/backend/api/routes/wiki.py`**

Find the list_wiki_nodes function and update its return to include `linked_slugs`:
```python
return [
    {
        "id": str(n.id),
        "title": n.title,
        "slug": n.slug,
        "summary": n.summary,
        "linked_slugs": n.linked_slugs or [],
        "bookmark_ids": [str(b) for b in n.bookmark_ids],
        "updated_at": n.updated_at.isoformat(),
    }
    for n in nodes
]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_wiki_routes_graph.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add dke/backend/api/routes/wiki.py dke/tests/test_wiki_routes_graph.py
git commit -m "feat: include linked_slugs in GET /wiki/nodes response for graph edges"
```

---

### Task 3: Initialize Next.js 15 frontend project

**Files:**
- Create: `frontend/` directory with Next.js 15 app

- [ ] **Step 1: Scaffold Next.js 15 project**

```bash
cd .worktrees/dke-phase1
npx create-next-app@latest frontend \
  --typescript \
  --tailwind \
  --app \
  --no-src-dir \
  --import-alias "@/*"
```

When prompted:
- Would you like to use ESLint? → Yes
- Would you like to use Turbopack? → Yes

- [ ] **Step 2: Install additional dependencies**

```bash
cd frontend
npm install @xyflow/react react-markdown
```

- [ ] **Step 3: Initialize shadcn/ui**

```bash
npx shadcn@latest init
```

When prompted: Default style → Default, Base color → Slate, CSS variables → Yes.

- [ ] **Step 4: Add required shadcn components**

```bash
npx shadcn@latest add badge button card tabs input
```

- [ ] **Step 5: Create `.env.local`**

```bash
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
```

- [ ] **Step 6: Verify dev server starts**

```bash
npm run dev
```

Expected: `▲ Next.js 15.x.x` ready at `http://localhost:3000`

- [ ] **Step 7: Commit**

```bash
cd ..
git add frontend/
git commit -m "chore: scaffold Next.js 15 frontend with shadcn/ui and React Flow"
```

---

### Task 4: Create typed API client

**Files:**
- Create: `frontend/lib/api.ts`

- [ ] **Step 1: Create `frontend/lib/api.ts`**

```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface WikiNode {
  id: string;
  title: string;
  slug: string;
  summary: string | null;
  linked_slugs: string[];
  bookmark_ids: string[];
  updated_at: string;
}

export interface Bookmark {
  id: string;
  url: string;
  title: string | null;
  status: "pending" | "processing" | "done" | "failed";
}

export interface Alert {
  id: string;
  source_node_id: string;
  conflicting_node_id: string;
  description: string | null;
  confidence: "HIGH" | "MEDIUM";
  status: "open" | "resolved" | "accepted_tension";
  created_at: string;
}

export interface Gap {
  id: string;
  topic: string;
  domain: string;
  score: number | null;
  score_reasons: { adjacency: number; link_frequency: number } | null;
  recommended: string[];
  learning_path: string[];
  status: "open" | "filled";
  created_at: string;
}

export async function getWikiNodes(): Promise<WikiNode[]> {
  const res = await fetch(`${API_URL}/wiki/nodes`, { next: { revalidate: 30 } });
  if (!res.ok) throw new Error("Failed to fetch wiki nodes");
  return res.json();
}

export async function getWikiNode(id: string): Promise<WikiNode> {
  const res = await fetch(`${API_URL}/wiki/nodes/${id}`);
  if (!res.ok) throw new Error("Failed to fetch wiki node");
  return res.json();
}

export async function getBookmarks(): Promise<Bookmark[]> {
  const res = await fetch(`${API_URL}/bookmarks`, { next: { revalidate: 10 } });
  if (!res.ok) throw new Error("Failed to fetch bookmarks");
  return res.json();
}

export async function submitBookmark(url: string): Promise<void> {
  const res = await fetch(`${API_URL}/bookmarks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error("Failed to submit bookmark");
}

export async function getAlerts(): Promise<Alert[]> {
  const res = await fetch(`${API_URL}/alerts`, { next: { revalidate: 15 } });
  if (!res.ok) throw new Error("Failed to fetch alerts");
  return res.json();
}

export async function resolveAlert(
  id: string,
  status: "resolved" | "accepted_tension"
): Promise<void> {
  const res = await fetch(`${API_URL}/alerts/${id}/resolve`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error("Failed to resolve alert");
}

export async function getGaps(): Promise<Gap[]> {
  const res = await fetch(`${API_URL}/gaps`, { next: { revalidate: 30 } });
  if (!res.ok) throw new Error("Failed to fetch gaps");
  return res.json();
}

export async function triggerGapAnalysis(): Promise<void> {
  const res = await fetch(`${API_URL}/gaps/analyze`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger gap analysis");
}

export async function fillGap(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/gaps/${id}/fill`, { method: "PATCH" });
  if (!res.ok) throw new Error("Failed to fill gap");
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat: add typed API client for all FastAPI endpoints"
```

---

### Task 5: Create Knowledge Graph component and page

**Files:**
- Create: `frontend/components/WikiPanel.tsx`
- Create: `frontend/components/KnowledgeGraph.tsx`
- Create: `frontend/app/page.tsx`

- [ ] **Step 1: Create `frontend/components/WikiPanel.tsx`**

```typescript
"use client";

import ReactMarkdown from "react-markdown";
import { WikiNode } from "@/lib/api";

interface WikiPanelProps {
  node: WikiNode;
  content: string;
  onClose: () => void;
}

export function WikiPanel({ node, content, onClose }: WikiPanelProps) {
  return (
    <div className="fixed right-0 top-0 h-full w-96 bg-white shadow-xl overflow-y-auto z-50 border-l border-gray-200">
      <div className="sticky top-0 bg-white border-b border-gray-200 p-4 flex justify-between items-center">
        <h2 className="font-semibold text-lg truncate">{node.title}</h2>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-xl leading-none"
        >
          ×
        </button>
      </div>
      <div className="p-4 prose prose-sm max-w-none">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/components/KnowledgeGraph.tsx`**

```typescript
"use client";

import { useCallback, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  useNodesState,
  useEdgesState,
  NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { WikiNode } from "@/lib/api";
import { WikiPanel } from "./WikiPanel";

interface KnowledgeGraphProps {
  nodes: WikiNode[];
  alertNodeIds: Set<string>;
  gapTopics: Set<string>;
}

export function KnowledgeGraph({ nodes, alertNodeIds, gapTopics }: KnowledgeGraphProps) {
  const [selectedNode, setSelectedNode] = useState<WikiNode | null>(null);
  const [nodeContent, setNodeContent] = useState<string>("");

  // Build slug → id + node map
  const slugToNode = Object.fromEntries(nodes.map((n) => [n.slug, n]));

  const rfNodes: Node[] = nodes.map((n, i) => {
    const hasAlert = alertNodeIds.has(n.id);
    const hasGap = gapTopics.has(n.title.toLowerCase());
    const color = hasAlert ? "#fca5a5" : hasGap ? "#fde68a" : "#e5e7eb";

    return {
      id: n.id,
      data: { label: n.title },
      position: { x: (i % 8) * 200, y: Math.floor(i / 8) * 120 },
      style: { background: color, border: "1px solid #9ca3af", borderRadius: 8, fontSize: 12 },
    };
  });

  const rfEdges: Edge[] = nodes.flatMap((n) =>
    (n.linked_slugs || [])
      .filter((slug) => slugToNode[slug])
      .map((slug) => ({
        id: `${n.id}-${slugToNode[slug].id}`,
        source: n.id,
        target: slugToNode[slug].id,
        style: { stroke: "#9ca3af" },
      }))
  );

  const [flowNodes, , onNodesChange] = useNodesState(rfNodes);
  const [flowEdges, , onEdgesChange] = useEdgesState(rfEdges);

  const onNodeClick: NodeMouseHandler = useCallback(
    async (_, node) => {
      const wikiNode = nodes.find((n) => n.id === node.id);
      if (!wikiNode) return;
      setSelectedNode(wikiNode);
      // Fetch markdown file content via backend
      const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const res = await fetch(`${API_URL}/wiki/nodes/${wikiNode.id}`);
      const data = await res.json();
      setNodeContent(data.content || wikiNode.summary || "No content available.");
    },
    [nodes]
  );

  return (
    <div className="w-full h-full relative">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>

      {selectedNode && (
        <WikiPanel
          node={selectedNode}
          content={nodeContent}
          onClose={() => setSelectedNode(null)}
        />
      )}

      <div className="absolute bottom-4 left-4 bg-white rounded shadow p-3 text-xs space-y-1">
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded bg-red-300 inline-block" /> Open alert</div>
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded bg-yellow-200 inline-block" /> Knowledge gap</div>
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded bg-gray-200 inline-block" /> Normal node</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Update backend `GET /wiki/nodes/{id}` to return file content**

In `dke/backend/api/routes/wiki.py`, update the single node endpoint to include file content:
```python
@router.get("/wiki/nodes/{node_id}")
async def get_wiki_node(node_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WikiNode).where(WikiNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Wiki node not found")
    content = ""
    if node.file_path:
        from pathlib import Path
        p = Path(node.file_path)
        if p.exists():
            content = p.read_text()
    return {
        "id": str(node.id),
        "title": node.title,
        "slug": node.slug,
        "summary": node.summary,
        "linked_slugs": node.linked_slugs or [],
        "content": content,
        "updated_at": node.updated_at.isoformat(),
    }
```

- [ ] **Step 4: Create `frontend/app/page.tsx`**

```typescript
import { getAlerts, getGaps, getWikiNodes } from "@/lib/api";
import { KnowledgeGraph } from "@/components/KnowledgeGraph";

export default async function HomePage() {
  const [nodes, alerts, gaps] = await Promise.all([
    getWikiNodes(),
    getAlerts(),
    getGaps(),
  ]);

  const alertNodeIds = new Set(
    alerts
      .filter((a) => a.status === "open")
      .flatMap((a) => [a.source_node_id, a.conflicting_node_id])
  );

  const gapTopics = new Set(
    gaps.filter((g) => g.status === "open").map((g) => g.topic.toLowerCase())
  );

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b px-6 py-3 flex items-center justify-between bg-white">
        <h1 className="font-semibold text-lg">DKE — Knowledge Graph</h1>
        <nav className="flex gap-4 text-sm text-gray-600">
          <a href="/bookmarks" className="hover:text-black">Bookmarks</a>
          <a href="/alerts" className="hover:text-black">
            Alerts {alerts.filter((a) => a.status === "open").length > 0 && (
              <span className="ml-1 bg-red-500 text-white rounded-full px-1.5 py-0.5 text-xs">
                {alerts.filter((a) => a.status === "open").length}
              </span>
            )}
          </a>
          <a href="/gaps" className="hover:text-black">Gaps</a>
        </nav>
      </header>
      <main className="flex-1 overflow-hidden">
        <KnowledgeGraph
          nodes={nodes}
          alertNodeIds={alertNodeIds}
          gapTopics={gapTopics}
        />
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Verify page renders**

```bash
cd frontend && npm run dev
```

Open `http://localhost:3000` — graph should render with wiki nodes.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/KnowledgeGraph.tsx frontend/components/WikiPanel.tsx frontend/app/page.tsx dke/backend/api/routes/wiki.py
git commit -m "feat: add knowledge graph page with React Flow and WikiPanel"
```

---

### Task 6: Create Bookmarks page

**Files:**
- Create: `frontend/components/BookmarkForm.tsx`
- Create: `frontend/app/bookmarks/page.tsx`

- [ ] **Step 1: Create `frontend/components/BookmarkForm.tsx`**

```typescript
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { submitBookmark } from "@/lib/api";

export function BookmarkForm() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setLoading(true);
    try {
      await submitBookmark(url.trim());
      setUrl("");
      setMessage("Bookmark queued for processing.");
      setTimeout(() => setMessage(""), 3000);
    } catch {
      setMessage("Failed to submit bookmark.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2 mb-6">
      <Input
        type="url"
        placeholder="https://example.com/article"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        className="flex-1"
        required
      />
      <Button type="submit" disabled={loading}>
        {loading ? "Submitting…" : "Add Bookmark"}
      </Button>
      {message && <span className="text-sm text-gray-500 self-center">{message}</span>}
    </form>
  );
}
```

- [ ] **Step 2: Create `frontend/app/bookmarks/page.tsx`**

```typescript
import { getBookmarks } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { BookmarkForm } from "@/components/BookmarkForm";

const STATUS_COLORS = {
  pending: "secondary",
  processing: "outline",
  done: "default",
  failed: "destructive",
} as const;

export default async function BookmarksPage() {
  const bookmarks = await getBookmarks();

  return (
    <div className="max-w-4xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Bookmarks</h1>
        <a href="/" className="text-sm text-gray-500 hover:text-black">← Graph</a>
      </div>

      <BookmarkForm />

      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="text-left p-3 font-medium text-gray-600">Title / URL</th>
              <th className="text-left p-3 font-medium text-gray-600">Status</th>
            </tr>
          </thead>
          <tbody>
            {bookmarks.length === 0 && (
              <tr><td colSpan={2} className="p-6 text-center text-gray-400">No bookmarks yet.</td></tr>
            )}
            {bookmarks.map((b) => (
              <tr key={b.id} className="border-b last:border-0 hover:bg-gray-50">
                <td className="p-3">
                  <div className="font-medium truncate max-w-lg">{b.title || b.url}</div>
                  {b.title && <div className="text-gray-400 text-xs truncate max-w-lg">{b.url}</div>}
                </td>
                <td className="p-3">
                  <Badge variant={STATUS_COLORS[b.status]}>{b.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify page at `http://localhost:3000/bookmarks`**

Expected: Table of bookmarks with status badges and URL submission form.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/BookmarkForm.tsx frontend/app/bookmarks/page.tsx
git commit -m "feat: add bookmarks page with submission form and status table"
```

---

### Task 7: Create Alerts page

**Files:**
- Create: `frontend/components/AlertCard.tsx`
- Create: `frontend/app/alerts/page.tsx`

- [ ] **Step 1: Create `frontend/components/AlertCard.tsx`**

```typescript
"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, resolveAlert } from "@/lib/api";

interface AlertCardProps {
  alert: Alert;
  sourceTitle: string;
  conflictingTitle: string;
  onResolved: (id: string, status: string) => void;
}

export function AlertCard({ alert, sourceTitle, conflictingTitle, onResolved }: AlertCardProps) {
  const [loading, setLoading] = useState(false);

  async function handleResolve(status: "resolved" | "accepted_tension") {
    setLoading(true);
    try {
      await resolveAlert(alert.id, status);
      onResolved(alert.id, status);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div>
            <span className="font-medium text-red-700">{sourceTitle}</span>
            <span className="text-gray-400 mx-2">vs</span>
            <span className="font-medium text-blue-700">{conflictingTitle}</span>
          </div>
          <Badge variant={alert.confidence === "HIGH" ? "destructive" : "outline"}>
            {alert.confidence}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-gray-600 mb-4">{alert.description}</p>
        {alert.status === "open" && (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleResolve("resolved")}
              disabled={loading}
            >
              Resolve
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => handleResolve("accepted_tension")}
              disabled={loading}
            >
              Accept Tension
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Create `frontend/app/alerts/page.tsx`**

```typescript
import { getAlerts, getWikiNodes } from "@/lib/api";
import { AlertsClient } from "./AlertsClient";

export default async function AlertsPage() {
  const [alerts, nodes] = await Promise.all([getAlerts(), getWikiNodes()]);
  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n.title]));
  return <AlertsClient initialAlerts={alerts} nodeMap={nodeMap} />;
}
```

- [ ] **Step 3: Create `frontend/app/alerts/AlertsClient.tsx`**

```typescript
"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AlertCard } from "@/components/AlertCard";
import { Alert } from "@/lib/api";

interface AlertsClientProps {
  initialAlerts: Alert[];
  nodeMap: Record<string, string>;
}

export function AlertsClient({ initialAlerts, nodeMap }: AlertsClientProps) {
  const [alerts, setAlerts] = useState(initialAlerts);

  function handleResolved(id: string, status: string) {
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, status: status as Alert["status"] } : a))
    );
  }

  const open = alerts.filter((a) => a.status === "open");
  const resolved = alerts.filter((a) => a.status === "resolved");
  const accepted = alerts.filter((a) => a.status === "accepted_tension");

  function renderList(list: Alert[]) {
    if (list.length === 0) return <p className="text-gray-400 text-sm py-4">No alerts.</p>;
    return list.map((a) => (
      <AlertCard
        key={a.id}
        alert={a}
        sourceTitle={nodeMap[a.source_node_id] || a.source_node_id}
        conflictingTitle={nodeMap[a.conflicting_node_id] || a.conflicting_node_id}
        onResolved={handleResolved}
      />
    ));
  }

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Dialectical Alerts</h1>
        <a href="/" className="text-sm text-gray-500 hover:text-black">← Graph</a>
      </div>
      <Tabs defaultValue="open">
        <TabsList className="mb-4">
          <TabsTrigger value="open">Open ({open.length})</TabsTrigger>
          <TabsTrigger value="resolved">Resolved ({resolved.length})</TabsTrigger>
          <TabsTrigger value="accepted">Accepted ({accepted.length})</TabsTrigger>
        </TabsList>
        <TabsContent value="open">{renderList(open)}</TabsContent>
        <TabsContent value="resolved">{renderList(resolved)}</TabsContent>
        <TabsContent value="accepted">{renderList(accepted)}</TabsContent>
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 4: Verify at `http://localhost:3000/alerts`**

Expected: Tabbed alerts dashboard. Clicking Resolve/Accept Tension updates the card immediately.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/AlertCard.tsx frontend/app/alerts/
git commit -m "feat: add alerts dashboard with resolve/accept tension workflow"
```

---

### Task 8: Create Gaps page

**Files:**
- Create: `frontend/components/GapCard.tsx`
- Create: `frontend/app/gaps/page.tsx`

- [ ] **Step 1: Create `frontend/components/GapCard.tsx`**

```typescript
"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Gap, fillGap } from "@/lib/api";

interface GapCardProps {
  gap: Gap;
  position: number;
  onFilled: (id: string) => void;
}

export function GapCard({ gap, position, onFilled }: GapCardProps) {
  const [loading, setLoading] = useState(false);
  const scorePercent = gap.score != null ? Math.round(gap.score * 100) : null;

  async function handleFill() {
    setLoading(true);
    try {
      await fillGap(gap.id);
      onFilled(gap.id);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div>
            <span className="text-xs text-gray-400 mr-2">#{position}</span>
            <span className="font-medium">{gap.topic}</span>
            <Badge variant="outline" className="ml-2 text-xs">{gap.domain}</Badge>
          </div>
          {scorePercent != null && (
            <div className="text-right">
              <div className="text-sm font-semibold">{scorePercent}%</div>
              <div className="w-20 bg-gray-200 rounded-full h-1.5 mt-1">
                <div className="bg-blue-500 h-1.5 rounded-full" style={{ width: `${scorePercent}%` }} />
              </div>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {gap.recommended.length > 0 && (
          <div className="mb-3">
            <p className="text-xs font-medium text-gray-500 mb-1">Recommended searches:</p>
            <ul className="text-sm text-blue-600 space-y-0.5">
              {gap.recommended.map((q, i) => (
                <li key={i}>
                  <a
                    href={`https://www.google.com/search?q=${encodeURIComponent(q)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                  >
                    {q}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
        {gap.status === "open" && (
          <Button size="sm" variant="outline" onClick={handleFill} disabled={loading}>
            {loading ? "Marking…" : "Mark as Filled"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Create `frontend/app/gaps/page.tsx`**

```typescript
import { getGaps, triggerGapAnalysis } from "@/lib/api";
import { GapsClient } from "./GapsClient";

export default async function GapsPage() {
  const gaps = await getGaps();
  return <GapsClient initialGaps={gaps} />;
}
```

- [ ] **Step 3: Create `frontend/app/gaps/GapsClient.tsx`**

```typescript
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { GapCard } from "@/components/GapCard";
import { Gap, triggerGapAnalysis } from "@/lib/api";

interface GapsClientProps {
  initialGaps: Gap[];
}

export function GapsClient({ initialGaps }: GapsClientProps) {
  const [gaps, setGaps] = useState(initialGaps);
  const [triggering, setTriggering] = useState(false);
  const [message, setMessage] = useState("");

  function handleFilled(id: string) {
    setGaps((prev) => prev.map((g) => (g.id === id ? { ...g, status: "filled" as const } : g)));
  }

  async function handleTrigger() {
    setTriggering(true);
    try {
      await triggerGapAnalysis();
      setMessage("Gap analysis queued. Refresh in a minute to see results.");
      setTimeout(() => setMessage(""), 5000);
    } finally {
      setTriggering(false);
    }
  }

  const open = gaps.filter((g) => g.status === "open");

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Knowledge Gaps Compass</h1>
        <div className="flex items-center gap-3">
          <a href="/" className="text-sm text-gray-500 hover:text-black">← Graph</a>
          <Button size="sm" onClick={handleTrigger} disabled={triggering}>
            {triggering ? "Queuing…" : "Trigger Analysis"}
          </Button>
        </div>
      </div>

      {message && <p className="text-sm text-blue-600 mb-4">{message}</p>}

      {open.length === 0 ? (
        <p className="text-gray-400 text-sm">No open gaps. Add more bookmarks or trigger an analysis.</p>
      ) : (
        open.map((g, i) => (
          <GapCard key={g.id} gap={g} position={i + 1} onFilled={handleFilled} />
        ))
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify at `http://localhost:3000/gaps`**

Expected: List of gap cards ordered by score, with search query links and Mark as Filled button.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/GapCard.tsx frontend/app/gaps/
git commit -m "feat: add gaps compass page with score bars and learning path"
```

---

### Task 9: Deploy to Vercel

- [ ] **Step 1: Push to GitHub**

```bash
git push origin main
```

- [ ] **Step 2: Import project on Vercel**

1. Go to vercel.com → New Project
2. Import the GitHub repository
3. Set **Root Directory** to `frontend`
4. Add environment variable: `NEXT_PUBLIC_API_URL` = your Railway backend URL

- [ ] **Step 3: Deploy backend to Railway**

1. Go to railway.app → New Project → Deploy from GitHub
2. Select the repo, set root to `.worktrees/dke-phase1/dke`
3. Add environment variables from `.env`
4. Add a second Railway service for the Celery worker with start command:
   ```
   celery -A backend.tasks.celery_app worker --loglevel=info
   ```
5. Add Upstash Redis: railway.app → Add Plugin → Redis

- [ ] **Step 4: Smoke test production**

```bash
# Replace with your Vercel URL
curl -s https://your-app.vercel.app
```

Expected: 200 response. App loads in browser.

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: Feature 4 Frontend complete — deployed to Vercel"
```
