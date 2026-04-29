import pytest
from uuid import UUID
from sqlalchemy import select

from backend.models.bookmark import Bookmark
from backend.models.wiki_node import WikiNode


async def test_bookmark_can_be_inserted_and_retrieved(db):
    bm = Bookmark(url="https://example.com", source="manual", tags=["ai"])
    db.add(bm)
    await db.commit()

    result = await db.execute(select(Bookmark).where(Bookmark.url == "https://example.com"))
    saved = result.scalar_one()
    assert saved.status == "pending"
    assert saved.tags == ["ai"]
    assert isinstance(saved.id, UUID)


async def test_wiki_node_can_be_inserted_and_retrieved(db):
    from uuid import uuid4
    bid = uuid4()
    node = WikiNode(title="RAG Architecture", slug="rag-architecture", bookmark_ids=[bid])
    db.add(node)
    await db.commit()

    result = await db.execute(select(WikiNode).where(WikiNode.slug == "rag-architecture"))
    saved = result.scalar_one()
    assert saved.title == "RAG Architecture"
    assert bid in saved.bookmark_ids
