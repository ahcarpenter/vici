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
