---
created: 2026-04-04T13:47:33.175Z
title: Add follow-up conversation flow to re-request missing extraction fields
area: pipeline
files:
  - src/extraction/schemas.py
  - src/pipeline/handlers/job_posting.py
  - src/pipeline/handlers/worker_goal.py
---

## Problem

When GPT extracts a job posting or worker goal, some fields may come back NULL (e.g., `estimated_duration_hours`, `pay_rate`, `target_timeframe`). Currently those records are stored as-is with no mechanism to ask the user for the missing data. This degrades matching quality — partial-data jobs are deprioritized but never improved.

## Solution

Add an outbound SMS flow (triggered after storage) that detects incomplete records and sends a follow-up question to the original poster requesting the missing field(s). Wire into the pipeline handler or PipelineOrchestrator after the storage step. Keep it to one follow-up question per field, prioritize the most impactful missing field (pay_rate > estimated_duration_hours > others).
