"""Tests for the search_job_embeddings Pinecone read adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.extraction.utils import search_job_embeddings
from tests.extraction.conftest import make_mock_openai_client


def _mock_pinecone_cls(matches):
    """Mock the PineconeAsyncio class: pc and index async context managers."""
    resp = MagicMock(matches=matches)
    idx = AsyncMock()
    idx.query = AsyncMock(return_value=resp)
    idx_cm = AsyncMock()
    idx_cm.__aenter__ = AsyncMock(return_value=idx)
    idx_cm.__aexit__ = AsyncMock(return_value=None)
    pc = MagicMock()
    pc.IndexAsyncio = MagicMock(return_value=idx_cm)
    pc_cm = AsyncMock()
    pc_cm.__aenter__ = AsyncMock(return_value=pc)
    pc_cm.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=pc_cm), idx


@pytest.mark.asyncio
async def test_search_returns_ranked_int_ids_and_skips_junk():
    openai_client = make_mock_openai_client(MagicMock())
    pinecone_cls, idx = _mock_pinecone_cls(
        [
            MagicMock(id="7", score=0.9),
            MagicMock(id="junk", score=0.5),
            MagicMock(id="3", score=0.1),
        ]
    )
    settings = MagicMock()

    with patch("src.extraction.utils.PineconeAsyncio", pinecone_cls):
        ranked = await search_job_embeddings(
            query_text="need moving work",
            top_k=50,
            openai_client=openai_client,
            settings=settings,
        )

    assert ranked == [(7, 0.9), (3, 0.1)]
    idx.query.assert_awaited_once()
    assert idx.query.await_args.kwargs["top_k"] == 50


@pytest.mark.asyncio
async def test_search_raises_on_pinecone_failure():
    """The adapter propagates failures — MatchService owns degradation."""
    openai_client = make_mock_openai_client(MagicMock())
    pinecone_cls, idx = _mock_pinecone_cls([])
    idx.query = AsyncMock(side_effect=RuntimeError("Pinecone down"))
    settings = MagicMock()

    with (
        patch("src.extraction.utils.PineconeAsyncio", pinecone_cls),
        pytest.raises(RuntimeError),
    ):
        await search_job_embeddings(
            query_text="need moving work",
            top_k=50,
            openai_client=openai_client,
            settings=settings,
        )
