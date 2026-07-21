import json

import structlog
from opentelemetry import trace as otel_trace
from twilio.rest import Client as TwilioClient

from src.extraction.constants import MessageType
from src.extraction.schemas import ExtractionResult
from src.matches.formatter import format_match_sms
from src.matches.service import MatchService
from src.money import dollars_to_cents
from src.observability import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_WORK_GOAL_USER_ID
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.audit_repository import AuditLogRepository
from src.sms.constants import AuditEvent
from src.sms.outbound import send_sms
from src.sms.service import hash_phone
from src.work_goals.repository import WorkGoalRepository
from src.work_goals.schemas import WorkGoalCreate

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()


class WorkGoalHandler(MessageHandler):
    message_type = MessageType.WORK_GOAL

    def __init__(
        self,
        work_goal_repo: WorkGoalRepository,
        audit_repo: AuditLogRepository,
        match_service: MatchService,
        twilio_client: TwilioClient,
        from_number: str,
    ):
        self._work_goal_repo = work_goal_repo
        self._audit_repo = audit_repo
        self._match_service = match_service
        self._twilio_client = twilio_client
        self._from_number = from_number

    def can_handle(self, result: ExtractionResult) -> bool:
        return (
            result.message_type == MessageType.WORK_GOAL
            and result.work_goal is not None
        )

    async def handle(self, ctx: PipelineContext) -> None:
        with tracer.start_as_current_span("pipeline.handle_work_goal") as span:
            span.set_attribute(OTEL_ATTR_MESSAGE_ID, ctx.message_sid)
            span.set_attribute(OTEL_ATTR_WORK_GOAL_USER_ID, str(ctx.user_id))
            return await self._do_handle(ctx)

    async def _do_handle(self, ctx: PipelineContext) -> None:
        extracted = ctx.result.work_goal
        assert extracted is not None  # guaranteed by can_handle
        wg_create = WorkGoalCreate(
            message_id=ctx.message_id,
            target_earnings=dollars_to_cents(extracted.target_earnings),
            target_timeframe=extracted.target_timeframe,
        )
        wg = await self._work_goal_repo.create(ctx.session, wg_create)

        await self._audit_repo.write(
            ctx.session,
            ctx.message_sid,
            AuditEvent.WORK_GOAL_CREATED,
            detail=json.dumps({"work_goal_id": wg.id}),
            message_id=ctx.message_id,
        )

        # Match inside the same unit of work (job selection + match rows),
        # then reply after the orchestrator commits.
        match_result = await self._match_service.match(ctx.session, wg)
        reply_body = format_match_sms(match_result)

        message_sid = ctx.message_sid
        to_number = ctx.from_number

        async def send_match_reply() -> None:
            try:
                await send_sms(
                    self._twilio_client,
                    to=to_number,
                    from_number=self._from_number,
                    body=reply_body,
                )
            except Exception as exc:
                log.error(
                    "match_reply_failed",
                    message_sid=message_sid,
                    error=str(exc),
                )
                return
            log.info(
                "match_reply_sent",
                message_sid=message_sid,
                to_hash=hash_phone(to_number),
            )

        ctx.run_after_commit(send_match_reply)
