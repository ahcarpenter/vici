---
created: 2026-04-03T05:28:41.352Z
title: Integrate Grafana Loki, Alloy, and Tempo for observability
area: tooling
files: []
---

## Problem

The project lacks a unified observability stack for logs, traces, and metrics. As the system grows (Temporal workflows, FastAPI services, webhooks), debugging production issues requires structured log aggregation, distributed tracing, and correlation across services.

## Solution

Leverage the Grafana OSS observability stack:
- **Loki** (https://github.com/grafana/loki) — log aggregation, queryable via LogQL
- **Alloy** (Grafana Alloy) — OpenTelemetry-native collector replacing Promtail/Agent; ships logs to Loki and traces to Tempo
- **Tempo** — distributed tracing backend, correlates with Loki logs via trace IDs

Integration approach:
1. Instrument FastAPI with OpenTelemetry SDK (traces + structured logs)
2. Deploy Alloy as collector sidecar/agent to scrape and forward telemetry
3. Configure Loki for log storage and Tempo for trace storage
4. Wire up Grafana dashboards for unified observability (logs ↔ traces correlation)
