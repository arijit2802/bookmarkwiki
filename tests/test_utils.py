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
