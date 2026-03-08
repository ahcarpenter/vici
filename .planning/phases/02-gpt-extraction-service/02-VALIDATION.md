---
phase: 2
slug: gpt-extraction-service
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-07
audited: 2026-03-08
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (already installed) |
| **Config file** | `pyproject.toml` — `asyncio_mode = "auto"` |
| **Quick run command** | `pytest tests/extraction/ -x -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/extraction/ -x -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 0 | EXT-01 | unit | `pytest tests/extraction/test_service.py::test_classify_job -x` | ✅ | ✅ green |
| 2-01-02 | 01 | 0 | EXT-01 | unit | `pytest tests/extraction/test_service.py::test_classify_worker -x` | ✅ | ✅ green |
| 2-01-03 | 01 | 0 | EXT-04 | unit | `pytest tests/extraction/test_service.py::test_classify_unknown -x` | ✅ | ✅ green |
| 2-01-04 | 01 | 1 | EXT-02 | unit | `pytest tests/extraction/test_schemas.py::test_job_extraction_schema -x` | ✅ | ✅ green |
| 2-01-05 | 01 | 1 | EXT-03 | unit | `pytest tests/extraction/test_schemas.py::test_worker_extraction_schema -x` | ✅ | ✅ green |
| 2-01-06 | 01 | 1 | OBS-01 | unit | `pytest tests/extraction/test_service.py::test_braintrust_instrumentation -x` | ✅ | ✅ green |
| 2-02-01 | 02 | 0 | STR-01 | integration | `pytest tests/extraction/test_persistence.py::test_job_persistence -x` | ✅ | ✅ green |
| 2-02-02 | 02 | 0 | STR-02 | integration | `pytest tests/extraction/test_persistence.py::test_worker_persistence -x` | ✅ | ✅ green |
| 2-02-03 | 02 | 1 | VEC-01 | unit | `pytest tests/extraction/test_persistence.py::test_pinecone_upsert -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/extraction/__init__.py` — package init
- [ ] `tests/extraction/test_schemas.py` — Pydantic schema validation tests (EXT-02, EXT-03)
- [ ] `tests/extraction/test_service.py` — ExtractionService unit + integration stubs with AsyncMock (EXT-01, EXT-04, STR-01, STR-02, VEC-01, OBS-01)
- [ ] `tests/extraction/conftest.py` — shared mock client fixtures (mock OpenAI, mock Pinecone, mock DB session)

*Existing `tests/conftest.py` session fixtures can be reused; extraction tests need their own mock factories.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end SMS → DB → Pinecone round trip | STR-01, VEC-01 | Requires live Pinecone index and DB | Send test SMS via Twilio sandbox, verify DB record + Pinecone upsert in dashboard |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** ✅ Nyquist-compliant — 9/9 requirements covered, 29/29 tests passing (2026-03-08)
