from datetime import timedelta
from enum import StrEnum

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'

# How long rate_limit rows are kept before the purge cron deletes them.
# Must comfortably exceed the largest configurable rate-limit window.
RATE_LIMIT_PURGE_RETENTION: timedelta = timedelta(hours=1)


class AuditEvent(StrEnum):
    """Lifecycle events recorded in audit_log for an inbound message."""

    RECEIVED = "received"
    DUPLICATE = "duplicate"
    RATE_LIMITED = "rate_limited"
    GPT_CLASSIFIED = "gpt_classified"
    JOB_CREATED = "job_created"
    WORK_GOAL_CREATED = "work_goal_created"
