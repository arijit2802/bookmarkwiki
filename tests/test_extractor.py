import pytest
from backend.pipeline.extractor import ExtractedContent


def test_extracted_content_dataclass_creation():
    """Simple test to verify ExtractedContent can be instantiated"""
    content = ExtractedContent(
        title="Test",
        text="Test content",
        content_type="webpage"
    )
    assert content.title == "Test"
    assert content.content_type == "webpage"
