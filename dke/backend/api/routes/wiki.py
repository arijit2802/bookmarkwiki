from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_db
from backend.models.wiki_node import WikiNode

router = APIRouter()


@router.get("/wiki/nodes")
async def list_wiki_nodes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WikiNode).order_by(WikiNode.updated_at.desc()))
    nodes = result.scalars().all()
    return [
        {
            "id": str(n.id),
            "title": n.title,
            "slug": n.slug,
            "summary": n.summary,
            "bookmark_count": len(n.bookmark_ids),
            "updated_at": n.updated_at.isoformat(),
        }
        for n in nodes
    ]


@router.get("/wiki/nodes/{node_id}")
async def get_wiki_node(node_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WikiNode).where(WikiNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Wiki node not found")

    content = None
    if node.file_path and Path(node.file_path).exists():
        content = Path(node.file_path).read_text()

    return {
        "id": str(node.id),
        "title": node.title,
        "slug": node.slug,
        "summary": node.summary,
        "file_path": node.file_path,
        "bookmark_ids": [str(b) for b in node.bookmark_ids],
        "content": content,
        "updated_at": node.updated_at.isoformat(),
    }
