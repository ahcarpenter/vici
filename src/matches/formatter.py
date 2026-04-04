import structlog

from src.matches.schemas import AvailableJob, MatchResult
from src.money import cents_to_dollars

SMS_SEGMENT_CHARS = 160
MAX_JOBS_IN_SMS = 5

log = structlog.get_logger()


def format_match_sms(result: MatchResult) -> str:
    """
    Build SMS text for matched jobs (D-07, D-08, D-09, D-13).

    - Empty result: returns graceful no-matches message (D-13)
    - Partial match: appends "Best available: $X of $Y goal" summary (D-09)
    - Multi-segment SMS is acceptable (D-08); logs warning if > 3 segments (480 chars)
    - Shows top MAX_JOBS_IN_SMS jobs sorted per D-11/D-12 (caller already sorted)
    """
    if result.is_empty:
        return "No matching jobs found for your goal right now. Text us again soon!"

    lines = []
    for rank, cand in enumerate(result.jobs[:MAX_JOBS_IN_SMS], start=1):
        line = _format_job_line(rank, cand)
        lines.append(line)

    if result.is_partial:
        earned = cents_to_dollars(result.total_earnings)
        goal = cents_to_dollars(result.work_goal.target_earnings)
        lines.append(f"Best available: ${earned:.0f} of ${goal:.0f} goal")

    text = "\n".join(lines)

    if len(text) > SMS_SEGMENT_CHARS * 3:
        log.warning(
            "match.sms_exceeds_3_segments",
            char_count=len(text),
            job_count=len(result.jobs),
        )

    return text


def _format_job_line(rank: int, cand: AvailableJob) -> str:
    """Format a single job entry for SMS output."""
    desc = (cand.job.description or "Job")[:30]
    loc = (cand.job.location or "?")[:20]
    phone = cand.poster_phone or "N/A"
    dur_str = f"{cand.duration:.1f}h" if cand.duration else "flat"
    return f"{rank}. {desc} @ {loc} | ${cents_to_dollars(cand.earnings):.0f}/{dur_str} | {phone}"
