"""
Tests for MatchService, JobRepository.find_candidates_for_goal,
MatchRepository.persist_matches, and format_match_sms.

Covers: MATCH-01, MATCH-02, MATCH-03
"""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
import structlog.testing

from src.jobs.repository import JobRepository
from src.matches.formatter import format_match_sms
from src.matches.repository import MatchRepository
from src.matches.schemas import JobCandidate, MatchResult
from src.matches.service import MatchService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> MatchService:
    return MatchService(job_repo=JobRepository(), match_repo=MatchRepository())


# ---------------------------------------------------------------------------
# find_candidates_for_goal -- exclusion rules (MATCH-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_null_pay_rate_excluded(async_session, make_job, make_work_goal):
    job = await make_job(
        pay_rate=None, pay_type="hourly", estimated_duration_hours=2.0, status="available"
    )
    await make_work_goal(target_earnings=50.0)

    with structlog.testing.capture_logs() as cap:
        repo = JobRepository()
        candidates = await repo.find_candidates_for_goal(async_session)

    job_ids = [j.id for j in candidates]
    assert job.id not in job_ids
    assert any(
        e.get("job_id") == job.id and e.get("reason") == "null_pay_rate" for e in cap
    )


@pytest.mark.asyncio
async def test_null_duration_hourly_excluded(async_session, make_job, make_work_goal):
    job = await make_job(
        pay_rate=25.0, pay_type="hourly", estimated_duration_hours=None, status="available"
    )
    await make_work_goal(target_earnings=50.0)

    with structlog.testing.capture_logs() as cap:
        repo = JobRepository()
        candidates = await repo.find_candidates_for_goal(async_session)

    job_ids = [j.id for j in candidates]
    assert job.id not in job_ids
    assert any(
        e.get("job_id") == job.id and e.get("reason") == "null_duration_hourly"
        for e in cap
    )


@pytest.mark.asyncio
async def test_null_duration_flat_allowed(async_session, make_job):
    """Flat-rate jobs with NULL estimated_duration_hours are valid candidates (D-02)."""
    job = await make_job(
        pay_rate=100.0, pay_type="flat", estimated_duration_hours=None, status="available"
    )
    repo = JobRepository()
    candidates = await repo.find_candidates_for_goal(async_session)
    assert job.id in [j.id for j in candidates]


@pytest.mark.asyncio
async def test_unknown_pay_type_excluded(async_session, make_job):
    job = await make_job(
        pay_rate=25.0, pay_type="unknown", estimated_duration_hours=2.0, status="available"
    )
    repo = JobRepository()
    candidates = await repo.find_candidates_for_goal(async_session)
    assert job.id not in [j.id for j in candidates]


@pytest.mark.asyncio
async def test_status_filter(async_session, make_job):
    """Jobs with status != 'available' are excluded (D-06a)."""
    accepted_job = await make_job(
        pay_rate=25.0, pay_type="hourly", estimated_duration_hours=2.0, status="accepted"
    )
    repo = JobRepository()
    candidates = await repo.find_candidates_for_goal(async_session)
    assert accepted_job.id not in [j.id for j in candidates]


# ---------------------------------------------------------------------------
# MatchService.match -- DP algorithm (MATCH-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dp_meets_goal(async_session, make_job, make_work_goal):
    """Happy path: seeded hourly jobs, goal is met."""
    job = await make_job(
        pay_rate=25.0, pay_type="hourly", estimated_duration_hours=2.0, status="available"
    )
    goal = await make_work_goal(target_earnings=40.0)

    svc = _make_service()
    result = await svc.match(async_session, goal)

    assert not result.is_partial
    assert result.total_earnings >= 40.0
    assert any(c.job.id == job.id for c in result.jobs)


@pytest.mark.asyncio
async def test_dp_meets_goal_flat(async_session, make_job, make_work_goal):
    """Flat-rate earnings = pay_rate only, not pay_rate * duration (D-02)."""
    job = await make_job(
        pay_rate=200.0, pay_type="flat", estimated_duration_hours=None, status="available"
    )
    goal = await make_work_goal(target_earnings=150.0)

    svc = _make_service()
    result = await svc.match(async_session, goal)

    assert not result.is_partial
    selected = [c for c in result.jobs if c.job.id == job.id]
    assert len(selected) == 1
    assert selected[0].earnings == 200.0


@pytest.mark.asyncio
async def test_dp_partial_match(async_session, make_job, make_work_goal):
    """When no combination meets goal, returns best-effort subset with is_partial=True (D-05)."""
    await make_job(pay_rate=10.0, pay_type="flat", status="available")
    goal = await make_work_goal(target_earnings=500.0)

    svc = _make_service()
    result = await svc.match(async_session, goal)

    assert result.is_partial
    assert len(result.jobs) > 0
    assert result.total_earnings < goal.target_earnings


@pytest.mark.asyncio
async def test_empty_match(async_session, make_work_goal):
    """No jobs in DB -- MatchResult.is_empty=True, format returns graceful string (D-13)."""
    goal = await make_work_goal(target_earnings=100.0)

    svc = _make_service()
    result = await svc.match(async_session, goal)

    assert result.is_empty
    sms = format_match_sms(result)
    assert len(sms) > 0
    assert "No matching" in sms


# ---------------------------------------------------------------------------
# Sort order (D-11, D-12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sort_order(async_session, make_job, make_work_goal):
    """Soonest ideal_datetime first; NULL ideal_datetime sorts last."""
    now = datetime.now(UTC)
    job_soon = await make_job(
        pay_rate=10.0,
        pay_type="flat",
        status="available",
        ideal_datetime=now + timedelta(days=1),
    )
    job_later = await make_job(
        pay_rate=10.0,
        pay_type="flat",
        status="available",
        ideal_datetime=now + timedelta(days=5),
    )
    job_null = await make_job(
        pay_rate=10.0, pay_type="flat", status="available", ideal_datetime=None
    )
    goal = await make_work_goal(target_earnings=1.0)

    svc = _make_service()
    result = await svc.match(async_session, goal)

    ids = [c.job.id for c in result.jobs]
    if job_null.id in ids and job_soon.id in ids:
        assert ids.index(job_null.id) > ids.index(job_soon.id)
    if job_null.id in ids and job_later.id in ids:
        assert ids.index(job_null.id) > ids.index(job_later.id)


# ---------------------------------------------------------------------------
# MatchRepository.persist_matches -- idempotency (D-10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_persistence_idempotent(async_session, make_job, make_work_goal):
    """Calling persist_matches twice with same ids must not raise (D-10)."""
    job = await make_job(pay_rate=100.0, pay_type="flat", status="available")
    goal = await make_work_goal(target_earnings=50.0)

    repo = MatchRepository()
    await repo.persist_matches(async_session, [job.id], goal.id)
    await repo.persist_matches(async_session, [job.id], goal.id)

    from sqlmodel import select

    from src.matches.models import Match

    result = await async_session.execute(
        select(Match).where(Match.job_id == job.id).where(Match.work_goal_id == goal.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# SMS formatter (MATCH-02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sms_format_poster_phone(
    async_session, make_job, make_work_goal, make_user, make_message
):
    """Poster phone_e164 appears in each SMS job line (D-07)."""
    user = await make_user(phone_e164="+15551234567")
    message = await make_message(user=user)
    await make_job(
        message=message,
        pay_rate=25.0,
        pay_type="hourly",
        estimated_duration_hours=2.0,
        status="available",
    )
    goal = await make_work_goal(target_earnings=40.0)

    svc = _make_service()
    result = await svc.match(async_session, goal)
    sms = format_match_sms(result)

    assert "+15551234567" in sms


@pytest.mark.asyncio
async def test_sms_format_partial_summary(async_session, make_job, make_work_goal):
    """'Best available: $X of $Y goal' appears when is_partial=True (D-09)."""
    await make_job(pay_rate=10.0, pay_type="flat", status="available")
    goal = await make_work_goal(target_earnings=1000.0)

    svc = _make_service()
    result = await svc.match(async_session, goal)
    sms = format_match_sms(result)

    assert "Best available:" in sms
    assert "goal" in sms


@pytest.mark.asyncio
async def test_sms_format_empty():
    """Empty match returns graceful no-matches string (D-13)."""
    from src.work_goals.models import WorkGoal

    wg = WorkGoal(id=1, message_id=1, target_earnings=100.0)
    result = MatchResult(jobs=[], work_goal=wg, total_earnings=0.0, is_partial=True)
    sms = format_match_sms(result)
    assert len(sms) > 0
    assert "No matching" in sms


@pytest.mark.asyncio
async def test_sms_max_5_jobs(async_session, make_job, make_work_goal):
    """SMS output includes at most 5 job lines regardless of DP selection size (D-08)."""
    for _ in range(8):
        await make_job(pay_rate=5.0, pay_type="flat", status="available")
    goal = await make_work_goal(target_earnings=1.0)

    svc = _make_service()
    result = await svc.match(async_session, goal)
    sms = format_match_sms(result)

    job_lines = [line for line in sms.split("\n") if line and line[0].isdigit()]
    assert len(job_lines) <= 5
