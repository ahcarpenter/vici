---
phase: 5
slug: application-deployment-and-ci-cd
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing) |
| **Config file** | `pyproject.toml` (existing) |
| **Quick run command** | `uv run pytest tests/ -x --tb=short -q` |
| **Full suite command** | `uv run pytest tests/ --tb=short -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x --tb=short -q`
- **After every plan wave:** Run `uv run pytest tests/ --tb=short -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | APP-01 | — | N/A | smoke | `kubectl get deployment vici-app -n vici` | ✅ | ⬜ pending |
| 05-01-02 | 01 | 1 | APP-02 | — | N/A | smoke | `kubectl logs -n vici deploy/vici-app -c vici-app \| grep temporal` | ✅ | ⬜ pending |
| 05-01-03 | 01 | 1 | APP-03 | — | N/A | smoke | `kubectl get hpa vici-app -n vici` | ✅ | ⬜ pending |
| 05-02-01 | 02 | 1 | APP-04 | T-05-01 | TLS cert auto-renewed by cert-manager | smoke | `kubectl describe certificate vici-tls -n vici` | ✅ | ⬜ pending |
| 05-02-02 | 02 | 1 | APP-05 | — | N/A | integration | `curl -s -o /dev/null -w "%{http_code}" https://<hostname>/health` | ❌ W0 | ⬜ pending |
| 05-02-03 | 02 | 1 | APP-06 | — | N/A | manual | Verify in GCP Secret Manager console | ❌ W0 | ⬜ pending |
| 05-03-01 | 03 | 2 | CD-01 | T-05-02 | WIF OIDC only, no static keys | integration | Push trivial commit; check GitHub Actions run | ❌ W0 | ⬜ pending |
| 05-03-02 | 03 | 2 | CD-02 | — | N/A | integration | Open PR; check `pulumi preview` output | ❌ W0 | ⬜ pending |
| 05-03-03 | 03 | 2 | CD-03 | T-05-03 | Prod requires approval gate | integration | Trigger `cd-prod.yml`; verify approval request | ❌ W0 | ⬜ pending |
| 05-03-04 | 03 | 2 | CD-04 | T-05-04 | No static GCP keys in GitHub secrets | manual | Inspect GitHub Actions secrets; verify WIF only | ❌ W0 | ⬜ pending |
| 05-03-05 | 03 | 2 | CD-05 | — | N/A | unit | `uv run pytest tests/ -x --tb=short -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- No new test files required — Phase 5 is infrastructure and CI/CD only; application code is unchanged
- Manual cluster validation steps (APP-01 through APP-05) documented above cannot be automated before the cluster exists

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `WEBHOOK_BASE_URL` env var matches Ingress hostname | APP-06 | Requires GCP console inspection | Verify in GCP Secret Manager that `WEBHOOK_BASE_URL` value equals the Ingress hostname |
| No static GCP keys in GitHub secrets | CD-04 | Requires GitHub UI audit | Navigate to repo Settings > Secrets; verify no `GCP_SA_KEY` or similar static credential |
| Prod deploy requires approval | CD-03 | Requires GitHub Environment setup | Trigger `cd-prod.yml`; verify reviewer approval prompt appears before deployment |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
