# GKS Refactor Research Summary

**Workstream:** gks-refactor
**Synthesized:** 2026-04-04
**Source files:** `.planning/research/STACK.md`, `FEATURES.md`, `ARCHITECTURE.md`, `PITFALLS.md` + `.planning/codebase/` docs
**Confidence:** MEDIUM — existing research files describe the Render/Inngest-era architecture; the codebase docs reflect the current Temporal-based system. GKS-specific tooling (Pulumi, Cloud SQL Auth Proxy, ESO, GKE Autopilot) draws on established community patterns, not yet validated against this specific codebase.

---

## Executive Summary

Vici is a Python/FastAPI SMS job-matching service currently deployed on Render.com with a managed PostgreSQL instance. The application uses Temporal for workflow orchestration (replacing Inngest in Phase 02.9), a 5-gate Twilio webhook security chain, GPT for SMS classification and structured extraction, Pinecone for vector embeddings, and a full observability stack (OTel → Jaeger v2 on OpenSearch, Prometheus, Grafana). The codebase is containerized with a multi-stage Dockerfile and tested via GitHub Actions CI. The production deployment is a single Render web service + PostgreSQL basic-256mb instance, defined in `render.yaml`.

The GKS refactor migrates this production deployment from Render.com to Google Kubernetes Engine (GKE) Autopilot, with Pulumi (Python) as the IaC layer. The refactor introduces several new infrastructure concerns: Cloud SQL (PostgreSQL managed by Google) with the Cloud SQL Auth Proxy sidecar pattern for in-cluster database connectivity, External Secrets Operator (ESO) for secrets injection from GCP Secret Manager, a namespace-per-environment layout, and Temporal Server running in-cluster (replacing the local dev-only Temporal in Docker Compose with a production-grade deployment). The migration must preserve all existing observability integrations and not alter application code beyond configuration.

The most significant risks are: (1) Pulumi's GKE cluster resource replacing the entire cluster on `dns_config` or node pool changes — requiring careful `ignoreChanges` guards on volatile fields; (2) the Cloud SQL Auth Proxy native sidecar pattern is the recommended approach for GKE but requires the Cloud SQL Admin API to be enabled and Workload Identity configured correctly before the app pod starts; (3) Temporal's recommended Elasticsearch/OpenSearch dependency for visibility — in this architecture the existing OpenSearch instance can serve dual duty but must be provisioned before Temporal's `temporal-server` init container completes; (4) ESO's `ClusterSecretStore` vs namespace-scoped `SecretStore` and the bootstrap ordering problem (ESO must be installed before any `ExternalSecret` CR is applied, which affects Helm chart installation order).

---

## Key Findings

### Stack Additions for GKS

The application stack itself does not change. The following infrastructure tooling is added:

| Tool | Version/Source | Purpose | Rationale |
|------|---------------|---------|-----------|
| Pulumi (Python SDK) | `>=3.x` | IaC for GKE cluster, Cloud SQL, namespaces, Helm releases | Python-native IaC; avoids HCL context switching; integrates with existing Python toolchain. Alternative (Terraform) is viable but requires a separate language and state backend configuration. |
| GKE Autopilot | GCP-managed | Kubernetes cluster mode | Autopilot eliminates node pool management, auto-provisions nodes for pod resource requests, and reduces operational overhead vs. Standard mode. Trade-off: less control over node machine types; not suitable if GPU or specialty hardware is required. |
| Cloud SQL (PostgreSQL 16) | GCP-managed | Managed PostgreSQL | Direct replacement for Render PostgreSQL; private IP in the same VPC as the GKE cluster. Version must match current Render instance (postgres:16). |
| Cloud SQL Auth Proxy | `cloud-sql-proxy:2.x` (native sidecar) | Secure DB connectivity from pods | GKE-native sidecar injection pattern eliminates the need to run the proxy as a separate container per deployment; requires the Cloud SQL API and Workload Identity on the node SA. |
| External Secrets Operator (ESO) | Helm `external-secrets/external-secrets` | Secrets sync from GCP Secret Manager to Kubernetes Secrets | Decouples secret rotation from pod restarts; avoids storing secrets in Pulumi state or git. Must be installed before `ExternalSecret` CRs are applied. |
| Temporal Server | Helm `temporaltech/temporal` | In-cluster workflow server | Replaces local dev Temporal; production Temporal requires a DB backend (PostgreSQL or Cassandra) and optionally Elasticsearch/OpenSearch for workflow visibility search. |
| cert-manager | Helm `cert-manager/cert-manager` | TLS certificate provisioning | Required for Ingress TLS termination; integrates with Let's Encrypt or GCP-managed certs. |
| Ingress-NGINX (or GKE Ingress) | Helm `ingress-nginx/ingress-nginx` | HTTP ingress for the FastAPI app | GKE Autopilot supports both GKE Ingress (GCP Load Balancer) and NGINX ingress. GKE Ingress is simpler for Autopilot; NGINX gives more control over routing. Decision needed before Phase 1 planning. |

**Critical version note:** Pulumi GCP provider `>= 7.x` is required for the Cloud SQL Auth Proxy native sidecar annotation support (`cloud.google.com/sql-instance`). Confirm provider version before writing IaC.

### Features: What Changes and What Stays

The GKS refactor is purely infrastructure — no application feature changes. What maps across:

| Existing Feature | Render Target | GKS Target | Migration Concern |
|-----------------|--------------|-----------|-------------------|
| FastAPI app | Render web service | Kubernetes Deployment in `vici` namespace | Environment variables from ESO ExternalSecrets; resource requests required for Autopilot |
| PostgreSQL 16 | Render managed PostgreSQL | Cloud SQL (private IP) + Auth Proxy sidecar | Connection string changes from direct TCP to proxy socket; must update `DATABASE_URL` secret |
| Temporal worker | Same pod as app (lifespan task) | Same pod, connects to in-cluster Temporal server | `TEMPORAL_HOST` env var changes from `temporal:7233` (compose) to `temporal-frontend.temporal.svc.cluster.local:7233` |
| Twilio webhook | Render public URL | GKE Ingress public IP | Update Twilio webhook URL in Twilio console post-deploy; TLS required (Twilio rejects HTTP) |
| OTel → Jaeger v2 (OpenSearch) | Docker Compose local | Kubernetes Deployment in `observability` namespace | `OTEL_EXPORTER_OTLP_ENDPOINT` points to in-cluster Jaeger collector service |
| Prometheus + Grafana | Docker Compose local | Helm `kube-prometheus-stack` in `observability` namespace | ServiceMonitor CRs for the FastAPI app and Temporal |
| Pinecone | External SaaS | External SaaS (unchanged) | API key injected via ESO |
| OpenAI / Braintrust | External SaaS | External SaaS (unchanged) | API keys injected via ESO |
| GitHub Actions CI | SQLite tests, ruff | Add: image push to GCR, Pulumi preview on PR | Requires GCP service account credentials in GitHub secrets |

**Features deferred to post-GKS (v2+):** Semantic matching (Pinecone), web dashboard, multi-turn conversation — unchanged by this refactor.

### Architecture Decisions

#### Namespace Layout

Recommended namespace structure:

```
vici          — application workloads (FastAPI app Deployment, ExternalSecrets)
temporal      — Temporal server + UI + database migration job
observability — Jaeger, OpenSearch, Prometheus, Grafana
cert-manager  — cert-manager controller
external-secrets — ESO controller
ingress-nginx — (optional) NGINX ingress controller
```

Rationale: separation by concern allows RBAC scoping per namespace. Temporal is isolated so its PostgreSQL dependency (either a separate Cloud SQL database or a database within the same Cloud SQL instance) can be managed independently.

#### Pulumi Stack Structure

Recommended Pulumi project layout:

```
infra/
├── __main__.py           # Entry point — composes stack resources
├── cluster.py            # GKE Autopilot cluster resource
├── sql.py                # Cloud SQL instance + databases + users
├── namespaces.py         # Kubernetes namespace resources
├── eso.py                # ESO Helm release + ClusterSecretStore
├── temporal.py           # Temporal Helm release + config
├── observability.py      # Jaeger, OpenSearch, Prometheus, Grafana Helm releases
├── app.py                # Vici app Deployment + Service + Ingress + ExternalSecrets
└── Pulumi.yaml           # Project config
```

State backend: GCS bucket (recommended over local state for team use). One Pulumi stack per environment (`dev`, `staging`, `prod`).

#### Cloud SQL Auth Proxy Native Sidecar Pattern

GKE Autopilot supports the Cloud SQL Auth Proxy as a native sidecar (GKE 1.29+). The recommended pattern is to annotate the Pod spec rather than add a sidecar container manually:

```yaml
metadata:
  annotations:
    cloud.google.com/sql-instance: "PROJECT:REGION:INSTANCE_NAME"
```

This requires:
1. Cloud SQL Admin API enabled on the GCP project
2. Workload Identity configured on the GKE cluster
3. The app's Kubernetes ServiceAccount annotated with the GCP service account that has `Cloud SQL Client` IAM role
4. `DATABASE_URL` must use the Unix socket path: `postgresql+asyncpg:///dbname?host=/cloudsql/PROJECT:REGION:INSTANCE_NAME`

Alternative: run `cloud-sql-proxy` as an explicit sidecar container. More explicit but adds a container to manage. Use if the native annotation pattern is not supported by the Pulumi GCP provider version in use.

#### OpenSearch as Dual-Purpose Backend (Temporal + Jaeger)

OpenSearch currently serves as the Jaeger v2 trace storage backend. Temporal Server (in production mode) requires an Elasticsearch or OpenSearch backend for workflow visibility search (searching workflows by status, run ID, etc.). The same OpenSearch instance can serve both Temporal and Jaeger.

Requirements:
- OpenSearch must be deployed and healthy before Temporal's `temporal-server` pod starts
- Temporal's Helm chart `values.yaml` must set `elasticsearch.enabled: false` and `elasticsearch.host` pointing to the in-cluster OpenSearch service
- Index lifecycle management (ILM) should be configured — Temporal creates its own indexes

Decision needed: use a single shared OpenSearch instance (simpler, fewer resources) or separate instances (better isolation). For v1 GKS, shared is recommended.

#### ESO Bootstrap Ordering

ESO must be installed and its `ClusterSecretStore` must be ready before any `ExternalSecret` CRs are applied. In Pulumi, this means:

1. Install ESO Helm chart first (with `dependsOn` in Pulumi)
2. Create `ClusterSecretStore` pointing at GCP Secret Manager
3. Apply `ExternalSecret` CRs for each namespace

If `ExternalSecret` CRs are applied before ESO is ready, they silently fail and Kubernetes Secrets are never created — pods will fail to start with missing env var errors. This is easy to miss because the ExternalSecret object itself is created (the CRD exists) but the sync never runs.

### Critical Pitfalls

#### Pitfall A: Pulumi Cluster Replacement on `dns_config` or Node Pool Changes

**What goes wrong:** Modifying certain GKE cluster fields (notably `dns_config`, `node_config` in Standard mode, or cluster-level settings that GKE doesn't support in-place updates for) causes Pulumi to propose replacing the entire cluster. A cluster replacement destroys all workloads, PVCs, and node pools.

**Prevention:**
- Add `opts=pulumi.ResourceOptions(ignore_changes=["dns_config", "node_version"])` on the GKE cluster resource for fields that are set once and should not drift
- Always run `pulumi preview` before `pulumi up` in CI; treat any `replace` operation on the cluster resource as a blocking alert
- For GKE Autopilot, many node-level fields are managed by GCP — set them once and guard with `ignore_changes`
- Maintain a separate Pulumi stack per environment so a misconfigured `pulumi up` in dev does not propagate to prod

**Phase to address:** Phase 1 (cluster provisioning). The `ignore_changes` list must be established before the cluster is first created, not after.

#### Pitfall B: Cloud SQL Auth Proxy Native Sidecar — Workload Identity Misconfiguration

**What goes wrong:** The Cloud SQL Auth Proxy sidecar annotation is applied but the Kubernetes ServiceAccount is not annotated with the GCP service account, or the GCP service account lacks the `Cloud SQL Client` IAM role. The app pod starts but database connections fail immediately with "connection refused" or "permission denied on Cloud SQL."

**Prevention:**
- Configure Workload Identity on the GKE cluster during cluster creation (not retrofittable without draining nodes)
- Create a dedicated GCP service account for the app (`vici-app@PROJECT.iam.gserviceaccount.com`)
- Bind `roles/cloudsql.client` to the GCP SA
- Annotate the Kubernetes ServiceAccount: `iam.gke.io/gcp-service-account: vici-app@PROJECT.iam.gserviceaccount.com`
- Test connectivity with a standalone `cloud-sql-proxy` pod before deploying the full app

**Phase to address:** Phase 1 (cluster provisioning) and Phase 2 (app deployment).

#### Pitfall C: Temporal Autopilot ES Init Container Fails if OpenSearch Not Ready

**What goes wrong:** Temporal's Helm chart includes an init container (`temporal-server`) that checks for Elasticsearch/OpenSearch connectivity before starting the Temporal server. If OpenSearch is not healthy (e.g., still initializing, replicas > 0 on single-node causing yellow status), the Temporal pod's init container times out and the pod enters `CrashLoopBackOff`.

**Prevention:**
- Deploy OpenSearch before Temporal in Pulumi (`dependsOn` chain)
- Set `number_of_replicas: 0` in OpenSearch's index templates for single-node deployments (same pitfall as local dev — Pitfall 14 in PITFALLS.md)
- Add a readiness probe to the OpenSearch deployment before Temporal's Helm release is applied
- In Temporal's Helm values, configure the connection timeout and retry settings to allow OpenSearch a startup window

**Phase to address:** Phase 3 (Temporal in-cluster deployment).

#### Pitfall D: ESO Bootstrap Ordering — ExternalSecrets Applied Before ESO Ready

**What goes wrong:** `ExternalSecret` CRs are applied (by Pulumi or Helm) before ESO is ready to process them. The CRs are created successfully (the CRD exists) but no Kubernetes Secret is generated. The app pod fails to start because environment variables sourced from the missing Secret are undefined.

**Prevention:**
- In Pulumi: use `dependsOn` to ensure the ESO Helm release is applied and all its CRD webhooks are healthy before applying any `ExternalSecret` resource
- Add a readiness check in CI: after `pulumi up`, run `kubectl get externalsecret -A` and confirm all are `Ready=True` before proceeding to smoke tests
- For the initial deploy, manually verify `kubectl describe clustersecretstore` shows `Valid=True`

**Phase to address:** Phase 2 (secrets infrastructure) and Phase 4 (full app deployment).

#### Pitfall E: `DATABASE_URL` Format Change for Cloud SQL Auth Proxy Socket

**What goes wrong:** The existing `DATABASE_URL` secret uses a TCP connection string (`postgresql+asyncpg://USER:PASS@HOST:5432/DB`). Cloud SQL Auth Proxy via the native sidecar uses a Unix socket path, not TCP. The connection string format is different and the application fails to connect.

**Prevention:**
- Update `DATABASE_URL` in GCP Secret Manager to use the socket format: `postgresql+asyncpg:///DB?host=/cloudsql/PROJECT:REGION:INSTANCE`
- The socket directory must match the path the Cloud SQL Auth Proxy sidecar mounts (default: `/cloudsql`)
- Test the connection string format locally with `cloud-sql-proxy` before deploying to GKE

**Phase to address:** Phase 2 (secrets and database connectivity).

#### Pitfall F: Twilio Webhook URL Must Be Updated Before Traffic Cuts Over

**What goes wrong:** After GKE deployment, the Twilio webhook URL still points at the Render.com service. Traffic goes to Render, not GKE. Alternatively, both are active simultaneously, causing duplicate processing.

**Prevention:**
- Treat the Twilio webhook URL as the cutover gate — update it only after GKE is fully validated (health check passes, Temporal worker connected, database connected)
- Decommission the Render service only after the Twilio webhook is updated and at least one successful end-to-end SMS has been processed on GKE
- The `WEBHOOK_BASE_URL` environment variable must reflect the GKE Ingress public IP/hostname, not the Render URL, for Twilio signature validation to pass

**Phase to address:** Phase 6 (cutover and validation).

---

## Implications for Roadmap

### Recommended Phase Structure (6 Phases)

#### Phase 1: GKE Cluster and Networking Baseline

**Rationale:** Everything downstream depends on the cluster. Cluster replacement is the highest-risk Pulumi operation; establishing the cluster resource with correct `ignore_changes` guards first prevents catastrophic accidents in later phases.

**Delivers:**
- GKE Autopilot cluster (single region, private nodes + public endpoint for kubectl)
- VPC with private subnet for GKE nodes and Cloud SQL
- Workload Identity enabled on the cluster
- Pulumi state in GCS bucket
- One Pulumi stack per environment (`dev`, `prod`)

**Pitfalls to avoid:** Pulumi cluster replacement on `dns_config` (Pitfall A).

**Research flag:** Standard patterns — GKE Autopilot + Pulumi Python is well-documented by Google and Pulumi. No additional research needed unless custom node configuration is required.

---

#### Phase 2: Secrets Infrastructure and Database

**Rationale:** The app cannot start without database connectivity and secrets. ESO and Cloud SQL must be fully operational before the app is deployed.

**Delivers:**
- Cloud SQL instance (PostgreSQL 16, private IP in same VPC)
- Cloud SQL Auth Proxy native sidecar configured on app ServiceAccount
- GCP Secret Manager secrets populated (DATABASE_URL, TWILIO_*, OPENAI_API_KEY, PINECONE_API_KEY, BRAINTRUST_API_KEY)
- ESO Helm release installed with `ClusterSecretStore` pointing at GCP Secret Manager
- `ExternalSecret` CRs for the `vici` namespace
- Alembic migration Job (runs `alembic upgrade head` against Cloud SQL before app Deployment is applied)

**Pitfalls to avoid:** Cloud SQL Auth Proxy Workload Identity misconfiguration (Pitfall B), ESO bootstrap ordering (Pitfall D), DATABASE_URL socket format (Pitfall E).

**Research flag:** Needs Phase-level research. Cloud SQL Auth Proxy native sidecar in Autopilot + ESO + Workload Identity is a three-way integration with GKE-specific nuances.

---

#### Phase 3: Temporal In-Cluster

**Rationale:** The Temporal server must be running before the app worker can connect. The Temporal Helm chart has several configuration decisions (PostgreSQL backend vs. Cassandra, OpenSearch integration, schema migration jobs) that affect the app's `TEMPORAL_HOST` configuration.

**Delivers:**
- OpenSearch deployment in `observability` namespace (precondition for Temporal)
- Temporal Helm release in `temporal` namespace (connected to Cloud SQL for persistence, OpenSearch for visibility)
- Temporal UI accessible internally (or via Ingress if desired)
- App's `TEMPORAL_HOST` secret updated to `temporal-frontend.temporal.svc.cluster.local:7233`

**Pitfalls to avoid:** Temporal init container failing if OpenSearch not ready (Pitfall C), OpenSearch replicas > 0 on single-node (Pitfall 14 from PITFALLS.md).

**Research flag:** Needs Phase-level research. Temporal Helm chart values for OpenSearch integration and the schema migration init container sequence require validation against the `temporaltech/temporal` chart version to be used.

---

#### Phase 4: Observability Stack

**Rationale:** Observability should be in place before the app is deployed so the first real request generates traces and metrics.

**Delivers:**
- Jaeger v2 deployment (connected to OpenSearch from Phase 3)
- `kube-prometheus-stack` Helm release in `observability` namespace
- ServiceMonitor for the FastAPI app (`/metrics` endpoint)
- ServiceMonitor for Temporal
- Grafana with pre-built FastAPI dashboard (from existing Docker Compose config)
- App's `OTEL_EXPORTER_OTLP_ENDPOINT` secret set to in-cluster Jaeger collector

**Pitfalls to avoid:** OpenSearch single-node replica count (already addressed in Phase 3).

**Research flag:** Standard patterns. kube-prometheus-stack is well-documented. Jaeger v2 Helm chart for OpenSearch backend is stable.

---

#### Phase 5: Application Deployment

**Rationale:** The app is deployed last, after all dependencies are confirmed healthy.

**Delivers:**
- FastAPI app Deployment in `vici` namespace (with Cloud SQL Auth Proxy native sidecar annotation)
- Kubernetes Service (ClusterIP)
- Ingress (GKE Ingress or NGINX) with TLS via cert-manager
- cert-manager Helm release with Let's Encrypt issuer
- `WEBHOOK_BASE_URL` set to Ingress public hostname
- End-to-end smoke test: `GET /health` returns 200, Temporal worker appears in Temporal UI

**Pitfalls to avoid:** Twilio webhook URL update (Pitfall F — do NOT update Twilio yet; validate GKE first).

**Research flag:** Standard patterns. GKE Ingress + cert-manager + Let's Encrypt is well-documented.

---

#### Phase 6: Cutover and Render Decommission

**Rationale:** Traffic cutover is a one-way door. Validate GKE thoroughly before switching Twilio.

**Delivers:**
- Twilio webhook URL updated to GKE Ingress hostname
- End-to-end SMS test on GKE (one real SMS through the full pipeline)
- Render.com service deprovisioned (after 1 full business day of GKE traffic)
- Render PostgreSQL data migration confirmed (if any data needs to migrate from Render PostgreSQL to Cloud SQL)

**Pitfalls to avoid:** Twilio signature validation failing on new URL (Pitfall 1 from PITFALLS.md — `WEBHOOK_BASE_URL` must match the URL Twilio uses to sign requests). Parallel Render + GKE active causes duplicate SMS processing.

**Research flag:** No additional research needed. Twilio webhook URL change is a console operation.

---

### Research Flags Summary

| Phase | Research Needed | Reason |
|-------|----------------|--------|
| Phase 1 | No | GKE Autopilot + Pulumi is well-documented |
| Phase 2 | Yes | Cloud SQL Auth Proxy native sidecar + Workload Identity + ESO three-way integration |
| Phase 3 | Yes | Temporal Helm chart values for OpenSearch visibility; init container sequence |
| Phase 4 | No | kube-prometheus-stack + Jaeger standard patterns |
| Phase 5 | No | GKE Ingress + cert-manager standard patterns |
| Phase 6 | No | Operational cutover |

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Current application stack | HIGH | Derived from codebase inspection (codebase STACK.md, ARCHITECTURE.md dated 2026-04-03) |
| GKE Autopilot + Pulumi | MEDIUM | Well-documented patterns; not yet applied to this specific codebase |
| Cloud SQL Auth Proxy native sidecar | MEDIUM | GKE 1.29+ feature; Pulumi GCP provider version dependency unconfirmed |
| ESO + GCP Secret Manager | MEDIUM | Stable pattern; bootstrap ordering is a known operational concern |
| Temporal Helm chart (OpenSearch visibility) | LOW-MEDIUM | Temporal Helm chart values for OpenSearch integration require validation; `temporaltech/temporal` chart versioning is not pinned in this research |
| OpenSearch dual-use (Jaeger + Temporal) | MEDIUM | Supported by both projects; ILM configuration not researched |
| Render → GKE data migration | MEDIUM | PostgreSQL dump/restore is standard; Cloud SQL import path needs validation |

**Overall confidence:** MEDIUM. The application-layer findings are HIGH confidence (derived from built system). The infrastructure findings are MEDIUM — patterns are established but the specific combination (GKE Autopilot + Pulumi + Cloud SQL Auth Proxy native sidecar + ESO + Temporal + OpenSearch dual-use) has not been exercised in this repository.

---

## Open Questions (Decisions Required Before or During Planning)

| Question | When Needed | Impact |
|----------|-------------|--------|
| GKE Ingress (GCP Load Balancer) vs. NGINX Ingress? | Phase 1 planning | Affects Helm chart choices, routing capabilities, and cost |
| Temporal database backend: separate Cloud SQL database or shared Cloud SQL instance with separate DB? | Phase 3 planning | Shared instance is cheaper; separate is more isolated |
| OpenSearch: single shared instance (Jaeger + Temporal) or separate instances? | Phase 3 planning | Single instance simpler but higher blast radius |
| Cloud SQL Auth Proxy: native sidecar annotation or explicit sidecar container? | Phase 2 planning | Native requires GKE 1.29+ and Workload Identity; explicit is more portable |
| Pulumi GCP provider version? | Phase 1 planning | Must be >= 7.x for native sidecar annotation support |
| Data migration: copy Render PostgreSQL data to Cloud SQL, or start fresh on GKE? | Phase 6 planning | If data needs migrating, pg_dump + Cloud SQL import must be planned |
| Temporal version to deploy? | Phase 3 planning | `temporaltech/temporal` chart version determines OpenSearch compatibility |
| ESO: `ClusterSecretStore` (cluster-wide) or namespace-scoped `SecretStore`? | Phase 2 planning | ClusterSecretStore is simpler; SecretStore gives namespace isolation |
| GCP region selection? | Phase 1 planning | Affects latency to Twilio, OpenAI, Pinecone; nearest to users |
| cert-manager issuer: Let's Encrypt or GCP-managed certificates? | Phase 5 planning | Let's Encrypt is free and universal; GCP-managed is simpler with GKE Ingress |

---

## Sources

### Primary (HIGH confidence)
- `.planning/codebase/STACK.md` — current tech stack (updated 2026-04-03)
- `.planning/codebase/ARCHITECTURE.md` — current architecture and source layout (updated 2026-04-03)
- `.planning/codebase/SUMMARY.md` — current state summary (updated 2026-04-03)
- `.planning/todos/pending/2026-04-04-revise-setup-to-ensure-it-s-able-to-be-deployed-to-gks-v-render.md` — GKS migration TODO
- `.planning/todos/pending/2026-04-02-refactor-code-such-that-temporal-is-able-to-be-leveraged.md` — Temporal migration context

### Secondary (used for original application research)
- `.planning/research/STACK.md`, `FEATURES.md`, `ARCHITECTURE.md`, `PITFALLS.md` — original pre-build research (Render/Inngest era, 2026-03-08); superseded by codebase docs for application-layer findings; pitfalls remain relevant for application-layer concerns carried forward to GKS

### External Patterns (MEDIUM confidence — established community patterns)
- GKE Autopilot documentation: https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview
- Cloud SQL Auth Proxy native sidecar: https://cloud.google.com/sql/docs/postgres/connect-kubernetes-engine
- Pulumi GCP provider: https://www.pulumi.com/registry/packages/gcp/
- External Secrets Operator: https://external-secrets.io/latest/provider/google-secrets-manager/
- Temporal Helm chart: https://github.com/temporalio/helm-charts

---

*Synthesized: 2026-04-04*
*Ready for roadmap planning: yes, pending answers to Open Questions*
