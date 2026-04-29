from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from backend.db.postgres import async_session_factory
from backend.models.bookmark import Bookmark
from backend.models.wiki_node import WikiNode
from backend.pipeline.extractor import extract
from backend.pipeline.synthesizer import synthesize
from backend.pipeline.utils import extract_title_from_markdown, slugify
from backend.pipeline.wiki_writer import write_node


async def process_bookmark(bookmark_id: UUID, url_or_path: str) -> None:
    """Full pipeline: extract → synthesize (new or merge) → write wiki node."""
    async with async_session_factory() as db:
        result = await db.execute(select(Bookmark).where(Bookmark.id == bookmark_id))
        bookmark = result.scalar_one()
        bookmark.status = "processing"
        await db.commit()

        try:
            content = await extract(url_or_path)
            bookmark.title = content.title
            bookmark.content_type = content.content_type

            # First synthesis pass to determine concept title
            initial_markdown = synthesize(content)
            title = extract_title_from_markdown(initial_markdown)
            slug = slugify(title)

            # Check if a node with this slug already exists → merge
            existing_result = await db.execute(
                select(WikiNode).where(WikiNode.slug == slug)
            )
            existing_node = existing_result.scalar_one_or_none()

            if existing_node and existing_node.file_path:
                existing_markdown = Path(existing_node.file_path).read_text()
                final_markdown = synthesize(content, existing_node=existing_markdown)
                final_title = extract_title_from_markdown(final_markdown)
                final_slug = slugify(final_title)
            else:
                final_markdown = initial_markdown
                final_title = title
                final_slug = slug

            await write_node(db, final_title, final_slug, final_markdown, bookmark_id)
            bookmark.status = "done"

        except Exception as e:
            bookmark.status = "failed"
            bookmark.error = str(e)

        await db.commit()
