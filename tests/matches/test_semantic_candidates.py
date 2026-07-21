"""
Tests for the Pinecone semantic-search read path:
JobRepository.find_candidates_by_ids and MatchService hybrid retrieval.

Covers: MATCH-01 (eligibility reuse), semantic restriction + fallbacks.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import structlog.testing

from src.jobs.repository import JobRepository
from src.matches.repository import MatchRepository
from src.matches.service import MatchService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(searcher=None) -> MatchService:
    return MatchService(
        job_repo=JobRepository(),
        match_repo=MatchRepository(),
        embedding_searcher=searcher,
    )


def _ranked(job_ids):
    """Build a searcher stub returning the given ids best-first."""

    async def _searcher(*, query_text: str, top_k: int):
        return [(job_id, 1.0 - i * 0.01) for i, job_id in enumerate(job_ids)]

    return _searcher


# ---------------------------------------------------------------------------
# find_candidates_by_ids -- eligibility + ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_by_ids_preserves_caller_order(async_session, make_job):
    j1 = await make_job(pay_rate=100.0, pay_type="flat", status="available")
    j2 = await make_job(pay_rate=100.0, pay_type="flat", status="available")
    j3 = await make_job(pay_rate=100.0, pay_type="flat", status="available")

    repo = JobRepository()
    jobs = await repo.find_candidates_by_ids(async_session, [j3.id, j1.id, j2.id])

    assert [j.id for j in jobs] == [j3.id, j1.id, j2.id]


@pytest.mark.asyncio
async def test_by_ids_drops_ineligible_and_unknown_ids(async_session, make_job):
    deadline = datetime.now(UTC) + timedelta(days=2)
    eligible = await make_job(pay_rate=100.0, pay_type="flat", status="available")
    accepted = await make_job(pay_rate=100.0, pay_type="flat", status="accepted")
    late = await make_job(
        pay_rate=100.0,
        pay_type="flat",
        status="available",
        ideal_datetime=deadline + timedelta(days=1),
    )

    repo = JobRepository()
    jobs = await repo.find_candidates_by_ids(
        async_session,
        [eligible.id, accepted.id, late.id, 999999],
        deadline=deadline,
    )

    assert [j.id for j in jobs] == [eligible.id]


@pytest.mark.asyncio
async def test_by_ids_empty_input_returns_empty(async_session):
    repo = JobRepository()
    assert await repo.find_candidates_by_ids(async_session, []) == []


# ---------------------------------------------------------------------------
# MatchService hybrid retrieval -- restriction + fallbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_results_restrict_candidate_pool(
    async_session, make_job, make_work_goal
):
    """Only searcher-returned jobs compete when results meet the floor."""
    jobs = [
        await make_job(pay_rate=100.0, pay_type="flat", status="available")
        for _ in range(7)
    ]
    semantic_ids = [j.id for j in jobs[:5]]
    goal = await make_work_goal(target_earnings=1000.0)

    svc = _make_service(searcher=_ranked(semantic_ids))
    result = await svc.match(async_session, goal, query_text="need warehouse work")

    selected_ids = {c.job.id for c in result.jobs}
    assert selected_ids == set(semantic_ids)
    assert jobs[5].id not in selected_ids
    assert jobs[6].id not in selected_ids


@pytest.mark.asyncio
async def test_searcher_error_falls_back_to_full_scan(
    async_session, make_job, make_work_goal
):
    """A searcher failure never breaks matching — full scan takes over."""
    jobs = [
        await make_job(pay_rate=100.0, pay_type="flat", status="available")
        for _ in range(7)
    ]
    goal = await make_work_goal(target_earnings=1000.0)

    async def _broken(*, query_text: str, top_k: int):
        raise RuntimeError("Pinecone down")

    svc = _make_service(searcher=_broken)
    with structlog.testing.capture_logs() as cap:
        result = await svc.match(async_session, goal, query_text="need work")

    assert any(e["event"] == "match.semantic_search_failed" for e in cap)
    selected_ids = {c.job.id for c in result.jobs}
    assert selected_ids == {j.id for j in jobs}


@pytest.mark.asyncio
async def test_empty_semantic_results_fall_back_to_full_scan(
    async_session, make_job, make_work_goal
):
    jobs = [
        await make_job(pay_rate=100.0, pay_type="flat", status="available")
        for _ in range(3)
    ]
    goal = await make_work_goal(target_earnings=1000.0)

    svc = _make_service(searcher=_ranked([]))
    result = await svc.match(async_session, goal, query_text="need work")

    assert {c.job.id for c in result.jobs} == {j.id for j in jobs}


@pytest.mark.asyncio
async def test_thin_semantic_results_fall_back_to_full_scan(
    async_session, make_job, make_work_goal
):
    """Fewer surviving semantic hits than the floor → full scan (logged)."""
    jobs = [
        await make_job(pay_rate=100.0, pay_type="flat", status="available")
        for _ in range(6)
    ]
    goal = await make_work_goal(target_earnings=1000.0)

    svc = _make_service(searcher=_ranked([jobs[0].id, jobs[1].id]))
    with structlog.testing.capture_logs() as cap:
        result = await svc.match(async_session, goal, query_text="need work")

    assert any(
        e["event"] == "match.semantic_fallback" and e["reason"] == "thin_results"
        for e in cap
    )
    assert {c.job.id for c in result.jobs} == {j.id for j in jobs}


@pytest.mark.asyncio
async def test_stale_semantic_ids_filtered_without_fallback(
    async_session, make_job, make_work_goal
):
    """Ineligible index hits drop out; enough survivors avoid the fallback."""
    deadline = datetime.now(UTC) + timedelta(days=2)
    eligible = [
        await make_job(pay_rate=100.0, pay_type="flat", status="available")
        for _ in range(6)
    ]
    accepted = await make_job(pay_rate=100.0, pay_type="flat", status="accepted")
    late = await make_job(
        pay_rate=100.0,
        pay_type="flat",
        status="available",
        ideal_datetime=deadline + timedelta(days=1),
    )
    goal = await make_work_goal(target_earnings=1000.0, target_deadline=deadline)

    semantic_ids = [j.id for j in eligible[:5]] + [accepted.id, late.id]
    svc = _make_service(searcher=_ranked(semantic_ids))
    result = await svc.match(async_session, goal, query_text="need work")

    selected_ids = {c.job.id for c in result.jobs}
    assert selected_ids == {j.id for j in eligible[:5]}
    assert accepted.id not in selected_ids
    assert late.id not in selected_ids
    # No fallback: the 6th eligible job was never a candidate.
    assert eligible[5].id not in selected_ids


@pytest.mark.asyncio
async def test_none_searcher_behaves_as_full_scan(
    async_session, make_job, make_work_goal
):
    jobs = [
        await make_job(pay_rate=100.0, pay_type="flat", status="available")
        for _ in range(3)
    ]
    goal = await make_work_goal(target_earnings=1000.0)

    svc = _make_service(searcher=None)
    result = await svc.match(async_session, goal, query_text="need work")

    assert {c.job.id for c in result.jobs} == {j.id for j in jobs}


@pytest.mark.asyncio
async def test_searcher_timeout_falls_back(
    async_session, make_job, make_work_goal, monkeypatch
):
    jobs = [
        await make_job(pay_rate=100.0, pay_type="flat", status="available")
        for _ in range(3)
    ]
    goal = await make_work_goal(target_earnings=1000.0)
    monkeypatch.setattr("src.matches.service.SEMANTIC_SEARCH_TIMEOUT_SECONDS", 0.01)

    async def _slow(*, query_text: str, top_k: int):
        await asyncio.sleep(1.0)
        return []

    svc = _make_service(searcher=_slow)
    with structlog.testing.capture_logs() as cap:
        result = await svc.match(async_session, goal, query_text="need work")

    assert any(e["event"] == "match.semantic_search_failed" for e in cap)
    assert {c.job.id for c in result.jobs} == {j.id for j in jobs}
