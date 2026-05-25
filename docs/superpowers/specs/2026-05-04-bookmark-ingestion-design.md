# DKE Design Spec — Feature 5: Seamless Bookmark Ingestion (Bookmarklet + Mobile Share)
**Date:** 2026-05-04
**Status:** Approved (updated: Celery replaced with FastAPI BackgroundTasks)

---

## 1. Problem Statement

DKE currently accepts bookmarks only via raw API calls (`POST /bookmarks`). There is no user-facing save mechanism. Users browse on both desktop and mobile and want to save content in the moment — context-switching to a separate app to paste a URL kills the habit. This feature adds a one-click save path for both desktop (bookmarklet) and mobile (share sheet shortcut).

---

## 2. Scope

### In scope
- New `GET /save?url=<encoded_url>` FastAPI endpoint
- Bookmarklet JavaScript (drag-to-bar button on Setup page)
- `/setup` page in Next.js frontend with bookmarklet + mobile instructions
- `SaveToast` component shown on dashboard after redirect
- Error handling for invalid URL, missing param, queue unavailable

### Out of scope
- Browser extension (Chrome Web Store / Firefox Add-ons) — future polish
- Authentication on `/save` — DKE is single-user
- iOS Shortcuts app automation — user configures manually using instructions on setup page
- Import from browser bookmark HTML export — separate feature

---

## 3. Architecture

```
User clicks bookmarklet (desktop) or Share Sheet shortcut (mobile)
        ↓
GET /save?url=https://some-article.com
        ↓
FastAPI /save endpoint
  → validate URL (must be http/https)
  → create Bookmark record in DB
  → background_tasks.add_task(process_bookmark, ...)   ← FastAPI BackgroundTask
  → redirect to /dashboard?saved=true
        ↓
Next.js dashboard reads ?saved=true query param
  → shows SaveToast: "Saved! Processing in background..."
```

The `/save` endpoint is a thin adapter — it does no processing itself. Processing runs as a FastAPI BackgroundTask after the redirect response is sent.

---

## 4. Backend

### New endpoint: `GET /save`

**File:** `backend/api/routes/save.py`

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

**Register in** `backend/api/main.py`:
```python
from backend.api.routes.save import router as save_router
app.include_router(save_router)
```

### New config field

**File:** `backend/config.py` — add `frontend_url: str = "http://localhost:3000"`

---

## 5. Frontend

### Bookmarklet JavaScript

```javascript
javascript:(function(){
  window.open('FRONTEND_URL/save?url='+encodeURIComponent(window.location.href));
})();
```

`FRONTEND_URL` is replaced at build time with the actual deployment URL (Next.js env var `NEXT_PUBLIC_APP_URL`).

### `/setup` page

**File:** `app/setup/page.tsx`

Sections:
1. **Desktop** — `<BookmarkletButton>` component (an `<a>` tag with the bookmarklet `href`, styled as a button with drag instruction)
2. **iOS** — step-by-step: Open Safari → Share → Shortcuts → New Shortcut → "Open URL" action with `https://YOUR_DKE_URL/save?url=[Shortcut Input]`
3. **Android** — step-by-step: Add Chrome shortcut to home screen or use "Share → Copy to clipboard" + paste in DKE (Android share-to-URL requires a custom app; instructions guide user to the paste-in-dashboard fallback)

### `BookmarkletButton` component

**File:** `components/BookmarkletButton.tsx`

Renders an `<a>` with `href={bookmarkletCode}`. Includes a drag hint: "Drag this to your bookmark bar". Clicking it (instead of dragging) opens a modal explaining how to add it manually.

### `SaveToast` component

**File:** `components/SaveToast.tsx`

Reads `?saved=true` or `?error=<code>` from URL search params on mount. Shows:
- `saved=true` → green toast: "Saved! Processing in background..."
- `error=invalid_url` → red toast: "Invalid URL — only http/https links are supported"
- `error=queue_unavailable` → red toast: "Couldn't save right now, please try again"

Toast auto-dismisses after 4 seconds. URL param is cleared with `router.replace('/dashboard')` after reading.

---

## 6. Error Handling

| Case | Behavior |
|---|---|
| URL param missing | FastAPI returns `422 Unprocessable Entity` (standard Query validation) |
| URL is not http/https | Redirect to `/dashboard?error=invalid_url` |
| Duplicate URL | BackgroundTask dispatched; processor skips silently if already `done` |

---

## 7. Environment Variables

```
# Backend (add to config.py + .env)
FRONTEND_URL=http://localhost:3000          # local dev
# FRONTEND_URL=https://your-dke.railway.app  # production

# Frontend (Next.js)
NEXT_PUBLIC_APP_URL=http://localhost:3000   # used to build bookmarklet href
```

---

## 8. Files Changed

| File | Type | Purpose |
|---|---|---|
| `backend/api/routes/save.py` | New | `GET /save` endpoint |
| `backend/api/main.py` | Modified | Register save router |
| `backend/config.py` | Modified | Add `frontend_url` field |
| `app/setup/page.tsx` | New | Setup page with bookmarklet + mobile instructions |
| `components/BookmarkletButton.tsx` | New | Drag-to-bar bookmarklet button |
| `components/SaveToast.tsx` | New | Toast shown after redirect |
| `app/dashboard/page.tsx` | Modified | Mount `SaveToast` |

---

## 9. Verification Checklist

1. Open any webpage on desktop → click bookmarklet → verify redirect to `/dashboard?saved=true` and toast appears
2. Verify bookmark appears in DB with `status=queued` then transitions to `done`
3. Try bookmarklet on `file://` URL → verify redirect to `/dashboard?error=invalid_url`
4. Follow iOS setup instructions → share a URL from Safari → verify it saves correctly
6. Visit `/save` with no `url` param → verify 422 response
