from enum import StrEnum

RATE_LIMIT_WINDOW_SECONDS: int = 60
MAX_MESSAGES_PER_WINDOW: int = 5


class MessageType(StrEnum):
    """Classification assigned to an inbound message by the extraction pipeline."""

    JOB_POSTING = "job_posting"
    WORK_GOAL = "work_goal"
    UNKNOWN = "unknown"


class AuditEvent(StrEnum):
    """Lifecycle events recorded in audit_log for an inbound message."""

    RECEIVED = "received"
    DUPLICATE = "duplicate"
    RATE_LIMITED = "rate_limited"
    GPT_CLASSIFIED = "gpt_classified"
    JOB_CREATED = "job_created"
    WORK_GOAL_CREATED = "work_goal_created"
