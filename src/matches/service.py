from datetime import UTC, datetime

import structlog
from opentelemetry import trace as otel_trace
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.jobs.models import Job
from src.jobs.repository import JobRepository
from src.matches.repository import MatchRepository
from src.matches.schemas import JobCandidate, MatchResult
from src.sms.models import Message
from src.users.models import User
from src.work_goals.models import WorkGoal

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()

SENTINEL_DATETIME = datetime.max.replace(
    tzinfo=UTC
)  # NULL ideal_datetime sorts last (D-12)


class MatchService:
    def __init__(self, job_repo: JobRepository, match_repo: MatchRepository):
        self._job_repo = job_repo
        self._match_repo = match_repo

    async def match(self, session: AsyncSession, work_goal: WorkGoal) -> MatchResult:
        with tracer.start_as_current_span("pipeline.match_jobs") as span:
            span.set_attribute("work_goal_id", str(work_goal.id))

            raw_jobs = await self._job_repo.find_candidates_for_goal(session)

            if not raw_jobs:
                return MatchResult(
                    jobs=[], work_goal=work_goal, total_earnings=0, is_partial=True
                )

            candidates = await self._build_candidates(session, raw_jobs)

            selected = self._dp_select(candidates, work_goal.target_earnings)
            sorted_selected = self._sort_results(selected)

            total = sum(c.earnings for c in sorted_selected)
            is_partial = total < work_goal.target_earnings

            if sorted_selected:
                job_ids = [c.job.id for c in sorted_selected]
                await self._match_repo.persist_matches(session, job_ids, work_goal.id)

            return MatchResult(
                jobs=sorted_selected,
                work_goal=work_goal,
                total_earnings=total,
                is_partial=is_partial,
            )

    async def _build_candidates(
        self, session: AsyncSession, jobs: list[Job]
    ) -> list[JobCandidate]:
        """
        For each job, compute earnings and fetch poster phone via:
        job.message_id -> message.user_id -> user.phone_e164

        Load all relevant users in a single query to avoid N+1.
        """
        message_ids = [j.message_id for j in jobs]

        msg_result = await session.execute(
            select(Message).where(Message.id.in_(message_ids))
        )
        messages = {m.id: m for m in msg_result.scalars().all()}

        user_ids = list({m.user_id for m in messages.values()})
        user_result = await session.execute(select(User).where(User.id.in_(user_ids)))
        users = {u.id: u for u in user_result.scalars().all()}

        candidates = []
        for job in jobs:
            msg = messages.get(job.message_id)
            user = users.get(msg.user_id) if msg else None
            poster_phone = user.phone_e164 if user else None

            if job.pay_type == "hourly":
                earnings = int(round(job.pay_rate * job.estimated_duration_hours))
                duration = job.estimated_duration_hours
            else:  # flat
                earnings = job.pay_rate
                duration = job.estimated_duration_hours or 0.0

            candidates.append(
                JobCandidate(
                    job=job,
                    earnings=earnings,
                    duration=duration,
                    poster_phone=poster_phone,
                )
            )
        return candidates

    def _dp_select(
        self, candidates: list[JobCandidate], target: int
    ) -> list[JobCandidate]:
        """
        0/1 knapsack DP.
        Primary objective: maximize total earnings toward target.
        Secondary objective: minimize total duration among goal-meeting subsets.

        Earnings are integer cents throughout — no quantization step needed.

        Returns list of selected JobCandidates (unordered -- caller sorts).
        """
        if not candidates:
            return []

        capacity = sum(c.earnings for c in candidates)

        if capacity == 0:
            return []

        n = len(candidates)
        NEG_INF = float("-inf")
        dp = [(NEG_INF, 0.0)] * (capacity + 1)
        dp[0] = (0, 0.0)
        keep = [[False] * (capacity + 1) for _ in range(n)]

        for i, cand in enumerate(candidates):
            e = cand.earnings
            dur = cand.duration
            for w in range(capacity, e - 1, -1):
                prev_e, prev_neg_d = dp[w - e]
                if prev_e == NEG_INF:
                    continue
                candidate_val = (prev_e + e, prev_neg_d - dur)
                if candidate_val > dp[w]:
                    dp[w] = candidate_val
                    keep[i][w] = True

        best_w = max(
            (w for w in range(capacity + 1) if dp[w][0] != NEG_INF),
            key=lambda w: dp[w],
            default=0,
        )

        selected = []
        w = best_w
        for i in range(n - 1, -1, -1):
            if keep[i][w]:
                selected.append(candidates[i])
                w -= candidates[i].earnings
                if w < 0:
                    break
        return selected

    def _sort_results(self, candidates: list[JobCandidate]) -> list[JobCandidate]:
        """
        Sort by D-11/D-12: soonest ideal_datetime first, then shortest duration.
        NULL ideal_datetime sorts last (uses SENTINEL_DATETIME = datetime.max UTC).
        Normalize naive datetimes to UTC before comparison to avoid TypeError.
        """

        def sort_key(c: JobCandidate):
            dt = c.job.ideal_datetime
            if dt is None:
                dt = SENTINEL_DATETIME
            elif dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return (dt, c.duration)

        return sorted(candidates, key=sort_key)
