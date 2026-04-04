---
created: 2026-04-04T18:27:53.860Z
title: Double check on caching opportunities around the dp flow
area: general
files:
  - src/matches/service.py:102-158
---

## Problem

`MatchService._dp_select` runs a full 0/1 knapsack DP on every invocation. For a given set of candidate jobs and target earnings, the result is deterministic — repeated calls with the same inputs recompute unnecessarily. No caching layer exists at the service or repository level for match results.

## Solution

Audit the DP flow for caching opportunities:
- Cache key candidates: `(frozenset of job_id + earnings, target_cents)` → selected job ids
- Consider memoizing at the `match()` call level (per work_goal_id + candidate snapshot)
- Evaluate whether Redis or in-process LRU cache (`functools.lru_cache` / `cachetools`) fits the use pattern
- Ensure cache invalidation is correct when job status changes (e.g. job accepted → no longer available)
