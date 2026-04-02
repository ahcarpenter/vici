---
created: 2026-04-02T21:53:46.947Z
title: Refactor code such that Temporal is able to be leveraged
area: general
files:
  - src/inngest_client.py
  - src/sms/service.py
  - src/sms/router.py
  - src/main.py
---

## Problem

The current async workflow orchestration is built on Inngest. Temporal is a more powerful workflow engine with stronger durability guarantees, retry semantics, and observability. To adopt Temporal, the codebase needs to be refactored to decouple workflow orchestration from Inngest-specific APIs — currently embedded throughout `src/inngest_client.py`, `src/sms/`, and `src/main.py`.

## Solution

TBD — likely involves:
1. Abstracting the workflow trigger/handler interface so Inngest and Temporal are interchangeable
2. Replacing `src/inngest_client.py` with a Temporal worker + activity definitions
3. Updating the `process-message` event flow to use Temporal workflows
4. Migrating Inngest-specific retry/event configs to Temporal equivalents
