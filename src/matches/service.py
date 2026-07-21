import asyncio
from datetime import UTC, datetime
from typing import Protocol

import structlog
from opentelemetry import trace as otel_trace
from sqlalchemy.ext.asyncio import AsyncSession

from src.jobs.models import Job
from src.jobs.repository import JobRepository
from src.matches.constants import (
    SEMANTIC_MIN_CANDIDATES,
    SEMANTIC_SEARCH_TIMEOUT_SECONDS,
    SEMANTIC_TOP_K,
)
from src.matches.repository import MatchRepository
from src.matches.schemas import JobCandidate, MatchResult
from src.observability import OTEL_ATTR_DB_OPERATION, OTEL_ATTR_DB_SYSTEM
from src.work_goals.models import WorkGoal

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()

SENTINEL_DATETIME = datetime.max.replace(
    tzinfo=UTC
)  # NULL ideal_datetime sorts last (D-12)


class JobEmbeddingSearcher(Protocol):
    """Port for semantic retrieval from the job vector index.

    MatchService owns this contract; composition (main.py) binds the OpenAI
    client and settings so the service never touches either.
    """

    async def __call__(
        self, *, query_text: str, top_k: int
    ) -> list[tuple[int, float]]: ...


class MatchService:
    def __init__(
        self,
        job_repo: JobRepository,
        match_repo: MatchRepository,
        embedding_searcher: JobEmbeddingSearcher | None = None,
    ):
        self._job_repo = job_repo
        self._match_repo = match_repo
        self._embedding_searcher = embedding_searcher

    async def match(
        self,
        session: AsyncSession,
        work_goal: WorkGoal,
        query_text: str | None = None,
    ) -> MatchResult:
        with tracer.start_as_current_span("pipeline.match_jobs") as span:
            span.set_attribute("work_goal_id", str(work_goal.id))
            if work_goal.target_deadline is not None:
                span.set_attribute(
                    "work_goal.deadline", work_goal.target_deadline.isoformat()
                )

            raw_jobs = await self._retrieve_candidates(session, work_goal, query_text)
            span.set_attribute("match.candidate_count", len(raw_jobs))

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
                assert work_goal.id is not None  # persisted before matching
                job_ids = [c.job.id for c in sorted_selected if c.job.id is not None]
                await self._match_repo.persist_matches(session, job_ids, work_goal.id)

            return MatchResult(
                jobs=sorted_selected,
                work_goal=work_goal,
                total_earnings=total,
                is_partial=is_partial,
            )

    async def _retrieve_candidates(
        self, session: AsyncSession, work_goal: WorkGoal, query_text: str | None
    ) -> list[Job]:
        """
        Semantic top-K when possible; full scan otherwise.

        Pinecone ranks relevance; Postgres remains the eligibility authority
        (status/pay/deadline — index metadata has no status and is never
        pruned). Thin or failed semantic results fall back to the full scan,
        which is a superset of the semantic hits — no merge needed.
        Degrade-don't-crash: a Pinecone/OpenAI outage must never break
        matching.
        """
        deadline = work_goal.target_deadline
        if self._embedding_searcher is not None and query_text:
            ranked = await self._semantic_ids(query_text)
            if ranked:
                ids = [job_id for job_id, _score in ranked]
                jobs = await self._job_repo.find_candidates_by_ids(
                    session, ids, deadline=deadline
                )
                if len(jobs) >= SEMANTIC_MIN_CANDIDATES:
                    return jobs
                log.info(
                    "match.semantic_fallback",
                    reason="thin_results",
                    semantic_count=len(jobs),
                )
        return await self._job_repo.find_candidates_for_goal(session, deadline=deadline)

    async def _semantic_ids(self, query_text: str) -> list[tuple[int, float]]:
        """Query the searcher port; [] on any failure or timeout (logged)."""
        assert self._embedding_searcher is not None  # guarded by caller
        try:
            with tracer.start_as_current_span("pinecone.query") as span:
                span.set_attribute(OTEL_ATTR_DB_SYSTEM, "pinecone")
                span.set_attribute(OTEL_ATTR_DB_OPERATION, "query")
                ranked = await asyncio.wait_for(
                    self._embedding_searcher(
                        query_text=query_text, top_k=SEMANTIC_TOP_K
                    ),
                    timeout=SEMANTIC_SEARCH_TIMEOUT_SECONDS,
                )
                span.set_attribute("db.vector.results", len(ranked))
                return ranked
        except Exception as exc:
            log.warning("match.semantic_search_failed", error=str(exc))
            return []

    async def _build_candidates(
        self, session: AsyncSession, jobs: list[Job]
    ) -> list[JobCandidate]:
        """
        For each job, compute earnings from its PayTerms and attach the
        poster's phone (single batched traversal via JobRepository).
        """
        posters = await self._job_repo.find_posters(session, jobs)

        candidates = []
        for job in jobs:
            assert job.id is not None  # rows loaded from the DB
            terms = job.pay_terms
            earnings = terms.earnings()
            if earnings is None:
                # find_candidates_for_goal already excludes these; stay defensive.
                log.warning(
                    "match.job_excluded",
                    job_id=job.id,
                    reason=terms.incomputable_reason(),
                )
                continue

            poster = posters.get(job.id)
            candidates.append(
                JobCandidate(
                    job=job,
                    earnings=earnings,
                    duration=terms.duration_hours or 0.0,
                    poster_phone=poster.phone_e164 if poster else None,
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

        # Bound DP memory at target + max single-job earnings. No optimal subset
        # sum ever exceeds target by more than the largest single job (any larger
        # overshoot is dominated by dropping jobs). Raw sum(earnings) unbounded
        # caused O(GB) allocations at realistic job volumes.
        total_earnings = sum(c.earnings for c in candidates)
        max_earning = max(c.earnings for c in candidates)
        capacity = min(total_earnings, target + max_earning)

        if capacity == 0:
            return []

        n = len(candidates)
        NEG_INF = float("-inf")
        dp = [(NEG_INF, 0.0)] * (capacity + 1)
        dp[0] = (0, 0.0)
        # bytearray rows, not list-of-bool: the reconstruction table is
        # n × capacity entries — at realistic targets (cents!) pointer-sized
        # bools cost hundreds of MB; bytes keep it ~1/8 of that.
        keep = [bytearray(capacity + 1) for _ in range(n)]

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
                    keep[i][w] = 1

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
