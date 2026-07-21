from openai import AsyncOpenAI
from pinecone import PineconeAsyncio, Vector

from src.config import Settings
from src.extraction.constants import EMBEDDING_MODEL


async def write_job_embedding(
    job_id: int,
    description: str,
    phone_hash: str,
    openai_client: AsyncOpenAI,
    settings: Settings,
) -> None:
    """Generate embedding via OpenAI and upsert to Pinecone. Raises on any failure."""
    emb_resp = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=description,
    )
    vector = emb_resp.data[0].embedding  # list[float], EMBEDDING_DIMS elements

    async with (
        PineconeAsyncio(api_key=settings.pinecone.api_key) as pc,
        pc.IndexAsyncio(host=settings.pinecone.index_host) as idx,
    ):
        await idx.upsert(
            vectors=[
                Vector(
                    id=str(job_id),
                    values=vector,
                    metadata={"phone_hash": phone_hash},
                )
            ]
        )


async def search_job_embeddings(
    query_text: str,
    top_k: int,
    openai_client: AsyncOpenAI,
    settings: Settings,
) -> list[tuple[int, float]]:
    """Embed query text via OpenAI and query Pinecone for nearest job vectors.

    Returns [(job_id, score)] ranked best-first. Raises on any failure —
    the caller (MatchService) owns degradation.
    """
    emb_resp = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query_text,
    )
    vector = emb_resp.data[0].embedding

    async with (
        PineconeAsyncio(api_key=settings.pinecone.api_key) as pc,
        pc.IndexAsyncio(host=settings.pinecone.index_host) as idx,
    ):
        resp = await idx.query(
            vector=vector,
            top_k=top_k,
            include_values=False,
            include_metadata=False,
        )

    ranked: list[tuple[int, float]] = []
    for match in resp.matches:
        try:
            ranked.append((int(match.id), float(match.score)))
        except (TypeError, ValueError):
            continue  # vector id not one of ours — skip defensively
    return ranked
