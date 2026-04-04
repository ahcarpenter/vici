# Quick Task 260404-msz: Rename JobCandidate to AvailableJob

**Date:** 2026-04-04
**Commit:** 7561936

## What was done

Renamed `JobCandidate` → `AvailableJob` across 4 files:

- `src/matches/schemas.py` — class definition + docstring updated
- `src/matches/service.py` — all type annotations and usages
- `src/matches/formatter.py` — type annotation
- `tests/matches/test_match_service.py` — import and usages

116 tests pass, 1 skipped.
