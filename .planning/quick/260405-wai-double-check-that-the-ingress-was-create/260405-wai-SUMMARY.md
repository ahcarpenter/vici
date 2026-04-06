---
phase: quick-260405-wai
plan: 01
subsystem: infra
tags: [pulumi, gke, ingress, dns, cert-manager, squarespace]
key-files:
  modified:
    - infra/components/ingress.py
  created:
    - infra/DOMAIN-SETUP.md
decisions:
  - Export ingress_external_ip from load balancer status with PENDING sentinel — avoids error on unprovisioned ingress
  - Export app_hostname alongside IP — single pulumi stack output command surfaces both values for DNS config
tech-stack:
  patterns:
    - Pulumi Output.apply for lazy status extraction from Kubernetes resource status fields
metrics:
  duration: ~5m
  completed: "2026-04-06"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
---

# Quick Task 260405-wai: Ingress IP Export and Domain Setup Runbook Summary

**One-liner:** Pulumi stack export for GKE ingress external IP with PENDING sentinel, plus Squarespace DNS A record runbook covering IP retrieval, DNS propagation, and TLS cert promotion.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add ingress external IP Pulumi export | 277003d | infra/components/ingress.py |
| 2 | Create DOMAIN-SETUP.md runbook | 6682159 | infra/DOMAIN-SETUP.md |

## What Was Built

### Task 1: ingress_external_ip export (infra/components/ingress.py)

Two new exports appended after the existing `ingress_name` and `webhook_base_url` exports:

- `ingress_external_ip` — extracts `status.loadBalancer.ingress[0].ip` via `Output.apply`; returns the string `"PENDING"` if the load balancer has not yet been provisioned by GKE.
- `app_hostname` — surfaces the configured hostname (from `Pulumi.dev.yaml`) alongside the IP for convenient cross-reference.

No existing exports or resource definitions were modified.

### Task 2: DOMAIN-SETUP.md runbook (infra/DOMAIN-SETUP.md)

Complete step-by-step runbook covering:

1. **Prerequisites** — stack healthy, ingress not pending, cert-manager issuers deployed
2. **Retrieve the Ingress IP** — `pulumi stack output ingress_external_ip` and fallback kubectl command
3. **Configure Squarespace DNS** — exact Custom Records UI path, A record values (Host, Type, Data, TTL), apex domain note
4. **Verify DNS Propagation** — `dig`, `nslookup`, and `curl -I` commands with expected outputs
5. **TLS Certificate** — staging-to-production issuer promotion steps including annotation change, `pulumi up`, certificate delete for re-issue, and readiness verification
6. **Troubleshooting** — table of common failure symptoms, likely causes, and remediation actions

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- infra/components/ingress.py: `ingress_external_ip` and `app_hostname` exports confirmed via AST parse
- infra/DOMAIN-SETUP.md: file exists, contains required sections (pulumi stack output, Squarespace, letsencrypt-prod)
- Commit 277003d: FOUND in gks-refactor branch
- Commit 6682159: FOUND in gks-refactor branch
