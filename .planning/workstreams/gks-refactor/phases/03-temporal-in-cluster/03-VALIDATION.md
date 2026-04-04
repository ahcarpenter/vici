---
phase: 3
slug: temporal-in-cluster
status: draft
nyquist_compliant: true
wave_0_complete: true
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
| 3-01-01 | 01 | 1 | TEMPORAL-02, TEMPORAL-03, OBS-01 | T-03-01, T-03-02 | ClusterIP-only OpenSearch | infra | `python -c "import ast; ast.parse(open('infra/components/opensearch.py').read())"` | n/a (creates file) | pending |
| 3-02-01 | 02 | 2 | TEMPORAL-01, TEMPORAL-04 | T-03-03, T-03-04 | Auth Proxy IAM auth; backoff_limit=0 | infra | `python -c "import ast; ast.parse(open('infra/components/temporal.py').read())"` | n/a (creates file) | pending |
| 3-02-02 | 02 | 2 | TEMPORAL-01, TEMPORAL-05, TEMPORAL-06 | T-03-05, T-03-06, T-03-07 | ClusterIP-only Temporal UI; numHistoryShards=512 | infra | `python -c "import ast; ast.parse(open('infra/components/temporal.py').read())"` | n/a (appends to file) | pending |
| 3-03-01 | 03 | 3 | TEMPORAL-01, TEMPORAL-02 | T-03-08 | N/A | infra | `python -c "import ast; ast.parse(open('infra/__main__.py').read())"` | exists | pending |
| 3-03-02 | 03 | 3 | TEMPORAL-05 | — | N/A | infra | `grep -q 'temporal-host.*vici.*temporal-host' infra/components/secrets.py` | exists | pending |
| 3-03-03 | 03 | 3 | TEMPORAL-01 thru TEMPORAL-06 | — | N/A | manual | See manual verifications | — | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [x] Verify `kubectl` context is pointed at the GKE cluster
- [x] Verify `pulumi stack select gks-refactor` is active
- [x] Confirm `helm repo add temporal https://go.temporal.io/helm-charts` and `helm repo add opensearch https://opensearch-project.github.io/helm-charts/` are added

*These are preconditions, not test stubs — infrastructure phases use live cluster feedback.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Test workflow can be started and completed via `temporal-frontend.temporal.svc.cluster.local:7233` | TEMPORAL-05 | Requires running a workflow inside the cluster | `kubectl run temporal-test --image=temporalio/admin-tools --rm -it --restart=Never -- temporal workflow run --workflow-type helloWorld --task-queue test --address temporal-frontend.temporal.svc.cluster.local:7233` |
| OpenSearch visibility search returns results | TEMPORAL-06 | Requires at least one completed workflow | After TEMPORAL-05 test workflow completes, verify in Temporal UI that the workflow appears in search results |
| TEMPORAL_HOST ExternalSecret syncs correctly | TEMPORAL-05 | Requires live cluster + GCP Secret Manager value | `kubectl get externalsecret temporal-host -n vici -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'` should return `True` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
