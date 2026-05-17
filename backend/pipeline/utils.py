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
