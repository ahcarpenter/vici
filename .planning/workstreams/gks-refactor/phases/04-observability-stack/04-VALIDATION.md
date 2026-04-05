---
phase: 4
slug: observability-stack
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | kubectl / helm / pulumi preview |
| **Config file** | none — infrastructure-only phase |
| **Quick run command** | `kubectl get pods -n observability` |
| **Full suite command** | `kubectl get pods -n observability && kubectl get servicemonitor -n observability` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `kubectl get pods -n observability`
- **After every plan wave:** Run `kubectl get pods -n observability && kubectl get servicemonitor -n observability`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-xx-01 | 01 | 1 | OBS-01 | — | Jaeger collector endpoint reachable in-cluster | manual | `kubectl exec -n default <pod> -- curl http://jaeger-collector.observability.svc.cluster.local:4317` | ❌ W0 | ⬜ pending |
| 04-xx-02 | 01 | 1 | OBS-02 | — | Prometheus scrapes /metrics via ServiceMonitor | manual | `kubectl get servicemonitor -n observability` | ❌ W0 | ⬜ pending |
| 04-xx-03 | 01 | 2 | OBS-03 | — | Grafana accessible and dashboards provisioned | manual | `kubectl get svc -n observability grafana` | ❌ W0 | ⬜ pending |
| 04-xx-04 | 01 | 2 | OBS-04 | — | Dashboard ConfigMaps labeled grafana_dashboard=1 | manual | `kubectl get configmap -n observability -l grafana_dashboard=1` | ❌ W0 | ⬜ pending |
| 04-xx-05 | 01 | 3 | OBS-05 | — | OTEL_EXPORTER_OTLP_ENDPOINT secret resolves | manual | `kubectl get secret -n default otel-endpoint` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Verify `kubectl` and `helm` CLIs available in environment
- [ ] Confirm `observability` namespace exists or will be created in Wave 1
- [ ] Confirm Pulumi stack is accessible: `pulumi stack ls`

*Infrastructure-only phase — no automated test files to install.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Jaeger UI shows traces | OBS-01 | Requires live request through app | Send test request, open Jaeger UI port-forward, verify trace appears |
| Prometheus scraping FastAPI | OBS-02 | Requires live metrics endpoint | Port-forward Prometheus, check Targets page for FastAPI endpoint |
| Grafana dashboards loaded | OBS-03, OBS-04 | Requires visual inspection | Port-forward Grafana, verify FastAPI dashboard is pre-provisioned |
| OTEL secret resolves in-cluster | OBS-05 | Requires pod-level DNS resolution | Exec into app pod, verify env var resolves to collector |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
