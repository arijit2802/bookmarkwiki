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
