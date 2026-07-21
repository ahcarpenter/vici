from abc import ABC, abstractmethod
from typing import ClassVar

from src.extraction.constants import MessageType
from src.extraction.schemas import ExtractionResult
from src.pipeline.context import PipelineContext


class MessageHandler(ABC):
    """Chain of Responsibility handler for classified messages."""

    # Classification this handler records on the message when it handles it.
    message_type: ClassVar[MessageType]

    # A terminal handler accepts every result. The orchestrator requires the
    # chain to end with exactly one — dispatch can then never fall through.
    is_terminal: ClassVar[bool] = False

    @abstractmethod
    def can_handle(self, result: ExtractionResult) -> bool:
        """Return True if this handler should process the result."""
        ...

    @abstractmethod
    async def handle(self, ctx: PipelineContext) -> None:
        """Execute handler logic. Flush-only — the orchestrator owns the
        transaction. External side effects go through ctx.run_after_commit."""
        ...
