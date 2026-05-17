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
