from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_db
from backend.models.bookmark import Bookmark
from backend.pipeline.processor import process_bookmark, process_bookmarks_bulk

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
    items = []
    for bm in created:
        await db.refresh(bm)
        items.append((bm.id, bm.url))
    background_tasks.add_task(process_bookmarks_bulk, items)
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
