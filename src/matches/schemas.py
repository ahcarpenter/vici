from dataclasses import dataclass
from typing import Optional

from src.jobs.models import Job
from src.work_goals.models import WorkGoal


@dataclass
class JobCandidate:
    """A job eligible for DP selection, with pre-computed earnings and poster phone."""

    job: Job
    earnings: float  # pay_rate * duration (hourly) or pay_rate (flat)
    duration: float  # estimated_duration_hours; 0.0 for flat jobs with no duration
    poster_phone: Optional[str]  # User.phone_e164, may be None for legacy users


@dataclass
class MatchResult:
    """Output of MatchService.match(). jobs are sorted per D-11/D-12."""

    jobs: list[JobCandidate]
    work_goal: WorkGoal
    total_earnings: float
    is_partial: bool  # True when total_earnings < work_goal.target_earnings

    @property
    def is_empty(self) -> bool:
        return len(self.jobs) == 0
