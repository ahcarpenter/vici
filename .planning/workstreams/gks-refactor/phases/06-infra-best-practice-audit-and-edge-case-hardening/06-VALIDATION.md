---
phase: 6
slug: infra-best-practice-audit-and-edge-case-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-06
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing) |
| **Config file** | `pyproject.toml` (existing) |
| **Quick run command** | `pytest tests/infra/test_phase6_static.py -x` |
| **Full suite command** | `pytest -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/infra/test_phase6_static.py -x`
- **After every plan wave:** Run `pytest -x`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | SC-1 | T-6-01 | protect=True prevents accidental deletion | static AST | `pytest tests/infra/test_phase6_static.py::TestProtect -x` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 1 | SC-2 | T-6-03 | default-deny NetworkPolicy per namespace | static AST | `pytest tests/infra/test_phase6_static.py::TestNetworkPolicy -x` | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 2 | SC-3 | T-6-02 | Temporal creds via ESO, not stack secrets | static AST | `pytest tests/infra/test_phase6_static.py::TestTemporalESO -x` | ❌ W0 | ⬜ pending |
| 06-04-01 | 04 | 2 | SC-4 | T-6-04 | PDB prevents total replica eviction | static AST | `pytest tests/infra/test_phase6_static.py::TestPDB -x` | ❌ W0 | ⬜ pending |
| 06-05-01 | 05 | 3 | SC-5 | — | OPERATIONS.md documents procedures | file content | `pytest tests/infra/test_phase6_static.py::TestOperationsDoc -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/infra/test_phase6_static.py` — covers all 5 success criteria (new file, following pattern of `test_observability_static.py`)

*Existing test infrastructure (pytest, conftest) covers all other needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Temporal pod labels match PDB selectors | SC-4 | Labels are Helm-generated; only verifiable against running cluster | Run `kubectl get pods -n temporal --show-labels` and compare with PDB matchLabels |
| `pulumi preview` shows zero changes after full deploy | All | Requires live Pulumi state | Run `pulumi preview --stack dev` and confirm no changes proposed |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
