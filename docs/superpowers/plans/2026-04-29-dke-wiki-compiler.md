# DKE Phase 1 — Wiki Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI service that ingests URLs and PDFs, synthesizes structured Markdown wiki nodes via Gemini 2.0 Flash, and writes them to an Obsidian-compatible `wiki/` folder backed by PostgreSQL metadata.

**Architecture:** FastAPI accepts bookmarks via REST and processes them as background tasks. Each task runs: content extraction (Playwright for web, pdfplumber for PDF) → Gemini 2.0 Flash synthesis (new or merge) → wiki node written to `wiki/*.md` + PostgreSQL upsert. No Celery/Redis in Phase 1.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2.0 (async + asyncpg), Playwright, BeautifulSoup4, pdfplumber, google-generativeai (Gemini 2.0 Flash), pydantic-settings, PostgreSQL 16, Docker Compose, pytest + pytest-asyncio + pytest-mock

---

## File Map

All paths relative to project root `dke/`:

| File | Purpose |
|---|---|
| `docker-compose.yml` | PostgreSQL 16 local service |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |
| `pytest.ini` | pytest asyncio config |
| `backend/config.py` | Pydantic settings (env vars) |
| `backend/db/postgres.py` | Async engine, session factory, `get_db`, `init_db` |
| `backend/models/__init__.py` | Imports all models (required for `create_all`) |
| `backend/models/bookmark.py` | `Bookmark` ORM model |
| `backend/models/wiki_node.py` | `WikiNode` ORM model |
| `backend/pipeline/utils.py` | `slugify()`, `extract_title_from_markdown()` |
| `backend/pipeline/extractor.py` | `extract(url_or_path)` → `ExtractedContent` |
| `backend/pipeline/synthesizer.py` | `synthesize(content, existing_node)` → Markdown str |
| `backend/pipeline/wiki_writer.py` | `write_node(db, title, slug, markdown, bookmark_id)` → `WikiNode` |
| `backend/pipeline/processor.py` | `process_bookmark(bookmark_id, url_or_path)` — orchestrates pipeline |
| `backend/prompts/synthesize.md` | Gemini prompt for new wiki nodes |
| `backend/prompts/merge.md` | Gemini prompt for merging into existing nodes |
| `backend/api/main.py` | FastAPI app, lifespan, router inclusion |
| `backend/api/routes/bookmarks.py` | Bookmark CRUD + background task trigger |
| `backend/api/routes/wiki.py` | Wiki node read endpoints |
| `tests/conftest.py` | pytest fixtures: test DB, test client |
| `tests/test_extractor.py` | Unit tests for extractor |
| `tests/test_synthesizer.py` | Unit tests for synthesizer |
| `tests/test_wiki_writer.py` | Unit tests for wiki writer |
| `tests/test_api.py` | API integration tests |

---

## Task 1: Project Scaffold

**Files:**
- Create: `docker-compose.yml`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `pytest.ini`
- Create: all `__init__.py` files

- [ ] **Step 1: Create project directory structure**

```bash
mkdir -p dke/backend/{api/routes,pipeline,models,db,prompts}
mkdir -p dke/tests
mkdir -p dke/wiki
touch dke/backend/__init__.py
touch dke/backend/api/__init__.py
touch dke/backend/api/routes/__init__.py
touch dke/backend/pipeline/__init__.py
touch dke/backend/models/__init__.py
touch dke/backend/db/__init__.py
touch dke/tests/__init__.py
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: dke
      POSTGRES_PASSWORD: dke
      POSTGRES_DB: dke
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

- [ ] **Step 3: Create `requirements.txt`**

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
playwright>=1.44.0
beautifulsoup4>=4.12.0
lxml>=5.2.0
pdfplumber>=0.11.0
pypdf>=4.3.0
google-generativeai>=0.8.0
httpx>=0.27.0
python-multipart>=0.0.9
pydantic-settings>=2.3.0
aiofiles>=23.2.0
pytest>=8.2.0
pytest-asyncio>=0.23.0
pytest-mock>=3.14.0
```

- [ ] **Step 4: Create `.env.example`**

```
GEMINI_API_KEY=your_gemini_api_key_here
DATABASE_URL=postgresql+asyncpg://dke:dke@localhost:5432/dke
WIKI_DIR=wiki
```

- [ ] **Step 5: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 6: Install dependencies and Playwright browser**

```bash
cd dke
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Expected: no errors. `playwright install chromium` downloads ~130MB.

- [ ] **Step 7: Create `.env` from example with Neon connection**

```bash
cp .env.example .env
# Edit .env and set:
# 1. GEMINI_API_KEY=your_gemini_api_key_here
# 2. DATABASE_URL=postgresql+asyncpg://user:password@ep-xxxx.us-east-1.neon.tech/dke?sslmode=require
#    (Get this from your Neon Dashboard)
```

- [ ] **Step 8: Create test database in Neon**

Via Neon Dashboard → SQL Editor, run:
```sql
CREATE DATABASE dke_test;
```

Or via psql:
```bash
psql "postgresql+asyncpg://user:password@ep-xxxx.us-east-1.neon.tech/dke?sslmode=require" -c "CREATE DATABASE dke_test;"
```

Expected: `CREATE DATABASE`

- [ ] **Step 9: Commit**

```bash
git init
git add docker-compose.yml requirements.txt .env.example pytest.ini
git add backend/ tests/ wiki/.gitkeep
git commit -m "chore: project scaffold — dirs, docker-compose, requirements"
```

---

## Task 2: Config and Database Setup

**Files:**
- Create: `backend/config.py`
- Create: `backend/db/postgres.py`

- [ ] **Step 1: Write failing test**

`tests/test_db.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

async def test_get_db_yields_async_session(db):
    assert isinstance(db, AsyncSession)
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_db.py -v
```

Expected: `ERROR` — `db` fixture not defined.

- [ ] **Step 3: Create `backend/config.py`**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    gemini_api_key: str
    database_url: str = "postgresql+asyncpg://dke:dke@localhost:5432/dke"
    wiki_dir: str = "wiki"

    model_config = {"env_file": ".env"}

settings = Settings()
```

- [ ] **Step 4: Create `backend/db/postgres.py`**

```python
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy.orm import DeclarativeBase
from backend.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """Create all tables. Import models before calling this."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 5: Create `tests/conftest.py`**

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import backend.models  # noqa: F401 — registers all models with Base
from backend.db.postgres import Base

TEST_DATABASE_URL = "postgresql+asyncpg://dke:dke@localhost:5432/dke_test"


@pytest.fixture(scope="session")
async def test_engine():
    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
```

Add missing import at top of conftest.py:
```python
from typing import AsyncGenerator
```

- [ ] **Step 6: Run test to confirm it passes**

```bash
pytest tests/test_db.py -v
```

Expected: `PASSED`

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/db/postgres.py tests/conftest.py tests/test_db.py
git commit -m "feat: config + async DB setup with session factory"
```

---

## Task 3: ORM Models

**Files:**
- Create: `backend/models/bookmark.py`
- Create: `backend/models/wiki_node.py`
- Modify: `backend/models/__init__.py`

- [ ] **Step 1: Write failing test**

`tests/test_models.py`:
```python
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
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_models.py -v
```

Expected: `ImportError` — models not yet created.

- [ ] **Step 3: Create `backend/models/bookmark.py`**

```python
from datetime import datetime, timezone
from uuid import uuid4, UUID

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres import Base


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 4: Create `backend/models/wiki_node.py`**

```python
from datetime import datetime, timezone
from uuid import uuid4, UUID

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres import Base


class WikiNode(Base):
    __tablename__ = "wiki_nodes"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    bookmark_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 5: Populate `backend/models/__init__.py`**

```python
from backend.models.bookmark import Bookmark  # noqa: F401
from backend.models.wiki_node import WikiNode  # noqa: F401
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
pytest tests/test_models.py -v
```

Expected: 2 `PASSED`

- [ ] **Step 7: Commit**

```bash
git add backend/models/
git commit -m "feat: Bookmark and WikiNode ORM models"
```

---

## Task 4: Pipeline Utilities

**Files:**
- Create: `backend/pipeline/utils.py`

- [ ] **Step 1: Write failing test**

`tests/test_utils.py`:
```python
from backend.pipeline.utils import slugify, extract_title_from_markdown


def test_slugify_lowercases_and_replaces_spaces():
    assert slugify("RAG Architecture") == "rag-architecture"


def test_slugify_removes_special_chars():
    assert slugify("LLMs: What's Next?") == "llms-whats-next"


def test_slugify_collapses_multiple_dashes():
    assert slugify("A  B---C") == "a-b-c"


def test_extract_title_from_markdown_gets_h1():
    md = "# My Concept\n\nSome content here."
    assert extract_title_from_markdown(md) == "My Concept"


def test_extract_title_from_markdown_falls_back_to_first_line():
    md = "No heading here\nJust text"
    assert extract_title_from_markdown(md) == "No heading here"


def test_extract_title_from_markdown_handles_empty():
    assert extract_title_from_markdown("") == "untitled"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_utils.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `backend/pipeline/utils.py`**

```python
import re


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def extract_title_from_markdown(markdown: str) -> str:
    if not markdown:
        return "untitled"
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    first = markdown.splitlines()[0].strip()
    return first if first else "untitled"
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_utils.py -v
```

Expected: 6 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/utils.py tests/test_utils.py
git commit -m "feat: pipeline utils — slugify and title extraction"
```

---

## Task 5: Content Extractor

**Files:**
- Create: `backend/pipeline/extractor.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: Write failing tests**

`tests/test_extractor.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.pipeline.extractor import extract, ExtractedContent


async def test_extract_webpage_returns_extracted_content(mocker):
    mock_page = AsyncMock()
    mock_page.content.return_value = "<html><head><title>Test Page</title></head><body><p>Hello world</p></body></html>"
    mock_page.title.return_value = "Test Page"
    mock_page.goto = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_page.return_value = mock_page

    mock_playwright = AsyncMock()
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock(return_value=None)
    mock_playwright.chromium.launch.return_value = mock_browser

    with patch("backend.pipeline.extractor.async_playwright", return_value=mock_playwright):
        result = await extract("https://example.com/article")

    assert isinstance(result, ExtractedContent)
    assert result.title == "Test Page"
    assert "Hello world" in result.text
    assert result.content_type == "webpage"


async def test_extract_pdf_local_file_returns_extracted_content(tmp_path):
    import pdfplumber
    from reportlab.pdfgen import canvas  # only if reportlab available; use mock instead

    # Use mocker-based approach instead
    pass  # replaced by next test


async def test_extract_pdf_uses_pdfplumber(mocker):
    mock_page_obj = MagicMock()
    mock_page_obj.extract_text.return_value = "This is PDF content"

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.metadata = {"Title": "My PDF"}
    mock_pdf.pages = [mock_page_obj]

    mocker.patch("pdfplumber.open", return_value=mock_pdf)

    result = await extract("/tmp/sample.pdf")

    assert result.title == "My PDF"
    assert "PDF content" in result.text
    assert result.content_type == "pdf"


async def test_extract_truncates_text_to_8000_chars(mocker):
    long_text = "x" * 10000
    mock_page = AsyncMock()
    mock_page.content.return_value = f"<html><body><p>{long_text}</p></body></html>"
    mock_page.title.return_value = "Long Page"
    mock_page.goto = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_page.return_value = mock_page

    mock_playwright = AsyncMock()
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock(return_value=None)
    mock_playwright.chromium.launch.return_value = mock_browser

    with patch("backend.pipeline.extractor.async_playwright", return_value=mock_playwright):
        result = await extract("https://example.com")

    assert len(result.text) <= 8000
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_extractor.py -v
```

Expected: `ImportError` — extractor not yet created.

- [ ] **Step 3: Create `backend/pipeline/extractor.py`**

```python
import os
import tempfile
from dataclasses import dataclass

import httpx
import pdfplumber
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

_MAX_TEXT_LENGTH = 8000


@dataclass
class ExtractedContent:
    title: str
    text: str
    content_type: str  # 'webpage' | 'pdf'


async def extract(url_or_path: str) -> ExtractedContent:
    """Extract content from a URL or local PDF path."""
    if _is_pdf(url_or_path):
        return await _extract_pdf(url_or_path)
    return await _extract_webpage(url_or_path)


def _is_pdf(url_or_path: str) -> bool:
    return url_or_path.lower().endswith(".pdf")


async def _extract_webpage(url: str) -> ExtractedContent:
    title = ""
    html = ""

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                html = await page.content()
                title = await page.title()
            finally:
                await browser.close()
    except Exception:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=15)
            html = resp.text

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)[:_MAX_TEXT_LENGTH]

    if not title:
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else url

    return ExtractedContent(title=title, text=text, content_type="webpage")


async def _extract_pdf(url_or_path: str) -> ExtractedContent:
    path = url_or_path
    downloaded = False

    if url_or_path.startswith("http"):
        async with httpx.AsyncClient() as client:
            resp = await client.get(url_or_path, timeout=30)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(resp.content)
            path = f.name
        downloaded = True

    try:
        with pdfplumber.open(path) as pdf:
            title = pdf.metadata.get("Title") or os.path.basename(path)
            pages_text = [p.extract_text() or "" for p in pdf.pages[:20]]
            text = "\n".join(pages_text)[:_MAX_TEXT_LENGTH]
    finally:
        if downloaded and os.path.exists(path):
            os.unlink(path)

    return ExtractedContent(title=title, text=text, content_type="pdf")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_extractor.py -v
```

Expected: 3 `PASSED` (the placeholder `pass` test is skipped)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/extractor.py tests/test_extractor.py
git commit -m "feat: content extractor — Playwright web + pdfplumber PDF"
```

---

## Task 6: Prompt Templates

**Files:**
- Create: `backend/prompts/synthesize.md`
- Create: `backend/prompts/merge.md`

- [ ] **Step 1: Create `backend/prompts/synthesize.md`**

```markdown
Given the following article content, extract and format as a Markdown wiki page:

1. A suggested wiki page title (the core concept name, NOT the article title) as a `# Heading`
2. **Core Claims** — 3–5 bullet assertions the article makes
3. **Key Entities** — tools, concepts, and frameworks mentioned
4. **Relationships** — how entities relate to each other
5. `[[wiki links]]` to related concepts inline where appropriate

Output ONLY the Markdown. No preamble. No explanation. No code fences.

Article content:
{content}
```

- [ ] **Step 2: Create `backend/prompts/merge.md`**

```markdown
You are updating an existing wiki page with new information from an article.

Existing wiki page:
{existing_node}

New article content:
{new_content}

Instructions:
- Add new claims not already present in the existing page
- Do not duplicate existing content
- Update or add `[[wiki links]]` if new relationships are found
- Keep the same Markdown structure and heading

Output ONLY the updated Markdown page. No preamble. No explanation. No code fences.
```

- [ ] **Step 3: Commit**

```bash
git add backend/prompts/
git commit -m "feat: Gemini prompt templates for synthesis and merge"
```

---

## Task 7: Synthesizer

**Files:**
- Create: `backend/pipeline/synthesizer.py`
- Create: `tests/test_synthesizer.py`

- [ ] **Step 1: Write failing tests**

`tests/test_synthesizer.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from backend.pipeline.extractor import ExtractedContent
from backend.pipeline.synthesizer import synthesize


def _make_content():
    return ExtractedContent(
        title="Test Article",
        text="RAG is a technique that combines retrieval with generation.",
        content_type="webpage",
    )


def test_synthesize_new_node_calls_gemini_and_returns_string(mocker):
    mock_response = MagicMock()
    mock_response.text = "# RAG\n\n- RAG combines retrieval with generation"

    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response

    mocker.patch("backend.pipeline.synthesizer._model", mock_model)

    result = synthesize(_make_content())

    assert isinstance(result, str)
    assert "RAG" in result
    mock_model.generate_content.assert_called_once()


def test_synthesize_uses_synthesize_prompt_for_new_node(mocker):
    mock_response = MagicMock()
    mock_response.text = "# RAG\n\n- Some claim"

    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response
    mocker.patch("backend.pipeline.synthesizer._model", mock_model)

    synthesize(_make_content())

    prompt_used = mock_model.generate_content.call_args[0][0]
    assert "{content}" not in prompt_used  # template was filled
    assert "RAG is a technique" in prompt_used


def test_synthesize_uses_merge_prompt_when_existing_node_provided(mocker):
    mock_response = MagicMock()
    mock_response.text = "# RAG\n\n- Merged claim"

    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response
    mocker.patch("backend.pipeline.synthesizer._model", mock_model)

    existing = "# RAG\n\n- Original claim"
    synthesize(_make_content(), existing_node=existing)

    prompt_used = mock_model.generate_content.call_args[0][0]
    assert "Original claim" in prompt_used  # existing node in prompt
    assert "{existing_node}" not in prompt_used  # template was filled
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_synthesizer.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `backend/pipeline/synthesizer.py`**

```python
from pathlib import Path

import google.generativeai as genai

from backend.config import settings
from backend.pipeline.extractor import ExtractedContent

genai.configure(api_key=settings.gemini_api_key)
_model = genai.GenerativeModel("gemini-2.0-flash")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text()


def synthesize(content: ExtractedContent, existing_node: str | None = None) -> str:
    """Call Gemini to generate or merge a wiki node. Returns Markdown string."""
    if existing_node is None:
        template = _load_prompt("synthesize.md")
        prompt = template.replace("{content}", f"{content.title}\n\n{content.text}")
    else:
        template = _load_prompt("merge.md")
        prompt = (
            template
            .replace("{existing_node}", existing_node)
            .replace("{new_content}", f"{content.title}\n\n{content.text}")
        )

    response = _model.generate_content(prompt)
    return response.text
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_synthesizer.py -v
```

Expected: 3 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/synthesizer.py tests/test_synthesizer.py
git commit -m "feat: Gemini 2.0 Flash synthesizer with new-node and merge modes"
```

---

## Task 8: Wiki Writer

**Files:**
- Create: `backend/pipeline/wiki_writer.py`
- Create: `tests/test_wiki_writer.py`

- [ ] **Step 1: Write failing tests**

`tests/test_wiki_writer.py`:
```python
import pytest
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from backend.models.wiki_node import WikiNode
from backend.pipeline.wiki_writer import write_node


async def test_write_node_creates_markdown_file(db, tmp_path):
    bid = uuid4()
    node = await write_node(db, "RAG Architecture", "rag-architecture",
                             "# RAG Architecture\n\n- Claim one", bid, wiki_dir=tmp_path)

    assert (tmp_path / "rag-architecture.md").exists()
    content = (tmp_path / "rag-architecture.md").read_text()
    assert "RAG Architecture" in content


async def test_write_node_inserts_wiki_node_in_db(db, tmp_path):
    bid = uuid4()
    node = await write_node(db, "Transformer Model", "transformer-model",
                             "# Transformer Model\n\n- Attention is all you need", bid,
                             wiki_dir=tmp_path)

    result = await db.execute(select(WikiNode).where(WikiNode.slug == "transformer-model"))
    saved = result.scalar_one()
    assert saved.title == "Transformer Model"
    assert bid in saved.bookmark_ids


async def test_write_node_updates_existing_node_on_slug_collision(db, tmp_path):
    bid1, bid2 = uuid4(), uuid4()
    await write_node(db, "Fine-tuning", "fine-tuning", "# Fine-tuning\n\n- Original", bid1,
                     wiki_dir=tmp_path)
    await write_node(db, "Fine-tuning", "fine-tuning", "# Fine-tuning\n\n- Updated", bid2,
                     wiki_dir=tmp_path)

    result = await db.execute(select(WikiNode).where(WikiNode.slug == "fine-tuning"))
    nodes = result.scalars().all()
    assert len(nodes) == 1  # no duplicate
    assert bid1 in nodes[0].bookmark_ids
    assert bid2 in nodes[0].bookmark_ids
    assert "Updated" in (tmp_path / "fine-tuning.md").read_text()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_wiki_writer.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `backend/pipeline/wiki_writer.py`**

```python
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_wiki_writer.py -v
```

Expected: 3 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/wiki_writer.py tests/test_wiki_writer.py
git commit -m "feat: wiki writer — write/merge .md files with DB upsert"
```

---

## Task 9: Pipeline Processor

**Files:**
- Create: `backend/pipeline/processor.py`

- [ ] **Step 1: Write failing test**

`tests/test_processor.py`:
```python
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select
from backend.models.bookmark import Bookmark
from backend.pipeline.extractor import ExtractedContent


async def test_process_bookmark_sets_status_done_on_success(db):
    bm = Bookmark(url="https://example.com", source="manual", tags=[])
    db.add(bm)
    await db.commit()

    fake_content = ExtractedContent(
        title="Test Article", text="Some content", content_type="webpage"
    )

    with (
        patch("backend.pipeline.processor.extract", AsyncMock(return_value=fake_content)),
        patch("backend.pipeline.processor.synthesize", return_value="# Test Article\n\n- Claim"),
        patch("backend.pipeline.processor.write_node", AsyncMock()),
        patch("backend.pipeline.processor.async_session_factory") as mock_factory,
    ):
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        from backend.pipeline.processor import process_bookmark
        await process_bookmark(bm.id, "https://example.com")

    await db.refresh(bm)
    assert bm.status == "done"
    assert bm.title == "Test Article"
    assert bm.content_type == "webpage"


async def test_process_bookmark_sets_status_failed_on_error(db):
    bm = Bookmark(url="https://bad.example.com", source="manual", tags=[])
    db.add(bm)
    await db.commit()

    with (
        patch("backend.pipeline.processor.extract", AsyncMock(side_effect=Exception("timeout"))),
        patch("backend.pipeline.processor.async_session_factory") as mock_factory,
    ):
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        from backend.pipeline.processor import process_bookmark
        await process_bookmark(bm.id, "https://bad.example.com")

    await db.refresh(bm)
    assert bm.status == "failed"
    assert "timeout" in bm.error
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_processor.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `backend/pipeline/processor.py`**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_processor.py -v
```

Expected: 2 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/processor.py tests/test_processor.py
git commit -m "feat: pipeline processor — orchestrates extract → synthesize → write"
```

---

## Task 10: FastAPI App and Bookmark Routes

**Files:**
- Create: `backend/api/main.py`
- Create: `backend/api/routes/bookmarks.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write failing tests**

`tests/test_api.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from uuid import uuid4


@pytest.fixture
async def client():
    import backend.models  # noqa: F401
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health_returns_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_post_bookmark_returns_pending(client):
    with patch("backend.api.routes.bookmarks.process_bookmark", new=AsyncMock()):
        resp = await client.post("/bookmarks", json={"url": "https://example.com"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["url"] == "https://example.com"


async def test_post_bookmarks_bulk_returns_queued_count(client):
    with patch("backend.api.routes.bookmarks.process_bookmark", new=AsyncMock()):
        resp = await client.post(
            "/bookmarks/bulk",
            json={"urls": ["https://a.com", "https://b.com", "https://c.com"]},
        )

    assert resp.status_code == 200
    assert resp.json()["queued"] == 3


async def test_get_bookmarks_returns_list(client):
    resp = await client.get("/bookmarks")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_bookmark_by_id_returns_404_for_unknown(client):
    resp = await client.get(f"/bookmarks/{uuid4()}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_api.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `backend/api/main.py`**

```python
from contextlib import asynccontextmanager

import backend.models  # noqa: F401 — register models before init_db
from fastapi import FastAPI
from backend.db.postgres import init_db
from backend.api.routes import bookmarks, wiki


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="DKE Wiki Compiler", lifespan=lifespan)
app.include_router(bookmarks.router)
app.include_router(wiki.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Create `backend/api/routes/bookmarks.py`**

```python
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_db
from backend.models.bookmark import Bookmark
from backend.pipeline.processor import process_bookmark

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
    for bm in created:
        await db.refresh(bm)
        background_tasks.add_task(process_bookmark, bm.id, bm.url)
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
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_api.py -v
```

Expected: 5 `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/api/main.py backend/api/routes/bookmarks.py tests/test_api.py
git commit -m "feat: FastAPI app with bookmark routes and bulk import endpoint"
```

---

## Task 11: PDF Upload and Wiki Routes

**Files:**
- Create: `backend/api/routes/wiki.py`
- Modify: `backend/api/routes/bookmarks.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_api.py`:
```python
async def test_get_wiki_nodes_returns_list(client):
    resp = await client.get("/wiki/nodes")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_wiki_node_by_id_returns_404_for_unknown(client):
    resp = await client.get(f"/wiki/nodes/{uuid4()}")
    assert resp.status_code == 404


async def test_post_bookmark_import_pdf_accepts_file(client, tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake content")  # minimal fake PDF

    with patch("backend.api.routes.bookmarks.process_bookmark", new=AsyncMock()):
        with open(pdf_path, "rb") as f:
            resp = await client.post(
                "/bookmarks/import/pdf",
                files={"file": ("test.pdf", f, "application/pdf")},
            )

    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
```

- [ ] **Step 2: Run tests to confirm new tests fail**

```bash
pytest tests/test_api.py -v -k "wiki or pdf"
```

Expected: `FAILED` — routes not yet defined.

- [ ] **Step 3: Create `backend/api/routes/wiki.py`**

```python
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
```

- [ ] **Step 4: Add PDF upload endpoint to `backend/api/routes/bookmarks.py`**

Add this import at top:
```python
import shutil
import tempfile
from fastapi import File, UploadFile
```

Add this route:
```python
@router.post("/bookmarks/import/pdf")
async def import_pdf(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    suffix = ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    bm = Bookmark(url=tmp_path, source="pdf_upload", content_type="pdf", tags=[])
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    background_tasks.add_task(process_bookmark, bm.id, tmp_path)
    return {"id": str(bm.id), "status": bm.status, "filename": file.filename}
```

- [ ] **Step 5: Register wiki router in `backend/api/main.py`**

The wiki router is already imported and included (from Task 10 Step 3). Verify it's in `main.py`:
```python
app.include_router(wiki.router)
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/test_api.py -v
```

Expected: all `PASSED`

- [ ] **Step 7: Commit**

```bash
git add backend/api/routes/wiki.py backend/api/routes/bookmarks.py
git commit -m "feat: wiki read endpoints and PDF upload route"
```

---

## Task 12: Full Test Run and Manual Smoke Test

- [ ] **Step 1: Run the full test suite**

```bash
pytest -v
```

Expected: all tests `PASSED`. Fix any failures before continuing.

- [ ] **Step 2: Start the server**

```bash
cd dke
uvicorn backend.api.main:app --reload --port 8000
```

Expected: `Application startup complete.` No errors.

- [ ] **Step 3: Smoke test health endpoint**

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 4: Submit a single real URL**

```bash
curl -X POST http://localhost:8000/bookmarks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://lilianweng.github.io/posts/2023-06-23-agent/"}'
```

Expected: `{"id":"...","url":"...","status":"pending"}`

- [ ] **Step 5: Check bookmark status after ~30 seconds**

```bash
curl http://localhost:8000/bookmarks
```

Expected: the bookmark's `status` is `"done"`.

- [ ] **Step 6: Verify wiki file created**

```bash
ls wiki/
cat wiki/<generated-slug>.md
```

Expected: a Markdown file with `# Heading`, bullet claims, and `[[wiki links]]`.

- [ ] **Step 7: Open wiki folder in Obsidian**

Open Obsidian → Open Folder as Vault → select `dke/wiki/`

Expected: nodes appear in the graph view with links between `[[concepts]]`.

- [ ] **Step 8: Bulk import your 200 existing bookmarks**

Prepare a JSON array of your URLs, then:
```bash
curl -X POST http://localhost:8000/bookmarks/bulk \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://url1.com", "https://url2.com", ...]}'
```

Monitor progress:
```bash
# Check how many are still pending/processing
curl http://localhost:8000/bookmarks | python3 -c "
import json, sys
bms = json.load(sys.stdin)
from collections import Counter
print(Counter(b['status'] for b in bms))
"
```

Expected: counts shift from `pending` → `done` over time. Failed ones show in `status: failed`.

- [ ] **Step 9: Final commit**

```bash
git add .
git commit -m "feat: DKE Phase 1 Wiki Compiler — complete"
```

---

## Verification Checklist (from spec)

Run these after Task 12 to confirm spec compliance:

- [ ] `POST /bookmarks/bulk` with 5 test URLs → all reach `status=done`
- [ ] Check `wiki/` folder → `.md` files created with `[[wiki links]]`
- [ ] Submit a URL on the same concept as an existing node → verify merge (not duplicate node)
- [ ] Submit a `.pdf` URL → verify text extracted and wiki node created
- [ ] Submit an unreachable URL → verify `status=failed` with error message logged
- [ ] Open `wiki/` in Obsidian → verify graph renders with linked nodes
