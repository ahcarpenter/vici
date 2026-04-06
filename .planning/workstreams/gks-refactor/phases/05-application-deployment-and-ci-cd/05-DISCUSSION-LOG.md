# Phase 5: Application Deployment and CI/CD - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 05-application-deployment-and-ci-cd
**Areas discussed:** Hostname & DNS convention, CI/CD pipeline design, cert-manager deployment, App Deployment shape

---

## Hostname & DNS Convention

| Option | Description | Selected |
|--------|-------------|----------|
| Subdomain per env | dev.vici.app, staging.vici.app, vici.app. Clean, conventional. | |
| GKE auto-assigned IPs only | No custom domains for v1. Raw IP only, no TLS. | |
| Custom per env | User specifies their own scheme. | |

**User's choice:** Use purchased domain usevici.com with subdomains per env. DNS configuration in Squarespace required.
**Notes:** User purchased usevici.com on Squarespace. Domain is now real; DNS configuration in Squarespace required before Phase 5 execution.

### UI Ingress Scope

| Option | Description | Selected |
|--------|-------------|----------|
| FastAPI app only | Only app gets public Ingress. Operators use kubectl port-forward. | |
| Grafana | Expose on subdomain. | |
| Temporal UI | Expose on subdomain. | |
| Jaeger UI | Expose on subdomain. | |

**User's choice:** FastAPI app only for now. All internal UIs (Grafana, Temporal UI, Jaeger) must NOT be exposed until authentication is in place for each. Create a todo for exposing them with auth.
**Notes:** Security-first approach — no unauthenticated dashboards on the public internet.

---

## CI/CD Pipeline Design

### Workflow Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Single cd.yml | One workflow file with jobs. CI stays separate. | |
| Per-env workflows | Separate cd-dev.yml, cd-staging.yml, cd-prod.yml. More isolation. | |
| Unified ci-cd.yml | Merge CI tests + CD deploy into one file. | |

**User's choice:** Per-env workflows (`cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`) that call a shared reusable workflow (`cd-base.yml`) to stay DRY.
**Notes:** User values DRY — wants the per-env isolation but with a shared base to avoid duplication.

### Image Tagging

| Option | Description | Selected |
|--------|-------------|----------|
| Git SHA + env tag | Tag with short SHA + env name. SHA for traceability, env for latest. | |
| Semver from tags | Only build on git tags (v1.0.0). | |
| SHA only | Just git SHA tags. Simple. | |

**User's choice:** Git SHA + env tag for v1. Add a todo for semver tagging from git tags as a future enhancement.
**Notes:** None.

### GCP Auth

| Option | Description | Selected |
|--------|-------------|----------|
| Workload Identity Federation | GitHub OIDC -> GCP WIF. No static keys. | |
| Service account key in secrets | Traditional approach — store a GCP SA key as GitHub secret. | |

**User's choice:** Workload Identity Federation (OIDC). Per CD-04 requirement.
**Notes:** None.

---

## cert-manager Deployment

### Issuer Scope

| Option | Description | Selected |
|--------|-------------|----------|
| ClusterIssuer | Single ClusterIssuer for Let's Encrypt. Any namespace can request certs. | |
| Namespace-scoped Issuer | One Issuer per namespace. Stricter RBAC alignment. | |

**User's choice:** Namespace-scoped Issuer — consistent with namespace-scoped SecretStore pattern from Phase 2.
**Notes:** Pattern consistency valued over convenience.

### Let's Encrypt Environment

| Option | Description | Selected |
|--------|-------------|----------|
| Staging first, prod when ready | LE staging to avoid rate limits during testing. Switch to prod when verified. | |
| Production only | Go straight to LE production. | |

**User's choice:** Staging first, switch to production when Ingress is verified working.
**Notes:** None.

---

## App Deployment Shape

### Env Injection

| Option | Description | Selected |
|--------|-------------|----------|
| envFrom per secret | Multiple envFrom refs, one per ExternalSecret. Matches migration.py pattern. | |
| Single merged secret | One combined K8s Secret. Fewer envFrom but diverges from existing pattern. | |

**User's choice:** envFrom per secret — matches existing pattern.
**Notes:** None.

### Component Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Single app.py | One file with Deployment + Service + HPA + ServiceMonitor. | |
| Split: app.py + ingress.py | Separate networking concerns. | |
| Split: app.py + ingress.py + cd.py | Three files for three concerns. | |

**User's choice:** Split into three files: `app.py` (workload), `ingress.py` (networking + TLS), `cd.py` (WIF + CI/CD GCP resources).
**Notes:** User prefers clean separation of concerns.

---

## Claude's Discretion

- cert-manager Helm chart version
- Readiness/liveness probe configuration
- Resource requests/limits for FastAPI pods
- GCP WIF pool and provider naming
- Reusable workflow input parameters
- Temporal dashboard provisioning in Grafana

## Deferred Ideas

- Expose Temporal UI, Grafana, Jaeger UI with authentication — todo
- Semver image tagging from git tags — todo
- Auto port-forward for in-cluster MCP servers on dev — existing backlog item, not folded
- Custom domain DNS configuration (usevici.com) — purchased on Squarespace, configure DNS to point to GKE Ingress IPs after first pulumi up
