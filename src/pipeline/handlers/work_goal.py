import json

from opentelemetry import trace as otel_trace

from src.extraction.schemas import ExtractionResult
from src.money import dollars_to_cents
from src.pipeline.constants import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_WORK_GOAL_USER_ID
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.audit_repository import AuditLogRepository
from src.sms.constants import AuditEvent, MessageType
from src.work_goals.repository import WorkGoalRepository
from src.work_goals.schemas import WorkGoalCreate

tracer = otel_trace.get_tracer(__name__)


class WorkGoalHandler(MessageHandler):
    message_type = MessageType.WORK_GOAL

    def __init__(
        self,
        work_goal_repo: WorkGoalRepository,
        audit_repo: AuditLogRepository,
    ):
        self._work_goal_repo = work_goal_repo
        self._audit_repo = audit_repo

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
        result = ctx.result
        wg_create = WorkGoalCreate(
            message_id=ctx.message_id,
            target_earnings=dollars_to_cents(result.work_goal.target_earnings),
            target_timeframe=result.work_goal.target_timeframe,
        )
        wg = await self._work_goal_repo.create(ctx.session, wg_create)

        await self._audit_repo.write(
            ctx.session,
            ctx.message_sid,
            AuditEvent.WORK_GOAL_CREATED,
            detail=json.dumps({"work_goal_id": wg.id}),
            message_id=ctx.message_id,
        )
