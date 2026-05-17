from uuid import uuid4

from backend.models.bookmark import Bookmark
from backend.models.wiki_node import WikiNode


def test_bookmark_python_defaults():
    bm = Bookmark(url="https://example.com", source="manual", tags=["ai"])
    assert bm.status == "pending"
    assert bm.tags == ["ai"]
    assert bm.url == "https://example.com"
    assert bm.source == "manual"


def test_wiki_node_python_attributes():
    bid = uuid4()
    node = WikiNode(title="RAG Architecture", slug="rag-architecture", bookmark_ids=[bid])
    assert node.title == "RAG Architecture"
    assert node.slug == "rag-architecture"
    assert bid in node.bookmark_ids
