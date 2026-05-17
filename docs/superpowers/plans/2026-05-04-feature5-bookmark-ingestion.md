# Feature 5: Seamless Bookmark Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click bookmark save path via a browser bookmarklet (desktop) and mobile share shortcut, both pointing at a new `GET /save` FastAPI endpoint.

**Architecture:** A new `GET /save?url=<encoded>` endpoint validates the URL, creates a Bookmark record in the DB, enqueues a FastAPI `BackgroundTask`, and redirects to `/dashboard?saved=true`. The Next.js frontend shows a `SaveToast` after the redirect and provides a `/setup` page with drag-to-bar bookmarklet button and mobile share instructions.

**Tech Stack:** FastAPI, SQLAlchemy async, FastAPI BackgroundTasks (built-in), Next.js 15 App Router, React, TypeScript, Tailwind CSS, shadcn/ui

> **Dependencies:** Phase 0 (pgvector) must be complete before this feature. Feature 4 (Next.js frontend) must be complete before Tasks 3–6.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `backend/config.py` | Modify | Add `frontend_url` field |
| `backend/api/routes/save.py` | Create | `GET /save` endpoint |
| `backend/api/main.py` | Modify | Register save router |
| `tests/test_save.py` | Create | Tests for `/save` endpoint |
| `frontend/components/BookmarkletButton.tsx` | Create | Drag-to-bar bookmarklet button |
| `frontend/components/SaveToast.tsx` | Create | Toast shown after redirect |
| `frontend/app/setup/page.tsx` | Create | Setup page with bookmarklet + mobile instructions |
| `frontend/app/dashboard/page.tsx` | Modify | Mount `SaveToast` |

---

## Task 1: Add `frontend_url` to config

**Files:**
- Modify: `backend/config.py`

- [ ] **Step 1: Add `frontend_url` to Settings**

Replace the contents of `backend/config.py` with:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    groq_api_key: str
    database_url: str = "postgresql+asyncpg://dke:dke@localhost:5432/dke"
    wiki_dir: str = "wiki"
    groq_model: str = "llama-3.3-70b-versatile"
    frontend_url: str = "http://localhost:3000"
    redis_url: str = "redis://localhost:6379/0"

    model_config = {"env_file": ".env"}


settings = Settings()
```

- [ ] **Step 2: Add `FRONTEND_URL` to `.env` and `.env.example`**

Add to `.env`:
```
FRONTEND_URL=http://localhost:3000
```

Add to `.env.example`:
```
FRONTEND_URL=http://localhost:3000
# FRONTEND_URL=https://your-dke.railway.app   # production
```

- [ ] **Step 3: Verify config loads**

Run from the worktree root (`.worktrees/dke-phase1/dke/`):
```bash
python -c "from backend.config import settings; print(settings.frontend_url)"
```
Expected output: `http://localhost:3000`

- [ ] **Step 4: Commit**

```bash
git add backend/config.py .env.example
git commit -m "feat: add frontend_url to settings"
```

---

## Task 2: Create `GET /save` endpoint

**Files:**
- Create: `backend/api/routes/save.py`
- Modify: `backend/api/main.py`
- Create: `tests/test_save.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_save.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock


@pytest.fixture
async def client():
    import backend.models  # noqa: F401
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_save_valid_url_redirects_to_dashboard_saved(client):
    with patch("backend.api.routes.save.process_bookmark", new_callable=AsyncMock):
        resp = await client.get(
            "/save",
            params={"url": "https://example.com/article"},
            follow_redirects=False,
        )
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/dashboard?saved=true")


async def test_save_invalid_scheme_redirects_to_error(client):
    resp = await client.get(
        "/save",
        params={"url": "file:///etc/passwd"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert "error=invalid_url" in resp.headers["location"]


async def test_save_missing_url_param_returns_422(client):
    resp = await client.get("/save")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd .worktrees/dke-phase1/dke
pytest tests/test_save.py -v
```
Expected: FAIL — `ModuleNotFoundError` or `404` because the route doesn't exist yet.

- [ ] **Step 3: Create the save route**

Create `backend/api/routes/save.py`:

```python
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.postgres import get_db
from backend.models.bookmark import Bookmark
from backend.pipeline.processor import process_bookmark

router = APIRouter()


@router.get("/save")
async def save_bookmark(
    url: str = Query(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return RedirectResponse(
            f"{settings.frontend_url}/dashboard?error=invalid_url",
            status_code=307,
        )
    bm = Bookmark(url=url, source="bookmarklet", tags=[])
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    background_tasks.add_task(process_bookmark, bm.id, bm.url)
    return RedirectResponse(
        f"{settings.frontend_url}/dashboard?saved=true",
        status_code=307,
    )
```

- [ ] **Step 4: Register the router in `main.py`**

Replace the contents of `backend/api/main.py`:

```python
from contextlib import asynccontextmanager

import backend.models  # noqa: F401 — register models before init_db
from fastapi import FastAPI

from backend.db.postgres import init_db
from backend.api.routes import bookmarks, wiki
from backend.api.routes.save import router as save_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="DKE Wiki Compiler", lifespan=lifespan)
app.include_router(bookmarks.router)
app.include_router(wiki.router)
app.include_router(save_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd .worktrees/dke-phase1/dke
pytest tests/test_save.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 6: Run full test suite to check no regressions**

```bash
pytest tests/ -v --ignore=tests/test_db.py
```
Expected: All existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/api/routes/save.py backend/api/main.py tests/test_save.py
git commit -m "feat: add GET /save endpoint for bookmarklet ingestion"
```

---

## Task 3: `BookmarkletButton` frontend component

> **Prerequisite:** Feature 4 (Next.js frontend) must be set up. Run from `frontend/` directory for all frontend steps.

**Files:**
- Create: `frontend/components/BookmarkletButton.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/components/BookmarkletButton.tsx`:

```tsx
"use client";

import { useState } from "react";

const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

const bookmarkletCode = `javascript:(function(){window.open('${APP_URL}/save?url='+encodeURIComponent(window.location.href));})();`;

export function BookmarkletButton() {
  const [showModal, setShowModal] = useState(false);

  return (
    <div className="flex flex-col items-start gap-3">
      <a
        href={bookmarkletCode}
        onClick={(e) => {
          e.preventDefault();
          setShowModal(true);
        }}
        draggable
        className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow hover:bg-blue-700 cursor-grab active:cursor-grabbing select-none"
        aria-label="Drag this to your bookmark bar to save pages to DKE"
      >
        📌 Save to DKE
      </a>
      <p className="text-sm text-gray-500">
        Drag this button to your bookmark bar. Then click it on any page to save
        to DKE.
      </p>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="rounded-lg bg-white p-6 shadow-xl max-w-sm w-full mx-4">
            <h2 className="text-lg font-semibold mb-3">Add to bookmark bar manually</h2>
            <ol className="list-decimal list-inside space-y-2 text-sm text-gray-700">
              <li>Right-click the button above and choose "Bookmark this link"</li>
              <li>In the dialog, change the location to your bookmark bar folder</li>
              <li>Click Save</li>
            </ol>
            <p className="mt-3 text-xs text-gray-500">
              Or drag the button directly to your browser&apos;s bookmark bar.
            </p>
            <button
              onClick={() => setShowModal(false)}
              className="mt-4 w-full rounded-md bg-gray-100 px-4 py-2 text-sm font-medium hover:bg-gray-200"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add `NEXT_PUBLIC_APP_URL` to frontend env**

Add to `frontend/.env.local`:
```
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

Add to `frontend/.env.example` (create if it doesn't exist):
```
NEXT_PUBLIC_APP_URL=http://localhost:3000
# NEXT_PUBLIC_APP_URL=https://your-dke.railway.app   # production
```

- [ ] **Step 3: Commit**

```bash
git add frontend/components/BookmarkletButton.tsx frontend/.env.example
git commit -m "feat: add BookmarkletButton component"
```

---

## Task 4: `SaveToast` frontend component

**Files:**
- Create: `frontend/components/SaveToast.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/components/SaveToast.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

const MESSAGES: Record<string, { text: string; color: string }> = {
  saved: {
    text: "Saved! Processing in background...",
    color: "bg-green-600",
  },
  invalid_url: {
    text: "Invalid URL — only http/https links are supported",
    color: "bg-red-600",
  },
  queue_unavailable: {
    text: "Couldn't save right now, please try again",
    color: "bg-red-600",
  },
};

export function SaveToast() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [toast, setToast] = useState<{ text: string; color: string } | null>(null);

  useEffect(() => {
    const saved = searchParams.get("saved");
    const error = searchParams.get("error");

    if (saved === "true") {
      setToast(MESSAGES.saved);
      router.replace("/dashboard");
    } else if (error && MESSAGES[error]) {
      setToast(MESSAGES[error]);
      router.replace("/dashboard");
    }
  }, [searchParams, router]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  if (!toast) return null;

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 rounded-lg px-4 py-3 text-sm font-medium text-white shadow-lg transition-all ${toast.color}`}
      role="status"
      aria-live="polite"
    >
      {toast.text}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/SaveToast.tsx
git commit -m "feat: add SaveToast component for post-redirect feedback"
```

---

## Task 5: `/setup` page

**Files:**
- Create: `frontend/app/setup/page.tsx`

- [ ] **Step 1: Create the setup page**

Create `frontend/app/setup/page.tsx`:

```tsx
import { BookmarkletButton } from "@/components/BookmarkletButton";

export default function SetupPage() {
  return (
    <main className="max-w-2xl mx-auto px-4 py-12 space-y-12">
      <h1 className="text-2xl font-bold">Set up DKE Save</h1>

      {/* Desktop: Bookmarklet */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Desktop (any browser)</h2>
        <p className="text-sm text-gray-600">
          Add the button below to your bookmark bar. One click on any page saves
          it to DKE.
        </p>
        <BookmarkletButton />
      </section>

      {/* iOS */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">iPhone / iPad (iOS Shortcuts)</h2>
        <ol className="list-decimal list-inside space-y-2 text-sm text-gray-700">
          <li>Open the Shortcuts app on your iPhone</li>
          <li>Tap <strong>+</strong> to create a new shortcut</li>
          <li>Tap <strong>Add Action</strong> → search for <strong>Open URLs</strong></li>
          <li>
            Set the URL to:{" "}
            <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">
              {process.env.NEXT_PUBLIC_APP_URL}/save?url=[Shortcut Input]
            </code>
          </li>
          <li>Tap <strong>⋯</strong> (top right) → <strong>Add to Share Sheet</strong></li>
          <li>
            Now open Safari, tap Share → <strong>DKE Save</strong> to save any
            page
          </li>
        </ol>
      </section>

      {/* Android */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Android</h2>
        <p className="text-sm text-gray-600">
          Android does not natively support custom share-to-URL shortcuts without
          a dedicated app. The easiest workaround:
        </p>
        <ol className="list-decimal list-inside space-y-2 text-sm text-gray-700">
          <li>Copy the URL you want to save</li>
          <li>Open DKE and paste it in the URL field on the dashboard</li>
        </ol>
        <p className="text-xs text-gray-500">
          A native Android share target is on the roadmap once the web app is
          published as a PWA.
        </p>
      </section>
    </main>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/setup/page.tsx
git commit -m "feat: add /setup page with bookmarklet and mobile save instructions"
```

---

## Task 6: Mount `SaveToast` on dashboard

**Files:**
- Modify: `frontend/app/dashboard/page.tsx`

- [ ] **Step 1: Read the current dashboard page**

Open `frontend/app/dashboard/page.tsx` and note its current contents.

- [ ] **Step 2: Add `SaveToast` and `Suspense` wrapper**

Add the following imports at the top:

```tsx
import { Suspense } from "react";
import { SaveToast } from "@/components/SaveToast";
```

Add `<SaveToast>` wrapped in `<Suspense>` inside the page's return, just before the closing tag of the outermost element:

```tsx
<Suspense fallback={null}>
  <SaveToast />
</Suspense>
```

> `SaveToast` uses `useSearchParams()` which requires a `Suspense` boundary in Next.js App Router. The `fallback={null}` means nothing renders while the param is being read.

- [ ] **Step 3: Start the dev server and verify**

```bash
cd frontend
npm run dev
```

In a browser, navigate to `http://localhost:3000/dashboard?saved=true`.
Expected: Green toast appears at bottom-right: "Saved! Processing in background..." and disappears after 4 seconds. URL becomes `http://localhost:3000/dashboard`.

Navigate to `http://localhost:3000/dashboard?error=invalid_url`.
Expected: Red toast: "Invalid URL — only http/https links are supported".

- [ ] **Step 4: Commit**

```bash
git add frontend/app/dashboard/page.tsx
git commit -m "feat: mount SaveToast on dashboard for post-save feedback"
```

---

## Task 7: End-to-end verification

- [ ] **Step 1: Start backend + frontend**

```bash
# Terminal 1 — Backend
cd .worktrees/dke-phase1/dke
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend
cd frontend
npm run dev
```

- [ ] **Step 2: Test the bookmarklet on desktop**

1. Go to `http://localhost:3000/setup`
2. Drag the "Save to DKE" button to your bookmark bar
3. Navigate to any webpage (e.g. `https://news.ycombinator.com`)
4. Click the bookmarklet
5. Expected: redirect to `http://localhost:3000/dashboard?saved=true`, green toast appears

- [ ] **Step 3: Verify bookmark was created in DB**

```bash
curl http://localhost:8000/bookmarks | python3 -m json.tool
```
Expected: The most recent bookmark has `url` matching the page you visited, `status` of `queued` or `done`.

- [ ] **Step 4: Test invalid scheme**

In browser address bar navigate to:
```
http://localhost:8000/save?url=file:///etc/passwd
```
Expected: redirect to `http://localhost:3000/dashboard?error=invalid_url`, red toast appears.

- [ ] **Step 5: Test missing URL param**

```bash
curl -i http://localhost:8000/save
```
Expected: `HTTP/1.1 422 Unprocessable Entity`

- [ ] **Step 6: Run full backend test suite**

```bash
cd .worktrees/dke-phase1/dke
pytest tests/ -v --ignore=tests/test_db.py
```
Expected: All tests pass.
