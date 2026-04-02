from abc import ABC, abstractmethod

from src.extraction.schemas import ExtractionResult
from src.pipeline.context import PipelineContext


class MessageHandler(ABC):
    """Chain of Responsibility handler for classified messages."""

    @abstractmethod
    def can_handle(self, result: ExtractionResult) -> bool:
        """Return True if this handler should process the result."""
        ...

    @abstractmethod
    async def handle(self, ctx: PipelineContext) -> None:
        """Execute handler logic. Caller owns the transaction."""
        ...
