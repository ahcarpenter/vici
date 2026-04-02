from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.schemas import ExtractionResult


@dataclass
class PipelineContext:
    """Immutable bag of values passed to message handlers."""

    session: AsyncSession
    result: ExtractionResult
    sms_text: str
    phone_hash: str
    message_id: int
    user_id: int
    message_sid: str
    from_number: str
