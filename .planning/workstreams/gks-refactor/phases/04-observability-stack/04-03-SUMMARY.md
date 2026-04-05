---
phase: 04-observability-stack
plan: "03"
subsystem: infra/observability
tags: [pulumi, jaeger, prometheus, secrets, kubernetes]
dependency_graph:
  requires:
    - 04-01 (jaeger.py component)
    - 04-02 (prometheus.py component)
  provides:
    - observability component registration in __main__.py
    - OTEL ExternalSecret targeting vici namespace
  affects:
    - infra/__main__.py
    - infra/components/secrets.py
tech_stack:
  added: []
  patterns:
    - Module-import-as-resource-registration pattern (existing)
    - ExternalSecret namespace targeting for app pod access
key_files:
  created: []
  modified:
    - infra/__main__.py
    - infra/components/secrets.py
decisions:
  - "OTEL ExternalSecret namespace changed from observability to vici so app pods can mount the secret directly"
metrics:
  duration: "~5 minutes"
  completed: "2026-04-05"
  tasks_completed: 2
  tasks_total: 2
  files_created: 0
  files_modified: 2
requirements:
  - OBS-05
---

# Phase 04 Plan 03: Pulumi Entry Point Wiring and OTEL Secret Namespace Summary

**One-liner:** Jaeger and Prometheus components wired into infra/__main__.py; OTEL ExternalSecret retargeted to vici namespace so app pods can mount the trace endpoint secret directly.

## What Was Built

### Task 1: Register observability components in __main__.py

Added two import lines to `infra/__main__.py` after the existing temporal import:

```python
from components.jaeger import jaeger_collector_deployment, jaeger_query_deployment  # noqa: F401
from components.prometheus import kube_prometheus_release, fastapi_service_monitor  # noqa: F401
```

Both imports follow the established pattern where module-level execution registers Pulumi resources. All observability resources (Jaeger collector, Jaeger query, kube-prometheus-stack, ServiceMonitor) are now included in `pulumi up`.

### Task 2: Update OTEL ExternalSecret namespace to vici

Updated the `_SECRET_DEFINITIONS` tuple in `infra/components/secrets.py` from:

```python
("otel-exporter-otlp-endpoint", "observability", "otel-exporter-otlp-endpoint"),
```

to:

```python
("otel-exporter-otlp-endpoint", "vici", "otel-exporter-otlp-endpoint"),
```

The ExternalSecret CR now syncs `OTEL_EXPORTER_OTLP_ENDPOINT` from GCP Secret Manager into the `vici` namespace, where the FastAPI app pods run. The operator must populate the GCP secret value (`http://jaeger-collector.observability.svc.cluster.local:4317`) via `gcloud secrets versions add`.

## Task Commits

| Task | Description | Commit |
|------|-------------|--------|
| Task 1 | Register jaeger and prometheus in __main__.py | 55cebe1 |
| Task 2 | Update OTEL ExternalSecret namespace to vici | 60938de |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None. The OTEL endpoint value is a cluster-internal URL (not a credential); this was accepted as T-04-08 in the plan's threat model.

## Self-Check: PASSED

- infra/__main__.py: contains `from components.jaeger import` — VERIFIED
- infra/__main__.py: contains `from components.prometheus import` — VERIFIED
- infra/components/secrets.py: OTEL tuple targets namespace `vici` — VERIFIED
- Both files parse as valid Python: VERIFIED
- Commit 55cebe1: FOUND
- Commit 60938de: FOUND
