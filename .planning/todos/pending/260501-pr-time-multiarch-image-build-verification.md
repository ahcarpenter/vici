---
created: 2026-05-01
title: Add PR-time multi-arch image build verification (no push) to catch Dockerfile breakage before merge
area: ci/build
files:
  - .github/workflows/ci.yml
---

# PR-Time Multi-Arch Image Build Verification

## Problem

Phase 5 publishes multi-arch GHCR images on `push: main`, `push: tags`, and `workflow_dispatch` only — PRs do **not** build images. This is a deliberate cost/speed tradeoff (PR builds add ~5–10 min per merge). The downside: a Dockerfile change that breaks one architecture (or breaks both via a syntax error) is only caught after the PR merges to `main`, polluting `main` history with a broken image push and forcing a follow-up revert PR.

## Solution

Add a PR-only job to `.github/workflows/ci.yml` that runs the same multi-arch buildx build path as the publish jobs but with `push: false`:

- Trigger: `pull_request: branches: [main]`
- Same matrix as `build-amd64` / `build-arm64` (`ubuntu-latest` + `ubuntu-24.04-arm`)
- `docker/build-push-action@v6` with `push: false`, same `cache-from: type=gha,scope=<arch>` so PR builds reuse the merge job's cache
- No manifest merge step — purely a build-doesn't-fail check
- Runs in parallel with existing PR jobs (lint, test, compose-validate)

## Context

Captured as a deferred idea during `/gsd-discuss-phase 5` (2026-05-01) Build Triggers + Tags discussion. User chose "main push + git tag + workflow_dispatch" for Phase 5 and explicitly asked for a todo to track adding PR builds later. Defensible to add when:

1. Dockerfile churn becomes frequent (e.g., during a Phase 6/7/8 hardening pass)
2. A Dockerfile-breaking commit lands on `main` and forces a revert (track this signal)
3. The repo gets external contributors whose PRs touch Docker build context

## Acceptance

- A `build-verify-pr` job (or matrix) added to `ci.yml`, gated on `pull_request` event
- Job builds both `linux/amd64` and `linux/arm64` with `push: false`
- Job uses GHA cache shared with the publish jobs (`scope=amd64` / `scope=arm64`)
- PR runtime impact measured and documented (expected ~5–8 min added to PR turnaround)
- README or DEPLOY.md mentions PR builds run for verification
