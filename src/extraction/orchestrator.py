import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.schemas import ExtractionResult
from src.extraction.service import ExtractionService
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.audit_repository import AuditLogRepository

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
