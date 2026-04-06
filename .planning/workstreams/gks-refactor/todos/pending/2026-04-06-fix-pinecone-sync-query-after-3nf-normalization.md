---
created: 2026-04-06T04:05:58.303Z
title: Fix Pinecone sync query after 3NF normalization
area: database
files:
  - src/workflows/pinecone_sync.py
---

## Problem

The cron workflow throws a non-fatal error because `j.user_id` was removed during Phase 02.14 (3NF normalization) but the Pinecone sync query was not updated to reflect the new schema. The app is otherwise healthy — readiness probe returns 200 and requests are being served — but the background Pinecone sync workflow fails on the stale column reference.

## Solution

Update the Pinecone sync query to join through the correct normalized table(s) to resolve `user_id` instead of referencing `j.user_id` directly. Verify the full query path against the current 3NF schema.
