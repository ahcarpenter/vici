# Phase 3: Temporal In-Cluster - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-04
**Phase:** 03-temporal-in-cluster
**Mode:** assumptions
**Areas analyzed:** Temporal Helm Deployment, OpenSearch Deployment, Schema Migration, Temporal UI, Pulumi Component Structure

## Assumptions Presented

### Temporal Helm Deployment
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Deploy via temporalio/helm-charts, new temporal.py component | Confident | infra/components/database.py, infra/components/iam.py (temporal resources already provisioned) |
| Disable all bundled chart dependencies | Confident | research/ARCHITECTURE.md §"Temporal Server: Official Helm Chart" |
| postgres12 driver for both default + visibility stores | Confident | REQUIREMENTS.md TEMPORAL-01, database.py exports |
| Auth Proxy native sidecar pattern for Temporal pods | Confident | infra/components/migration.py (established pattern) |
| numHistoryShards: 512 | Confident | research/ARCHITECTURE.md (512 for low-to-medium throughput) |

### OpenSearch Deployment
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Self-host OpenSearch in observability namespace | Unclear | CONFLICT: TEMPORAL-02 requires OpenSearch; ARCHITECTURE.md advises against self-hosting in Autopilot |
| Deploy with number_of_replicas: 0 | Confident | REQUIREMENTS.md OBS-01 |
| OpenSearch deployed before Temporal (depends_on) | Confident | REQUIREMENTS.md TEMPORAL-03 |

### Schema Migration
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Dedicated K8s Job with Auth Proxy sidecar, temporalio/admin-tools image | Confident | REQUIREMENTS.md TEMPORAL-04, migration.py pattern |
| Run in temporal namespace under temporal-app KSA | Confident | infra/components/iam.py (temporal_app_ksa already exists) |

### Temporal UI
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| ClusterIP-only in Phase 3, Ingress deferred to Phase 5 | Likely | REQUIREMENTS.md TEMPORAL-06 ("optionally exposed via Ingress") |

## Corrections Made

### OpenSearch Deployment
- **Original assumption:** Unclear — conflict between TEMPORAL-02 (requires OpenSearch) and ARCHITECTURE.md (advises against self-hosting in Autopilot)
- **User correction:** Option A — Self-host OpenSearch in `observability` namespace, deploy in Phase 3 ahead of Jaeger, Temporal and Phase 4 Jaeger share the same instance
- **Reason:** Follow TEMPORAL-02/03 as written; accept Autopilot complexity for consistency
