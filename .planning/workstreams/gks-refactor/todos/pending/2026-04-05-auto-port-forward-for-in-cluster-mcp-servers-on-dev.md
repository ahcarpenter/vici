---
created: "2026-04-05T22:57:00.870Z"
title: Auto port-forward for in-cluster MCP servers on dev
area: tooling
files:
  - .planning/quick/260405-oux-install-mcp-servers-and-claude-skills-fo/IN-CLUSTER-MCP-SETUP.md
  - .claude/skills/temporal/SKILL.md
---

## Problem

Three MCP servers (Grafana, Temporal, OpenTelemetry/Jaeger) connect to in-cluster GKE services and require active `kubectl port-forward` sessions to function. Currently the user must manually start 5 port-forwards each session:

```bash
kubectl port-forward svc/kube-prometheus-stack-ac828b0c-grafana 3000:80 -n observability
kubectl port-forward svc/temporal-5b5cac0f-frontend 7233:7233 -n temporal
kubectl port-forward svc/temporal-5b5cac0f-web 8233:8080 -n temporal
kubectl port-forward svc/jaeger-query 16686:16686 -n observability
kubectl port-forward svc/jaeger-collector 4318:4318 -n observability
```

When a user invokes a Temporal, Grafana, or OTEL MCP tool/skill against the dev cluster, the port-forward should be detected or started automatically rather than requiring manual setup.

## Solution

Create a debug/dev setup script or Claude Code hook that:

1. Detects when an in-cluster MCP tool is invoked (e.g., `mcp__temporal__*`, `mcp__grafana__*`, `mcp__opentelemetry__*`)
2. Checks if the required port-forward is already running (`lsof -i :PORT` or `ss -tlnp`)
3. If not running, automatically starts the port-forward in the background
4. Handles service name discovery dynamically (service names include Helm release hashes that change on upgrades)

Possible approaches:
- **Claude Code PreToolUse hook**: Trigger on MCP tool matcher, check/start port-forwards before the tool executes
- **Shell script** (`scripts/dev-port-forward.sh`): Source from `.zshrc` or run manually, manages all port-forwards with health checks
- **Combination**: Hook calls the shell script, script handles the actual port-forward lifecycle

Service name discovery could use label selectors instead of hardcoded names:
```bash
kubectl get svc -n temporal -l app.kubernetes.io/component=frontend -o name
kubectl get svc -n observability -l app.kubernetes.io/name=grafana -o name
```
