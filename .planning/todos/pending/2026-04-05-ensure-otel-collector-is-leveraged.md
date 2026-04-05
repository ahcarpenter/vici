---
created: 2026-04-05T09:29:25.262Z
title: Ensure OTel Collector is leveraged
area: tooling
files: []
---

## Problem

The current GKE observability stack (Phase 4) deploys Jaeger v2 directly as the trace receiver. An OpenTelemetry Collector in front of the trace pipeline would provide a vendor-neutral ingestion layer, enabling future flexibility (e.g., switching backends, adding processors, sampling, multi-destination fanout) without changing application instrumentation.

## Solution

Evaluate deploying an OTel Collector (Deployment or DaemonSet) in the `observability` namespace as the primary OTLP endpoint. The collector would receive traces from the FastAPI app and forward them to Jaeger/OpenSearch. This decouples the application's `OTEL_EXPORTER_OTLP_ENDPOINT` from the specific backend, aligning with OpenTelemetry best practices.

TBD — assess whether this belongs in Phase 4 (Observability Stack) or as a post-v1.0 improvement.
