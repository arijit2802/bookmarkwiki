from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.wiki_node import WikiNode


async def write_node(
    db: AsyncSession,
    title: str,
    slug: str,
    markdown: str,
    bookmark_id: UUID,
    wiki_dir: Path | str | None = None,
) -> WikiNode:
    """Write or update a wiki node on disk and in the database."""
    from backend.config import settings

    wiki_dir = Path(wiki_dir) if wiki_dir is not None else Path(settings.wiki_dir)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    file_path = str(wiki_dir / f"{slug}.md")
    summary = markdown[:300]

    result = await db.execute(select(WikiNode).where(WikiNode.slug == slug))
    existing = result.scalar_one_or_none()

    if existing:
        existing.bookmark_ids = list({*existing.bookmark_ids, bookmark_id})
        existing.summary = summary
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
        bookmark_ids=[bookmark_id],
    )
    db.add(node)
    Path(file_path).write_text(markdown)
    await db.commit()
    await db.refresh(node)
    return node
