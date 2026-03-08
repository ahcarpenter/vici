from unittest.mock import AsyncMock, MagicMock

from src.extraction.schemas import ExtractionResult


def make_mock_openai_client(parsed_result: ExtractionResult):
    mock_message = MagicMock()
    mock_message.parsed = parsed_result
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    mock_completion.usage = mock_usage
    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_completion)
    mock_client.embeddings.create = AsyncMock(
        return_value=MagicMock(data=[MagicMock(embedding=[0.0] * 1536)])
    )
    return mock_client


def mock_pinecone_client():
    """AsyncMock context manager for Pinecone — used in Plan 02-02."""
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock
