---
created: 2026-04-05T06:50:16.828Z
title: Set up distributed caching and push-based cache invalidation
area: general
files: []
---

## Problem

No distributed caching layer exists. DB query results, match computations, and other deterministic/expensive operations are recomputed on every request. In a multi-replica deployment (GKE with HPA), in-process caches (e.g. `lru_cache`) are per-pod and provide no shared benefit. Real-time invalidation of stale cache entries is also unaddressed.

## Solution

- Provision a Redis instance (Cloud Memorystore or equivalent) as the shared cache backend
- Audit all service/repository layers for caching candidates: DB query results (jobs, work goals, users), match results, extraction results
- Implement a push-based invalidation scheme: on job creation/update/deletion, publish an invalidation event (Pub/Sub or Redis keyspace notifications) so all replicas evict stale entries immediately
- Consider cache-aside pattern at the repository level for read-heavy queries
- See also: todo "Double check on caching opportunities around the dp flow" for DP-specific memoization
