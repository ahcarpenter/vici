import json

import structlog
from opentelemetry import trace as otel_trace
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.schemas import ExtractionResult
from src.extraction.service import ExtractionService
from src.pipeline.constants import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_PHONE_HASH
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.audit_repository import AuditLogRepository

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()


class PipelineOrchestrator:
    def __init__(
        self,
        extraction_service: ExtractionService,
        audit_repo: AuditLogRepository,
        handlers: list[MessageHandler],
    ):
        self._extraction_service = extraction_service
        self._audit_repo = audit_repo
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
                "gpt_classified",
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

            for handler in self._handlers:
                if handler.can_handle(result):
                    await handler.handle(ctx)
                    break

            return result
