---
status: awaiting_human_verify
trigger: "Render is still deploying the project — it should not be"
created: 2026-04-06T00:00:00Z
updated: 2026-04-06T00:00:00Z
---

## Current Focus

hypothesis: CONFIRMED - Active GitHub webhook sends push events to Render deploy API
test: gh api repos/ahcarpenter/vici/hooks
expecting: Found active Render webhook
next_action: Awaiting human verification that Render deploys have stopped

## Symptoms

expected: No Render deploys should happen — the project should not be deployed via Render at all.
actual: Render is still deploying the project somehow.
errors: None specific — the deploy itself may succeed, but it shouldn't be happening.
reproduction: Render deploys are triggered (likely on push to main or via Render dashboard config).
started: Project likely moved away from Render to GKE/Kubernetes.

## Eliminated

- hypothesis: render.yaml still exists in the repo
  evidence: render.yaml was removed in commit 07156c2. No render.yaml tracked by git. Only copies exist in .claude/worktrees/ (agent artifacts, not deployed).
  timestamp: 2026-04-06

- hypothesis: CI/CD workflows reference Render
  evidence: grep of .github/workflows/ for "render" returned zero matches
  timestamp: 2026-04-06

- hypothesis: Source code, Dockerfile, or docs reference Render
  evidence: grep of src/, docs/, README.md, and all .py/.yaml/.yml/.toml/.cfg/.env/.sh/Dockerfile files returned zero matches for render.com/onrender.com/render.yaml/RENDER_
  timestamp: 2026-04-06

## Evidence

- timestamp: 2026-04-06
  checked: git ls-files for render references
  found: Only .planning/todos/pending/2026-04-04-revise-setup-to-ensure-it-s-able-to-be-deployed-to-gks-v-render.md is tracked. No render.yaml in repo.
  implication: render.yaml was already cleaned up in commit 07156c2

- timestamp: 2026-04-06
  checked: GitHub webhooks via gh api repos/ahcarpenter/vici/hooks
  found: Active webhook (ID 599649549) sending push+workflow_run events to https://api.render.com/deploy/srv-d6mki1lactks7384v030. Created 2026-03-08, last response 202/active.
  implication: THIS is why Render still deploys. Every push to the repo triggers Render via this webhook.

- timestamp: 2026-04-06
  checked: Stale Render references in .planning/ docs
  found: ~20+ .planning/ files still reference Render.com as deployment target
  implication: Planning docs are stale but do not cause deploys. Low priority cleanup.

## Resolution

root_cause: A GitHub webhook (ID 599649549) was configured on the repo to send push and workflow_run events to the Render deploy API (https://api.render.com/deploy/srv-d6mki1lactks7384v030). This webhook was created on 2026-03-08 and remained active even after render.yaml was removed from the repo in commit 07156c2. Every push to any branch triggered a Render deployment via this hook.
fix: Deleted the webhook via `gh api -X DELETE repos/ahcarpenter/vici/hooks/599649549`. Verified no webhooks remain on the repo. User should also delete/suspend the Render service on the Render.com dashboard to fully decommission.
verification: gh api repos/ahcarpenter/vici/hooks returns empty array []
files_changed: []
