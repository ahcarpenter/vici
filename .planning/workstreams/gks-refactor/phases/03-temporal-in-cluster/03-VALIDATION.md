---
phase: 3
slug: temporal-in-cluster
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-04
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | kubectl / pulumi / temporal CLI (infrastructure validation — no unit test framework) |
| **Config file** | pulumi stack config |
| **Quick run command** | `kubectl get pods -n temporal` |
| **Full suite command** | `pulumi preview --stack gks-refactor && kubectl get pods -n temporal -o wide && kubectl get pods -n observability -o wide` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `kubectl get pods -n temporal`
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | TEMPORAL-01 | — | N/A | infra | `pulumi preview --stack gks-refactor` | ❌ W0 | ⬜ pending |
| 3-01-02 | 01 | 1 | TEMPORAL-02 | — | N/A | infra | `kubectl get pods -n temporal` | ❌ W0 | ⬜ pending |
| 3-01-03 | 01 | 2 | TEMPORAL-03 | — | N/A | infra | `kubectl exec -n temporal deploy/temporal-frontend -- temporal operator namespace list` | ❌ W0 | ⬜ pending |
| 3-01-04 | 01 | 2 | TEMPORAL-04 | — | N/A | infra | `kubectl get pods -n observability -l app=opensearch` | ❌ W0 | ⬜ pending |
| 3-01-05 | 01 | 3 | TEMPORAL-05 | — | N/A | manual | See manual verifications | — | ⬜ pending |
| 3-01-06 | 01 | 3 | TEMPORAL-06 | — | N/A | manual | See manual verifications | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Verify `kubectl` context is pointed at the GKE cluster
- [ ] Verify `pulumi stack select gks-refactor` is active
- [ ] Confirm `helm repo add temporal https://go.temporal.io/helm-charts` and `helm repo add opensearch https://opensearch-project.github.io/helm-charts/` are added

*These are preconditions, not test stubs — infrastructure phases use live cluster feedback.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Test workflow can be started and completed via `temporal-frontend.temporal.svc.cluster.local:7233` | TEMPORAL-05 | Requires running a workflow inside the cluster | `kubectl run temporal-test --image=temporalio/admin-tools --rm -it --restart=Never -- temporal workflow run --workflow-type helloWorld --task-queue test --address temporal-frontend.temporal.svc.cluster.local:7233` |
| OpenSearch visibility search returns results | TEMPORAL-06 | Requires at least one completed workflow | After TEMPORAL-05 test workflow completes, verify in Temporal UI that the workflow appears in search results |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
