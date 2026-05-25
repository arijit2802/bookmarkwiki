from unittest.mock import MagicMock

from backend.pipeline.extractor import ExtractedContent
from backend.pipeline.synthesizer import synthesize


def _make_content():
    return ExtractedContent(
        title="Test Article",
        text="RAG is a technique that combines retrieval with generation.",
        content_type="webpage",
    )


def _make_mock_client(text: str):
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def test_synthesize_new_node_calls_groq_and_returns_string(mocker):
    mock_client = _make_mock_client("# RAG\n\n- RAG combines retrieval with generation")
    mocker.patch("backend.pipeline.synthesizer._client", mock_client)

    result = synthesize(_make_content())

    assert isinstance(result, str)
    assert "RAG" in result
    mock_client.chat.completions.create.assert_called_once()


def test_synthesize_uses_synthesize_prompt_for_new_node(mocker):
    mock_client = _make_mock_client("# RAG\n\n- Some claim")
    mocker.patch("backend.pipeline.synthesizer._client", mock_client)

    synthesize(_make_content())

    prompt_used = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "{content}" not in prompt_used  # template was filled
    assert "RAG is a technique" in prompt_used


def test_synthesize_uses_merge_prompt_when_existing_node_provided(mocker):
    mock_client = _make_mock_client("# RAG\n\n- Merged claim")
    mocker.patch("backend.pipeline.synthesizer._client", mock_client)

    existing = "# RAG\n\n- Original claim"
    synthesize(_make_content(), existing_node=existing)

    prompt_used = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "Original claim" in prompt_used  # existing node in prompt
    assert "{existing_node}" not in prompt_used  # template was filled
