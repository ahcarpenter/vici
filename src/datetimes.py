"""Datetime coercion for LLM-extracted values.

Cross-cutting boundary utility (like ``src/money.py``): the GPT contract asks
for ISO-8601 but cannot guarantee it; junk degrades to None, naive becomes UTC.

NOTE: naive values are *labeled* UTC, not converted — this matches how job
ideal_datetime is stored (poster-local wall time labeled UTC), so wall-clock
comparisons between work-goal deadlines and job datetimes stay consistent.
Do not add real zoneinfo resolution on one side only.
"""

from datetime import UTC, datetime

import structlog


def coerce_llm_datetime(value: object, *, log_event: str) -> datetime | None:
    """Parse an LLM-supplied ISO-8601 value; junk -> None + warning; naive -> UTC.

    ``log_event`` is the structlog event name emitted when the value cannot be
    parsed (callers keep their historical event names).
    """
    if value is None or isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            structlog.get_logger().warning(log_event, raw_value=str(value))
            return None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
