from enum import StrEnum


class JobStatus(StrEnum):
    """Lifecycle states of a job posting."""

    AVAILABLE = "available"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class PayType(StrEnum):
    """How a job's pay_rate is denominated."""

    HOURLY = "hourly"
    FLAT = "flat"
    UNKNOWN = "unknown"


# Reasons a job's earnings cannot be computed (logged when excluding candidates)
INCOMPUTABLE_UNKNOWN_PAY_TYPE = "unknown_pay_type"
INCOMPUTABLE_NULL_PAY_RATE = "null_pay_rate"
INCOMPUTABLE_NULL_DURATION_HOURLY = "null_duration_hourly"
