---
phase: 1
slug: infrastructure-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) — Wave 0 creates |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -v --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | DEP-01 | manual | `docker compose up --wait && curl localhost:8000/health` | N/A | ⬜ pending |
| 1-01-02 | 01 | 1 | DEP-01 | manual | `docker compose up --wait && alembic upgrade head` | N/A | ⬜ pending |
| 1-01-03 | 01 | 1 | ASYNC-01 | integration | `pytest tests/sms/test_webhook.py::test_inngest_event_emitted -x` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 2 | SEC-01 | integration | `pytest tests/sms/test_webhook.py::test_invalid_signature -x` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 2 | SEC-01 | integration | `pytest tests/sms/test_webhook.py::test_valid_signature -x` | ❌ W0 | ⬜ pending |
| 1-02-03 | 02 | 2 | SEC-02 | integration | `pytest tests/sms/test_webhook.py::test_idempotency -x` | ❌ W0 | ⬜ pending |
| 1-02-04 | 02 | 2 | SEC-03 | integration | `pytest tests/sms/test_webhook.py::test_rate_limit -x` | ❌ W0 | ⬜ pending |
| 1-02-05 | 02 | 2 | SEC-04 | integration | `pytest tests/sms/test_webhook.py::test_audit_row_created -x` | ❌ W0 | ⬜ pending |
| 1-02-06 | 02 | 2 | IDN-01 | integration | `pytest tests/sms/test_webhook.py::test_phone_auto_register -x` | ❌ W0 | ⬜ pending |
| 1-02-07 | 02 | 2 | IDN-02 | unit | `pytest tests/sms/test_webhook.py::test_phone_created_at -x` | ❌ W0 | ⬜ pending |
| 1-03-01 | 03 | 3 | OBS-02 | integration | `pytest tests/test_health.py::test_metrics_endpoint -x` | ❌ W0 | ⬜ pending |
| 1-03-02 | 03 | 3 | OBS-03 | manual | Verify via Jaeger UI at http://localhost:16686 | N/A | ⬜ pending |
| 1-03-03 | 03 | 3 | OBS-04 | unit | `pytest tests/test_logging.py::test_trace_id_in_log -x` | ❌ W0 | ⬜ pending |
| 1-03-04 | 03 | 3 | DEP-02 | integration | `pytest tests/test_health.py::test_health_endpoint -x` | ❌ W0 | ⬜ pending |
| 1-03-05 | 03 | 3 | ASYNC-03 | manual | `docker compose up --wait && curl http://localhost:8000/health` | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — shared fixtures: async test DB, mock Twilio `RequestValidator`, mock Inngest client
- [ ] `tests/sms/test_webhook.py` — stubs for SEC-01, SEC-02, SEC-03, SEC-04, IDN-01, IDN-02, ASYNC-01
- [ ] `tests/test_health.py` — stubs for DEP-02, OBS-02
- [ ] `tests/test_logging.py` — stubs for OBS-04
- [ ] `pyproject.toml` — pytest + pytest-asyncio config (`asyncio_mode = "auto"`, test paths)
- [ ] Framework install: `uv add --dev pytest pytest-asyncio httpx` — none detected yet

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| OTel spans appear in Jaeger UI | OBS-03 | No mock OTLP collector in test suite; Jaeger is a Docker service | `docker compose up --wait`, send a test SMS via curl to `/webhook/sms`, open `http://localhost:16686` and verify traces appear |
| `docker compose up` starts all services + applies migrations | DEP-01, ASYNC-03 | Requires live Docker daemon and network | `docker compose up --wait && curl http://localhost:8000/health` — all services should return healthy |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
