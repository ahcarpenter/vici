---
phase: quick-260406-0zi
plan: "01"
subsystem: infra
tags: [cert-manager, tls, kubernetes, ingress, gke]
dependency_graph:
  requires: []
  provides: [tls-certificate-issuance, https-endpoint]
  affects: [dev.usevici.com, ingress]
tech_stack:
  added: []
  patterns: [kubectl-manual-cleanup, pulumi-targeted-deploy]
key_files:
  created: []
  modified: [infra/components/ingress.py]
decisions:
  - "Deleted stale cert-manager-4d0776c0-webhook and cert-manager-d160d62d-webhook MutatingWebhookConfigurations"
  - "Changed Issuer solver from ingress.class:gce to ingress.name:vici-ingress to prevent separate LB creation"
  - "Used self-signed placeholder cert to break GKE ingress sync chicken-and-egg"
  - "Switched from letsencrypt-staging to letsencrypt-prod after staging verification"
metrics:
  duration: "20 minutes"
  completed_date: "2026-04-06"
  tasks_completed: 1
  files_changed: 1
---

# Quick Task 260406-0zi: Redeploy Dev — Fix TLS & HTTPS Summary

**One-liner:** Fixed HTTPS for dev.usevici.com by cleaning up stale cert-manager webhooks, fixing ACME solver IP mismatch (ingress.class→ingress.name), resolving GKE ingress sync chicken-and-egg, and issuing production Let's Encrypt certificate.

## What Was Done

### Issue 1: Stale cert-manager webhooks

Three MutatingWebhookConfigurations existed from different Helm releases. Two stale ones (`4d0776c0`, `d160d62d`) intercepted CertificateRequest creation and called non-existent services. Deleted both, leaving only `554d5588`.

### Issue 2: ACME solver IP mismatch

Both Issuers used `ingress.class: gce` which caused cert-manager to create a **separate** GCE ingress with its own load balancer IP for the HTTP-01 challenge. Since DNS pointed to the main ingress IP (34.120.195.235), Let's Encrypt couldn't reach the solver.

**Fix:** Changed both staging and prod Issuers to use `ingress.name: vici-ingress` so cert-manager adds the challenge path directly to the existing ingress.

### Issue 3: GKE ingress sync chicken-and-egg

GKE's ingress controller refused to sync the URL map when the TLS secret was missing/had empty data — blocking HTTPS load balancer creation entirely. But cert-manager needed the LB to serve the ACME challenge to populate the TLS secret.

**Fix:** Created a self-signed placeholder TLS secret to unblock GKE sync, then cert-manager replaced it with the real Let's Encrypt cert after the challenge succeeded.

### Issue 4: Staging → Production

After confirming staging cert worked, updated the ingress annotation from `letsencrypt-staging` to `letsencrypt-prod` and re-issued.

## Files Changed

- `infra/components/ingress.py` — Changed Issuer solver config from `{"class": "gce"}` to `{"name": "vici-ingress"}` for both issuers; switched ingress annotation to `letsencrypt-prod`

## Verification

```
$ curl -s https://dev.usevici.com/health
{"status":"ok"}

$ openssl s_client -connect dev.usevici.com:443 | openssl x509 -noout -issuer
issuer=C=US, O=Let's Encrypt, CN=R13

Certificate valid: Apr 6 2026 – Jul 5 2026
```

## Deviations from Plan

The original plan only addressed stale webhooks (Issue 1). Issues 2-4 were discovered during execution:
- ACME solver creating separate LB was the root cause of persistent 404s
- GKE sync failure required self-signed placeholder workaround
- Production cert issuance was added as a natural follow-through

## Threat Flags

None — no new network endpoints, auth paths, or schema changes. Only fixed existing TLS configuration.
