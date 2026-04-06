---
phase: 05-application-deployment-and-ci-cd
plan: 02
subsystem: infra
tags: [kubernetes, cert-manager, ingress, tls, gke, pulumi, let-s-encrypt, gcp-secret-manager]
dependency_graph:
  requires:
    - infra/components/certmanager.py
    - infra/components/app.py (app_service)
    - infra/components/namespaces.py (k8s_provider, namespaces)
    - infra/config.py (APP_HOSTNAME, ENV, PROJECT_ID)
  provides:
    - infra/components/certmanager.py (certmanager_release)
    - infra/components/ingress.py (staging_issuer, prod_issuer, vici_ingress, webhook_base_url_version)
  affects:
    - infra/__main__.py (must import certmanager.py and ingress.py)
    - GCP Secret Manager (webhook-base-url SecretVersion written)
tech_stack:
  added:
    - k8s.helm.v3.Release (cert-manager v1.20.0 with CRDs)
    - k8s.apiextensions.CustomResource (Issuer CRs — namespace-scoped, not ClusterIssuer)
    - k8s.core.v1.Secret (placeholder TLS Secret for chicken-and-egg workaround)
    - k8s.networking.v1.Ingress (GKE Ingress with annotation-based class)
    - gcp.secretmanager.SecretVersion (WEBHOOK_BASE_URL value write)
  patterns:
    - Placeholder TLS Secret before cert-manager manages it (GKE chicken-and-egg fix)
    - Namespace-scoped Issuer (not ClusterIssuer) consistent with SecretStore pattern
    - Staging issuer default with prod issuer coexisting (D-14 rate limit protection)
    - Ingress annotation class over ingressClassName field (GKE Autopilot reliability)
    - app_service in Ingress depends_on for correct Pulumi resource ordering
key_files:
  created:
    - infra/components/certmanager.py
    - infra/components/ingress.py
  modified: []
decisions:
  - "Placeholder TLS Secret (empty tls.crt/tls.key) required — GKE Ingress refuses to accept TLS config referencing a nonexistent secret, preventing cert-manager from receiving the HTTP-01 challenge"
  - "Staging issuer annotated on Ingress by default per D-14 — switch to letsencrypt-prod annotation post-verification to avoid 50 cert/week rate limit"
  - "Both letsencrypt-staging and letsencrypt-prod Issuers created together — coexistence allows operator to switch without re-running pulumi up for issuer creation"
  - "ingressClassName field omitted entirely — GKE Autopilot requires kubernetes.io/ingress.class annotation for reliable GCE load balancer provisioning"
  - "webhook_base_url_version depends_on vici_ingress — ensures Ingress (and thus the external IP) is provisioned before writing the secret value"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-06"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
---

# Phase 05 Plan 02: cert-manager + GKE Ingress + TLS Summary

**One-liner:** cert-manager Helm release (v1.20.0, CRDs enabled) plus GKE Ingress with staging/prod Let's Encrypt Issuers (namespace-scoped), placeholder TLS Secret for chicken-and-egg workaround, and WEBHOOK_BASE_URL SecretVersion write to GCP Secret Manager.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create infra/components/certmanager.py -- cert-manager Helm release | f61c976 | infra/components/certmanager.py (created) |
| 2 | Create infra/components/ingress.py -- Issuers + placeholder TLS Secret + GKE Ingress + WEBHOOK_BASE_URL SecretVersion | d3f483b | infra/components/ingress.py (created) |

## What Was Built

### Task 1: infra/components/certmanager.py

Created the cert-manager Pulumi component:

**Helm Release (`cert-manager`):**
- Chart: `cert-manager` v1.20.0 from `https://charts.jetstack.io`
- Deployed to `cert-manager` namespace (`create_namespace=False` — namespace exists from Phase 1)
- CRDs enabled via `values.crds.enabled=True` — required before Issuer/Certificate CRs can be created
- `depends_on`: `namespaces["cert-manager"]` — ensures namespace API server readiness
- Exports `certmanager_chart_version` stack output

### Task 2: infra/components/ingress.py

Created the ingress Pulumi component with four resources:

**Staging Issuer (`letsencrypt-staging`):**
- Namespace-scoped `cert-manager.io/v1 Issuer` in `vici` namespace (D-13 — not ClusterIssuer)
- ACME server: `https://acme-staging-v02.api.letsencrypt.org/directory`
- HTTP-01 solver via GCE ingress class
- `depends_on`: `certmanager_release`, `namespaces["vici"]` — CRDs must be installed first

**Production Issuer (`letsencrypt-prod`):**
- Coexists with staging per D-14 (no pulumi up needed when switching)
- ACME server: `https://acme-v02.api.letsencrypt.org/directory`
- Same HTTP-01 solver and dependency chain as staging issuer

**Placeholder TLS Secret (`vici-tls`):**
- `kubernetes.io/tls` type Secret with empty `tls.crt` and `tls.key`
- Resolves GKE Ingress chicken-and-egg: GKE Ingress controller rejects TLS config referencing a nonexistent secret, which would prevent cert-manager from receiving the ACME HTTP-01 challenge
- `depends_on`: `namespaces["vici"]`

**GKE Ingress (`vici-ingress`):**
- Annotations: `kubernetes.io/ingress.class: gce`, `kubernetes.io/ingress.allow-http: "true"`, `cert-manager.io/issuer: letsencrypt-staging`
- `ingressClassName` field intentionally omitted — annotation is more reliable on GKE Autopilot
- HTTP allowed for ACME HTTP-01 challenge flow
- TLS: secret_name=`vici-tls`, hosts=[`APP_HOSTNAME`]
- Rule: host=`APP_HOSTNAME`, path="/", pathType=Prefix, backend=`vici-app:http`
- `depends_on`: `tls_secret_placeholder`, `staging_issuer`, `prod_issuer`, `app_service` — correct Pulumi ordering with backend Service guaranteed present

**WEBHOOK_BASE_URL SecretVersion:**
- `gcp.secretmanager.SecretVersion` writing `https://{APP_HOSTNAME}` to GCP Secret Manager
- Target secret: `projects/{PROJECT_ID}/secrets/{ENV}-webhook-base-url` (Secret resource created in Phase 2 `secrets.py`)
- `depends_on`: `vici_ingress` — Ingress must be provisioned before writing value
- When operator updates DNS in Squarespace to point `app_hostname` to GKE Ingress IP, re-running `pulumi up` automatically updates this secret version

**Exports:**
- `ingress_name`: Pulumi Output of `vici-ingress.metadata.name`
- `webhook_base_url`: Static `https://{APP_HOSTNAME}` string

## Deviations from Plan

None — plan executed exactly as written.

## Threat Mitigation Coverage

All five threats from the plan's STRIDE register are addressed:

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-05-06 | cert-manager provisions TLS certs from Let's Encrypt CA via HTTP-01 ACME challenge | Implemented |
| T-05-07 | Single Ingress rule routes only to vici-app; no other backends exposed (D-03) | Implemented |
| T-05-08 | Temporal UI, Grafana, Jaeger remain ClusterIP-only — no Ingress rules for observability | Implemented (by omission) |
| T-05-09 | Staging issuer default avoids 50 cert/week prod rate limit; switch to prod post-verify | Implemented |
| T-05-16 | WEBHOOK_BASE_URL derived from stack config `app_hostname`; only Pulumi SA can write SecretVersions | Implemented |

## Known Stubs

None — all values are wired from actual Pulumi stack config outputs (`APP_HOSTNAME`, `ENV`, `PROJECT_ID`).

## Threat Flags

None — no new security surface introduced beyond what the plan's threat model covers.

## Self-Check: PASSED

- [x] `infra/components/certmanager.py` exists
- [x] `infra/components/ingress.py` exists
- [x] Commit f61c976 verified in git log
- [x] Commit d3f483b verified in git log
- [x] ruff check passes for both files (0 errors)
- [x] Python syntax OK for both files
- [x] No `ClusterIssuer` in ingress.py
- [x] No `ingressClassName` field in ingress spec (comment only)
- [x] `letsencrypt-staging` appears 4 times (Issuer name x2, annotation x1, privateKeySecretRef x1)
- [x] `app_service` appears 3 times (import x1, comment x1, depends_on x1)
- [x] `SecretVersion` appears 2 times (class reference x1, resource name x1)
- [x] All module-level constants defined with underscore prefix
- [x] Placeholder TLS Secret with empty tls.crt/tls.key present
- [x] Both issuers depend on certmanager_release (CRDs must exist first)
