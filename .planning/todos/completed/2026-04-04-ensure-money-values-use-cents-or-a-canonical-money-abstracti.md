---
created: 2026-04-04T18:05:06.396Z
title: Ensure money values use cents or a canonical money abstraction
area: general
files:
  - src/matches/service.py:118-121
---

## Problem

`_dp_select` in `MatchService` manually scales dollar floats to integer cents using `SCALE = 100` inline. This pattern may exist elsewhere in the codebase (earnings, payments, goals). Floating-point money arithmetic is error-prone and the scaling logic is ad-hoc with no shared abstraction.

## Solution

Audit all money-related fields across models, schemas, and service logic. Either:
- Standardize on storing/passing cents as `int` throughout (convert only at API boundary), or
- Introduce a canonical `Money` value object (e.g. using `decimal.Decimal` or a library like `py-moneyed`) that encapsulates currency and prevents float arithmetic

Ensure DB columns storing money use `NUMERIC`/`DECIMAL` types, not `FLOAT`.
