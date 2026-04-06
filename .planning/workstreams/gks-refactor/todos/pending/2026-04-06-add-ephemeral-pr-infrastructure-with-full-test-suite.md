---
created: 2026-04-06T01:40:43.305Z
title: Add ephemeral PR infrastructure with full test suite
area: tooling
files: []
---

## Problem

Pull requests currently have no dedicated infrastructure to test against. There is no mechanism to spin up one-off environments per PR, meaning changes cannot be validated against real infrastructure before merging. This creates risk of deploying untested infrastructure changes and makes it impossible to run the full test suite against a live environment that mirrors production.

## Solution

Set up ephemeral per-PR infrastructure provisioning:

1. **PR-triggered infrastructure**: On PR open/update, provision a one-off GKE namespace (or equivalent isolated environment) with all required resources (database, Temporal, observability stack)
2. **Full test suite execution**: Run the complete test suite against the ephemeral deploy — not just unit tests, but integration and E2E tests against real infrastructure
3. **Automatic teardown**: On PR close/merge, destroy the ephemeral environment to avoid cost accumulation
4. **Status reporting**: Report test results back to the PR as a GitHub check/comment

Potential approaches:
- GitHub Actions workflow with Pulumi/CDK preview stacks per PR
- GKE namespace-per-PR with Helm value overrides
- Argo CD ApplicationSet with PR generator
