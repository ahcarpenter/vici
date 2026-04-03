import json

from opentelemetry import trace as otel_trace
from sqlalchemy import text as sa_text

from src.extraction.schemas import ExtractionResult
from src.pipeline.constants import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_WORK_REQUEST_USER_ID
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.audit_repository import AuditLogRepository
from src.work_requests.repository import WorkRequestRepository
from src.work_requests.schemas import WorkRequestCreate

tracer = otel_trace.get_tracer(__name__)


class WorkerGoalHandler(MessageHandler):
    def __init__(
        self,
        work_request_repo: WorkRequestRepository,
        audit_repo: AuditLogRepository,
    ):
        self._work_request_repo = work_request_repo
        self._audit_repo = audit_repo

    def can_handle(self, result: ExtractionResult) -> bool:
        return result.message_type == "worker_goal" and result.worker is not None

    async def handle(self, ctx: PipelineContext) -> None:
        with tracer.start_as_current_span("pipeline.handle_worker_goal") as span:
            span.set_attribute(OTEL_ATTR_MESSAGE_ID, ctx.message_sid)
            span.set_attribute(OTEL_ATTR_WORK_REQUEST_USER_ID, str(ctx.user_id))
            return await self._do_handle(ctx)

    async def _do_handle(self, ctx: PipelineContext) -> None:
        result = ctx.result
        wr_create = WorkRequestCreate(
            user_id=ctx.user_id,
            message_id=ctx.message_id,
            target_earnings=result.worker.target_earnings,
            target_timeframe=result.worker.target_timeframe,
            raw_sms=ctx.sms_text,
        )
        wr = await self._work_request_repo.create(ctx.session, wr_create)

        await ctx.session.execute(
            sa_text("UPDATE message SET message_type = 'worker_goal' WHERE id = :mid"),
            {"mid": ctx.message_id},
        )
        await self._audit_repo.write(
            ctx.session,
            ctx.message_sid,
            "work_request_created",
            detail=json.dumps({"work_request_id": wr.id}),
            message_id=ctx.message_id,
        )

        await ctx.session.commit()
