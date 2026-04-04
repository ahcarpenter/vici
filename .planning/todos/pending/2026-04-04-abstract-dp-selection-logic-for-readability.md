---
created: 2026-04-04T18:31:26.458Z
title: Abstract DP selection logic for readability
area: general
files:
  - src/matches/service.py:102-158
---

## Problem

`_dp_select` in `MatchService` is a dense 50-line method that mixes three concerns inline: earnings quantization, DP table filling, and backtracking. The intent of each phase is not obvious without reading the docstring and comments carefully. The lambda `key=lambda w: dp[w]` and tuple-as-objective pattern are particularly opaque to a first reader.

## Solution

Refactor `_dp_select` into clearly named helper methods or a dedicated class (e.g. `KnapsackSolver`) that exposes named steps:
- `_quantize(earnings, scale)` → cents
- `_fill_table(candidates, capacity)` → `(dp, keep)`
- `_backtrack(candidates, keep, best_w)` → selected candidates
- `_best_weight(dp)` → `best_w`

This preserves the algorithm while making each phase independently readable and testable.
