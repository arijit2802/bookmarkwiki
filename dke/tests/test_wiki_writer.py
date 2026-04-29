import pytest
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select

from backend.models.wiki_node import WikiNode
from backend.pipeline.wiki_writer import write_node


async def test_write_node_creates_markdown_file(db, tmp_path):
    bid = uuid4()
    node = await write_node(
        db, "RAG Architecture", "rag-architecture",
        "# RAG Architecture\n\n- Claim one", bid, wiki_dir=tmp_path
    )

    assert (tmp_path / "rag-architecture.md").exists()
    content = (tmp_path / "rag-architecture.md").read_text()
    assert "RAG Architecture" in content


async def test_write_node_inserts_wiki_node_in_db(db, tmp_path):
    bid = uuid4()
    node = await write_node(
        db, "Transformer Model", "transformer-model",
        "# Transformer Model\n\n- Attention is all you need", bid,
        wiki_dir=tmp_path
    )

    result = await db.execute(select(WikiNode).where(WikiNode.slug == "transformer-model"))
    saved = result.scalar_one()
    assert saved.title == "Transformer Model"
    assert bid in saved.bookmark_ids


async def test_write_node_updates_existing_node_on_slug_collision(db, tmp_path):
    bid1, bid2 = uuid4(), uuid4()
    await write_node(
        db, "Fine-tuning", "fine-tuning", "# Fine-tuning\n\n- Original", bid1,
        wiki_dir=tmp_path
    )
    await write_node(
        db, "Fine-tuning", "fine-tuning", "# Fine-tuning\n\n- Updated", bid2,
        wiki_dir=tmp_path
    )

    result = await db.execute(select(WikiNode).where(WikiNode.slug == "fine-tuning"))
    nodes = result.scalars().all()
    assert len(nodes) == 1  # no duplicate
    assert bid1 in nodes[0].bookmark_ids
    assert bid2 in nodes[0].bookmark_ids
    assert "Updated" in (tmp_path / "fine-tuning.md").read_text()
