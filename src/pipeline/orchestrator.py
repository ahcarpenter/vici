import json

import structlog
from opentelemetry import trace as otel_trace
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.schemas import ExtractionResult
from src.extraction.service import ExtractionService
from src.observability import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_PHONE_HASH
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.audit_repository import AuditLogRepository
from src.sms.constants import AuditEvent
from src.sms.repository import MessageRepository

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()


class PipelineOrchestrator:
    """Application service: classifies a message, dispatches to a handler,
    and owns the unit of work. Handlers stage writes; this commits them."""

    def __init__(
        self,
        extraction_service: ExtractionService,
        audit_repo: AuditLogRepository,
        message_repo: MessageRepository,
        handlers: list[MessageHandler],
    ):
        if not handlers or not handlers[-1].is_terminal:
            raise ValueError(
                "handler chain must end with a terminal (catch-all) handler"
            )
        if any(h.is_terminal for h in handlers[:-1]):
            raise ValueError("only the last handler in the chain may be terminal")
        self._extraction_service = extraction_service
        self._audit_repo = audit_repo
        self._message_repo = message_repo
        self._handlers = handlers

    async def run(
        self,
        session: AsyncSession,
        sms_text: str,
        phone_hash: str,
        message_id: int,
        user_id: int,
        message_sid: str,
        from_number: str,
    ) -> ExtractionResult:
        with tracer.start_as_current_span("pipeline.orchestrate") as span:
            span.set_attribute(OTEL_ATTR_MESSAGE_ID, message_sid)
            span.set_attribute(OTEL_ATTR_PHONE_HASH, phone_hash)

            # 1. Classify via GPT (no session)
            result = await self._extraction_service.process(sms_text, phone_hash)

            # 2. Log classification audit
            await self._audit_repo.write(
                session,
                message_sid,
                AuditEvent.GPT_CLASSIFIED,
                detail=json.dumps({"message_type": result.message_type}),
                message_id=message_id,
            )

            # 3. Dispatch to first matching handler (Chain of Responsibility)
            ctx = PipelineContext(
                session=session,
                result=result,
                sms_text=sms_text,
                phone_hash=phone_hash,
                message_id=message_id,
                user_id=user_id,
                message_sid=message_sid,
                from_number=from_number,
            )

            # The chain always dispatches — the constructor guarantees a
            # terminal catch-all sits at the end.
            dispatched = next(h for h in self._handlers if h.can_handle(result))
            await dispatched.handle(ctx)
            await self._message_repo.record_classification(
                session,
                message_id,
                dispatched.message_type,
                raw_gpt_response=result.model_dump_json(),
            )

            # 4. Single unit of work, then deferred external side effects
            await session.commit()

            for action in ctx.post_commit_actions:
                try:
                    await action()
                except Exception as exc:
                    log.error(
                        "pipeline.post_commit_action_failed",
                        message_sid=message_sid,
                        error=str(exc),
                    )

            return result
