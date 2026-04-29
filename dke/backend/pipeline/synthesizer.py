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
