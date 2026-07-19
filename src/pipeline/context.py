from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.schemas import ExtractionResult

PostCommitAction = Callable[[], Awaitable[None]]


@dataclass
class PipelineContext:
    """Values passed to message handlers, plus their deferred side effects.

    Handlers must not commit; they stage DB writes on `session` (flush-only)
    and register external side effects (Twilio sends, Pinecone upserts) via
    `run_after_commit`. The orchestrator commits, then runs the actions.
    """

    session: AsyncSession
    result: ExtractionResult
    sms_text: str
    phone_hash: str
    message_id: int
    user_id: int
    message_sid: str
    from_number: str
    post_commit_actions: list[PostCommitAction] = field(default_factory=list)

    def run_after_commit(self, action: PostCommitAction) -> None:
        """Register a side effect to run only after the transaction commits."""
        self.post_commit_actions.append(action)
