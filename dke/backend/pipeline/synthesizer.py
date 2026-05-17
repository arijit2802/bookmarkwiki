from pathlib import Path

from openai import OpenAI

from backend.config import settings
from backend.pipeline.extractor import ExtractedContent

_client = OpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
_MODEL = settings.groq_model

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text()


def synthesize(content: ExtractedContent, existing_node: str | None = None) -> str:
    """Call Groq to generate or merge a wiki node. Returns Markdown string."""
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

    response = _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""
