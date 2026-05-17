from uuid import uuid4

from backend.models.wiki_node import WikiNode
from backend.pipeline.wiki_writer import write_node


async def test_write_node_creates_markdown_file(db, tmp_path):
    bid = uuid4()
    await write_node(
        db, "RAG Architecture", "rag-architecture",
        "# RAG Architecture\n\n- Claim one", bid, wiki_dir=tmp_path,
    )

    assert (tmp_path / "rag-architecture.md").exists()
    content = (tmp_path / "rag-architecture.md").read_text()
    assert "RAG Architecture" in content


async def test_write_node_inserts_wiki_node_in_db(db, tmp_path):
    bid = uuid4()
    await write_node(
        db, "Transformer Model", "transformer-model",
        "# Transformer Model\n\n- Attention is all you need", bid, wiki_dir=tmp_path,
    )

    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert isinstance(added, WikiNode)
    assert added.title == "Transformer Model"
    assert bid in added.bookmark_ids


async def test_write_node_updates_existing_node_on_slug_collision(db, tmp_path):
    bid1, bid2 = uuid4(), uuid4()

    # First call: no existing node → creates new
    db.execute.return_value.scalar_one_or_none.return_value = None
    node1 = await write_node(
        db, "Fine-tuning", "fine-tuning", "# Fine-tuning\n\n- Original", bid1, wiki_dir=tmp_path,
    )

    # Second call: existing node found → updates it
    db.execute.return_value.scalar_one_or_none.return_value = node1
    db.add.reset_mock()
    await write_node(
        db, "Fine-tuning", "fine-tuning", "# Fine-tuning\n\n- Updated", bid2, wiki_dir=tmp_path,
    )

    db.add.assert_not_called()
    assert bid1 in node1.bookmark_ids
    assert bid2 in node1.bookmark_ids
    assert "Updated" in (tmp_path / "fine-tuning.md").read_text()
