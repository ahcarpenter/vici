---
phase: 04-observability-stack
plan: "01"
subsystem: infra/observability
tags: [jaeger, pulumi, kubernetes, observability, tracing]
dependency_graph:
  requires: [opensearch_index_template_job, namespaces.observability]
  provides: [jaeger_collector_deployment, jaeger_query_deployment, jaeger_collector_service, jaeger_query_service]
  affects: [infra/components/jaeger.py]
tech_stack:
  added: [jaeger v2.16.0]
  patterns: [raw K8s Deployments via Pulumi, ConfigMap-mounted config, ClusterIP services]
key_files:
  created: [infra/components/jaeger.py]
  modified: []
decisions:
  - "D-01: Raw K8s Deployments (not Helm chart) for Jaeger v2 unified binary"
  - "D-02: Collector and query configs ported from jaeger/ dir with in-cluster OpenSearch URL"
  - "D-10: Both services ClusterIP-only — no Ingress"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-05"
  tasks_completed: 2
  files_created: 1
  files_modified: 0
---

# Phase 04 Plan 01: Jaeger v2 Collector and Query Component Summary

**One-liner:** Jaeger v2.16.0 collector and query deployed as raw K8s Deployments in the observability namespace, connected to the existing in-cluster OpenSearch instance via ConfigMap-mounted YAML configs.

## What Was Built

`infra/components/jaeger.py` — Pulumi component providing:

- `jaeger_collector_configmap` — ConfigMap with collector OTLP→OpenSearch config
- `jaeger_query_configmap` — ConfigMap with query UI→OpenSearch config
- `jaeger_collector_deployment` — Jaeger collector receiving OTLP on ports 4317 (gRPC) and 4318 (HTTP)
- `jaeger_query_deployment` — Jaeger query UI on port 16686
- `jaeger_collector_service` — ClusterIP Service exposing 4317/4318
- `jaeger_query_service` — ClusterIP Service exposing 16686
- Pulumi exports for both service DNS names

Both Deployments depend on `opensearch_index_template_job` ensuring OpenSearch is ready before Jaeger starts.

## Task Commits

| Task | Description | Commit |
|------|-------------|--------|
| Task 0 | Pre-condition verification (OpenSearch index template confirmed) | N/A (no-op) |
| Task 1 | Create infra/components/jaeger.py | 15ed307 |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

All threat mitigations from the plan's threat model are implemented:

| Flag | File | Description |
|------|------|-------------|
| T-04-01 mitigated | infra/components/jaeger.py | Jaeger query service is ClusterIP-only (no Ingress) |
| T-04-03 mitigated | infra/components/jaeger.py | Collector resource limits set; ClusterIP-only |

## Self-Check: PASSED

- infra/components/jaeger.py: FOUND
- Commit 15ed307: FOUND
- Python syntax check: PASSED
- All 8 K8s resources present: VERIFIED (2 ConfigMaps, 2 Deployments, 2 Services, 2 exports)
- OTLP ports 4317/4318: VERIFIED
- Query port 16686: VERIFIED
- Health probes on port 13133 path /status: VERIFIED
- ClusterIP services: VERIFIED
- depends_on opensearch_index_template_job: VERIFIED
- In-cluster OpenSearch URL: VERIFIED (opensearch-cluster-master.observability.svc.cluster.local:9200)
