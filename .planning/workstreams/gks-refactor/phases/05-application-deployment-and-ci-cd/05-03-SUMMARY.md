---
phase: 05-application-deployment-and-ci-cd
plan: 03
subsystem: infra
tags: [gcp, wif, github-actions, ci-cd, pulumi, iam, oidc]
dependency_graph:
  requires:
    - infra/components/identity.py (ci_push_sa)
    - infra/components/cluster.py (cluster)
    - infra/config.py (ENV, GITHUB_ORG, PROJECT_ID)
    - infra/components/app.py (Plan 01)
    - infra/components/certmanager.py (Plan 02)
    - infra/components/ingress.py (Plan 02)
  provides:
    - infra/components/cd.py (wif_pool, wif_provider)
    - .github/workflows/cd-base.yml (reusable CD workflow)
    - .github/workflows/cd-dev.yml (dev deployment trigger)
    - .github/workflows/cd-staging.yml (staging preview + deploy)
    - .github/workflows/cd-prod.yml (prod manual deployment with approval gate)
    - infra/__main__.py (all Phase 5 components wired)
  affects:
    - GitHub Actions (WIF keyless auth for GCP access)
    - GKE (ci_push_sa has roles/container.developer)
    - GCS (ci_push_sa has roles/storage.objectAdmin for Pulumi state)
tech_stack:
  added:
    - gcp.iam.WorkloadIdentityPool (keyless GitHub Actions -> GCP auth)
    - gcp.iam.WorkloadIdentityPoolProvider (OIDC provider for GitHub)
    - gcp.serviceaccount.IAMBinding (ci_push_sa WIF binding)
    - gcp.projects.IAMMember (storage.objectAdmin + container.developer)
    - GitHub Actions reusable workflow (workflow_call pattern)
  patterns:
    - WIF attribute_condition scoped to repository_owner (T-05-10)
    - Per-environment workflow files calling shared cd-base.yml
    - Skip docker build on preview commands (if inputs.command == 'up')
    - GitHub environment approval gate for prod (CD-03)
key_files:
  created:
    - infra/components/cd.py
    - .github/workflows/cd-base.yml
    - .github/workflows/cd-dev.yml
    - .github/workflows/cd-staging.yml
    - .github/workflows/cd-prod.yml
  modified:
    - infra/__main__.py
decisions:
  - "WIF attribute_condition scoped to assertion.repository_owner == GITHUB_ORG to prevent cross-org token acceptance (T-05-10)"
  - "roles/storage.objectAdmin granted at project level (not bucket level) — acceptable per T-05-15 accept disposition since state bucket is env-scoped"
  - "ruff auto-reformatted existing __main__.py multi-import lines into parenthesized blocks; noqa: E501 added to pre-existing long comment"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-06"
  tasks_completed: 3
  files_created: 6
  files_modified: 1
---

# Phase 05 Plan 03: WIF + CD Workflows + Component Wiring Summary

**One-liner:** GCP Workload Identity Federation pool/provider for keyless GitHub Actions auth, four CD workflow files (reusable base + per-env triggers), and all Phase 5 Pulumi components registered in __main__.py.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create infra/components/cd.py -- WIF pool, OIDC provider, CI SA IAM bindings | 2964d51 | infra/components/cd.py (created) |
| 2 | Create GitHub Actions CD workflow files | 071e6b0 | .github/workflows/cd-base.yml, cd-dev.yml, cd-staging.yml, cd-prod.yml (created) |
| 3 | Wire all Phase 5 components into infra/__main__.py | ab8d141 | infra/__main__.py (modified) |

## What Was Built

### Task 1: infra/components/cd.py

Created the WIF Pulumi component:

**WIF Pool (`github-wif-pool`):**
- Pool ID: `github-actions-{ENV}` — one pool per GCP project/environment
- Display name includes environment for operator clarity

**WIF OIDC Provider (`github-wif-provider`):**
- Issuer: `https://token.actions.githubusercontent.com`
- Attribute mapping: `google.subject`, `attribute.actor`, `attribute.repository`, `attribute.repository_owner`
- `attribute_condition`: `assertion.repository_owner == 'ahcarpenter'` — scopes trust to this org only (T-05-10)

**CI SA WIF IAM Binding:**
- `roles/iam.workloadIdentityUser` on `ci_push_sa` for `principalSet://iam.googleapis.com/{pool}/attribute.repository/ahcarpenter/vici`
- Scoped to single repo path to minimize blast radius

**Additional CI SA IAM Roles:**
- `roles/storage.objectAdmin` — Pulumi GCS state backend read/write
- `roles/container.developer` — GKE cluster deployment access (T-05-12)
- Note: `roles/artifactregistry.writer` already bound in `registry.py`

**Stack Outputs:**
- `wif_pool_id`, `wif_provider_name`, `ci_push_sa_email`

### Task 2: GitHub Actions CD Workflow Files

**cd-base.yml (reusable workflow):**
- `workflow_call` trigger accepting `stack`, `command`, `environment` inputs
- Secrets: `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, `PULUMI_ACCESS_TOKEN`
- `id-token: write` permission for OIDC token issuance
- `google-github-actions/auth@v3` for keyless WIF authentication (D-07)
- Docker build+push with SHA tag + env tag — skipped on `preview` commands (`if: inputs.command == 'up'`)
- `astral-sh/setup-uv@v5` matching existing `ci.yml` pattern
- `pulumi/actions@v6` for Pulumi operations

**cd-dev.yml:**
- Triggers on `push: branches: [main]` (D-08, CD-01)
- Calls cd-base.yml with `stack: dev`, `command: up`
- Uses `GCP_WIF_PROVIDER_DEV` and `GCP_CI_SA_DEV` secrets

**cd-staging.yml:**
- Triggers on `pull_request` (runs `preview`) and `workflow_dispatch` (runs `up`) (D-09, CD-02)
- Two jobs conditioned on `github.event_name` — no unnecessary deployments on PRs

**cd-prod.yml:**
- Manual `workflow_dispatch` only (D-10, CD-03)
- `environment: prod` input triggers GitHub environment approval gate
- Uses `GCP_WIF_PROVIDER_PROD` and `GCP_CI_SA_PROD` secrets

### Task 3: infra/__main__.py Update

Added four Phase 5 component imports after existing 11 imports:
- `from components.certmanager import certmanager_release`
- `from components.app import app_deployment, app_hpa, app_service`
- `from components.ingress import prod_issuer, staging_issuer, vici_ingress, webhook_base_url_version`
- `from components.cd import wif_pool, wif_provider`

ruff auto-reformatted existing long import lines into parenthesized multi-line blocks (jaeger, prometheus, secrets). Final file has 15 distinct component modules registered.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ruff reformatted pre-existing long imports in __main__.py**
- **Found during:** Task 3
- **Issue:** Running `ruff check --fix` on `__main__.py` reorganized several pre-existing import lines into parenthesized blocks (jaeger, prometheus, secrets) and added `# noqa: E501` to a pre-existing long comment on line 3. These were latent ruff violations in the original file.
- **Fix:** Applied ruff auto-fix; added `# noqa: E501` to the long header comment
- **Files modified:** infra/__main__.py
- **Commit:** ab8d141

## Threat Mitigation Coverage

All six threats from the plan's STRIDE register are addressed:

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-05-10 | WIF `attribute_condition` scoped to `assertion.repository_owner == 'ahcarpenter'` | Implemented |
| T-05-11 | Only `vici-ci-push` SA has `roles/artifactregistry.writer` (bound in registry.py) | Inherited |
| T-05-12 | CI SA has minimum roles: `artifactregistry.writer`, `storage.objectAdmin`, `container.developer` | Implemented |
| T-05-13 | cd-prod.yml requires `environment: prod` with GitHub required reviewers gate | Implemented |
| T-05-14 | No static SA keys; WIF OIDC provides short-lived tokens only | Implemented |
| T-05-15 | `storage.objectAdmin` accept disposition — CI SA is only writer, state bucket is env-scoped | Accepted |

## Known Stubs

None — all values are wired from actual Pulumi outputs and stack config (`ENV`, `GITHUB_ORG`, `PROJECT_ID`). No hardcoded credentials.

## Threat Flags

None — no new security surface introduced beyond what the plan's threat model covers.

## Self-Check: PASSED

- [x] `infra/components/cd.py` exists with WIF pool, provider, and IAM bindings
- [x] `_WIF_POOL_ID = f"github-actions-{ENV}"` present
- [x] `_GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"` present
- [x] `attribute_condition` scoped to `GITHUB_ORG` present
- [x] `roles/iam.workloadIdentityUser`, `roles/storage.objectAdmin`, `roles/container.developer` present
- [x] No static credentials in any file
- [x] `.github/workflows/cd-base.yml` contains `workflow_call:`, `id-token: write`, `google-github-actions/auth@v3`, `pulumi/actions@v6`, `docker build`, `docker push`, `if: inputs.command == 'up'`
- [x] `cd-dev.yml` triggers on `push: branches: [main]`, `command: up`, `stack: dev`
- [x] `cd-staging.yml` triggers on `pull_request` and `workflow_dispatch`, has `command: preview` and `command: up`
- [x] `cd-prod.yml` triggers on `workflow_dispatch` only, has `environment: prod`
- [x] `.github/workflows/ci.yml` unchanged (diff shows no changes)
- [x] `infra/__main__.py` has all four new Phase 5 imports
- [x] `ruff check` passes on cd.py and __main__.py
- [x] Commits 2964d51, 071e6b0, ab8d141 verified in git log
