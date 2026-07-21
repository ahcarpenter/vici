from enum import StrEnum

GPT_MODEL = "gpt-5.3-chat-latest"
UNKNOWN_REPLY_TEXT = (
    "Hi from Vici! We didn't understand your message. "
    "Text us a job (include pay, location, time) or your earnings goal "
    "(e.g., 'I need $200 today')."
)
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536

# GPT call retry / timeout constants
GPT_CALL_TIMEOUT_SECONDS: float = 30.0
GPT_RETRY_MAX_ATTEMPTS: int = 4
GPT_RETRY_WAIT_MULTIPLIER: int = 1
GPT_RETRY_WAIT_MIN_SECONDS: int = 1
GPT_RETRY_WAIT_MAX_SECONDS: int = 60
OPENAI_MAX_RETRIES: int = 0

# Pinecone sync queue
PINECONE_SYNC_BATCH_SIZE: int = 50


class MessageType(StrEnum):
    """Classification assigned to an inbound message by the extraction pipeline.

    Single source of truth for the classification vocabulary — the extraction
    schema, the message record, and the pipeline handlers all reference this.
    """

    JOB_POSTING = "job_posting"
    WORK_GOAL = "work_goal"
    UNKNOWN = "unknown"


class SyncStatus(StrEnum):
    """States of a pinecone_sync_queue entry (outbox for the search index)."""

    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
