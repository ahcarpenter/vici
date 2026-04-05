---
phase: quick-260405-oux
plan: 01
subsystem: tooling
tags: [mcp, claude-skills, temporal, pinecone, kubernetes, docker, github]
dependency_graph:
  requires: []
  provides: [mcp-servers, temporal-skill, pinecone-skill]
  affects: [claude-code-capabilities, developer-experience]
tech_stack:
  added: [github-mcp, kubernetes-mcp, docker-mcp, pulumi-mcp, grafana-mcp, temporal-mcp, otel-mcp, pinecone-mcp]
  patterns: [claude-skills, mcp-server-config]
key_files:
  created:
    - .claude/skills/temporal/SKILL.md
    - .claude/skills/temporal/rules/workflows.md
    - .claude/skills/temporal/rules/activities.md
    - .claude/skills/pinecone/SKILL.md
    - .claude/skills/pinecone/rules/data-formats.md
    - .planning/quick/260405-oux-install-mcp-servers-and-claude-skills-fo/IN-CLUSTER-MCP-SETUP.md
  modified:
    - ~/.mcp.json
    - ~/.claude.json
    - .gitignore
decisions:
  - "Fixed Pinecone MCP package from @anthropic/pinecone-mcp to @pinecone-database/mcp (correct npm package)"
  - "Added .claude/skills/ exception to .gitignore so skills are version-controlled"
  - "Installed Pinecone as a skill (SKILL.md + rules/) rather than plugin since MCP server already configured"
metrics:
  duration_seconds: 1542
  completed: "2026-04-05T22:34:00Z"
  tasks_completed: 3
  tasks_total: 3
---

# Quick Task 260405-oux: Install MCP Servers and Claude Skills Summary

MCP server configs verified/fixed across global and project scopes; Temporal and Pinecone Claude skills installed with vici-specific patterns; in-cluster activation reference created.

## Tasks Completed

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Install global and project-scoped MCP servers | (config-only, no repo commit) | ~/.mcp.json, ~/.claude.json |
| 2 | Install Temporal and Pinecone Claude skills | 36bb220 | .claude/skills/temporal/*, .claude/skills/pinecone/*, .gitignore |
| 3 | Create in-cluster MCP setup documentation | 7ead7a1 | IN-CLUSTER-MCP-SETUP.md |

## What Was Done

### Task 1: MCP Server Configuration

Both `~/.mcp.json` (global) and `~/.claude.json` (project) already had all 8 MCP servers configured from a previous partial execution. The only fix needed was correcting the Pinecone MCP package name from `@anthropic/pinecone-mcp` (incorrect) to `@pinecone-database/mcp` (correct npm package per npm registry).

**Final state:**
- Global (5): gcloud, storage, github, kubernetes, docker
- Project vici (6): render, pulumi, grafana, temporal, opentelemetry, pinecone

### Task 2: Claude Skills

Created Temporal skill tailored to vici project patterns:
- `SKILL.md`: 50-line index covering project context, conventions, quick rules
- `rules/workflows.md`: Determinism constraints, timeout rules, signals/queries, cron patterns, versioning, testing
- `rules/activities.md`: Idempotency rules, retry policies, heartbeats, app.state DI pattern, testing

Installed Pinecone skill from official plugin repo:
- `SKILL.md`: Pinecone docs skill (from pinecone-io/pinecone-claude-code-plugin)
- `rules/data-formats.md`: Data format reference

Added `.claude/skills/` exception to `.gitignore` so skills are version-controlled.

### Task 3: In-Cluster MCP Setup Reference

Created operational reference with port-forward commands for Grafana, Temporal, and Jaeger/OTEL, plus cloud API env var requirements table.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed Pinecone MCP package name**
- **Found during:** Task 1
- **Issue:** Plan specified `@anthropic/pinecone-mcp` but correct npm package is `@pinecone-database/mcp`
- **Fix:** Updated ~/.claude.json with correct package name
- **Files modified:** ~/.claude.json

**2. [Rule 3 - Blocking] Added .gitignore exception for .claude/skills/**
- **Found during:** Task 2
- **Issue:** `.claude/` was gitignored, preventing skill files from being committed
- **Fix:** Added `!.claude/skills/` exception to `.gitignore`
- **Files modified:** .gitignore
- **Commit:** 36bb220

**3. [Rule 2 - Adaptation] Pinecone installed as skill instead of plugin**
- **Found during:** Task 2
- **Issue:** Pinecone repo is a Claude Code plugin but plugin install requires `/plugin install` CLI command not available in this context. MCP server already configured separately.
- **Fix:** Installed Pinecone docs/references as a skill under `.claude/skills/pinecone/` for Claude Code skill discovery
- **Files modified:** .claude/skills/pinecone/SKILL.md, .claude/skills/pinecone/rules/data-formats.md

## Self-Check: PASSED

All 6 created files verified on disk. Both commits (36bb220, 7ead7a1) verified in git log.
