from abc import ABC, abstractmethod
from typing import ClassVar

from src.extraction.schemas import ExtractionResult
from src.pipeline.context import PipelineContext
from src.sms.constants import MessageType


class MessageHandler(ABC):
    """Chain of Responsibility handler for classified messages."""

    # Classification this handler records on the message when it handles it.
    message_type: ClassVar[MessageType]

    @abstractmethod
    def can_handle(self, result: ExtractionResult) -> bool:
        """Return True if this handler should process the result."""
        ...

    @abstractmethod
    async def handle(self, ctx: PipelineContext) -> None:
        """Execute handler logic. Flush-only — the orchestrator owns the
        transaction. External side effects go through ctx.run_after_commit."""
        ...
