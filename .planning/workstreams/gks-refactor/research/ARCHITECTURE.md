# Architecture: GKE Migration

**Domain:** Infrastructure migration (Render.com to GKE Autopilot)
**Researched:** 2026-04-04

## Recommended Architecture

### Pulumi Program Structure: Single Program, Three Stacks

Use one Pulumi Python program with three stack config files: `Pulumi.dev.yaml`, `Pulumi.staging.yaml`, `Pulumi.prod.yaml`. This is the canonical Pulumi pattern for mirrored environments.

**Confidence:** HIGH (official Pulumi docs)

```
infra/
  __main__.py           # Entry point
  Pulumi.yaml           # Project definition
  Pulumi.dev.yaml       # Stack config: dev
  Pulumi.staging.yaml   # Stack config: staging
  Pulumi.prod.yaml      # Stack config: prod
  config.py             # Typed config wrapper
  components/
    cluster.py          # GKE Autopilot cluster
    database.py         # Cloud SQL instance + databases
    secrets.py          # Secret Manager + External Secrets Operator
    identity.py         # Workload Identity bindings
    workloads/
      app.py            # FastAPI Deployment + HPA + Service
      temporal_worker.py
      temporal_server.py
      observability.py  # Jaeger, Prometheus, Grafana
      migration_job.py  # Alembic Job
    networking.py       # Ingress, TLS, DNS
    registry.py         # Artifact Registry
```

Each component is a Pulumi `ComponentResource`. `__main__.py` composes them. Stack configs hold only values that differ (hostnames, instance sizes, replica counts).

### Namespace Layout (per cluster)

| Namespace | Workloads | Rationale |
|-----------|-----------|-----------|
| `vici` | FastAPI app, Temporal worker, Alembic Job | Application workloads share DB access patterns and secrets |
| `temporal` | Temporal server, Temporal UI | Isolated failure domain; separate RBAC; own DB credentials |
| `observability` | Jaeger (collector + query), Prometheus, Grafana | Shared concern; no app coupling |
| `external-secrets` | External Secrets Operator | Cluster-wide operator, own namespace per convention |

### Component Boundaries

| Component | Responsibility | Communicates With | New vs Modified |
|-----------|---------------|-------------------|-----------------|
| GKE Autopilot cluster | Compute platform | All workloads | **New** (Pulumi) |
| Cloud SQL instance | Postgres 16 (app DB + Temporal DBs) | App, Worker, Temporal server via Auth Proxy | **New** (Pulumi) |
| Cloud SQL Auth Proxy | IAM-authed DB connections | Sidecar on app, worker, temporal-server pods | **New** (K8s sidecar) |
| Artifact Registry | Docker image storage | GitHub Actions, GKE | **New** (Pulumi) |
| External Secrets Operator | Sync GCP Secret Manager to K8s Secrets | All namespaces | **New** (Helm via Pulumi) |
| Workload Identity | Pod-to-GCP IAM binding | All GCP-touching pods | **New** (Pulumi) |
| FastAPI Deployment | HTTP API | Cloud SQL, Pinecone, Temporal, OTel collector | **Modified** (K8s manifests replace Render service) |
| Temporal Worker | Workflow/activity execution | Cloud SQL, Pinecone, external APIs | **Modified** (K8s manifests replace Render worker) |
| Temporal Server | Workflow orchestration | Cloud SQL (temporal + visibility DBs) | **Modified** (Helm chart replaces docker-compose) |
| Jaeger (collector + query) | Trace storage and UI | OpenSearch (or replacement), OTel | **Modified** (K8s manifests) |
| Prometheus + Grafana | Metrics | Scrapes all pods | **Modified** (K8s manifests, existing dashboards) |
| Ingress + TLS | External traffic routing | FastAPI app, Grafana, Jaeger UI, Temporal UI | **New** |
| GitHub Actions CD | Build + deploy pipeline | Artifact Registry, Pulumi | **New** |

## Key Architectural Decisions

### 1. Cloud SQL: One Instance, Three Databases

**Decision:** Single Cloud SQL instance per environment with three databases: `vici`, `temporal`, `temporal_visibility`.

**Rationale:**
- Temporal requires two databases (`temporal` and `temporal_visibility`) separate from the app database. This is a hard requirement.
- Separate Cloud SQL instances would triple cost for no benefit at Vici's scale. A single instance with separate databases and separate DB users provides isolation.
- Cloud SQL Auth Proxy sidecars connect all pods to the same instance; connection routing is by database name.
- If Temporal load ever demands independent scaling, splitting to a second instance is straightforward.

**Confidence:** MEDIUM (Temporal docs confirm separate DBs required; single-instance approach is standard practice for small-to-medium workloads but not explicitly recommended by Temporal)

### 2. Temporal Server: Official Helm Chart with Bundled Dependencies Disabled

**Decision:** Deploy Temporal via the official `temporalio/helm-charts` (v3), disabling all bundled dependencies (Cassandra, Elasticsearch, Prometheus). Point Temporal at the Cloud SQL databases.

**Key configuration:**
- Disable `cassandra.enabled`, `elasticsearch.enabled`, `prometheus.enabled`, `grafana.enabled`
- Configure `server.config.persistence.default.sql.driver: postgres12` pointing to Cloud SQL
- Configure `server.config.persistence.visibility.sql.driver: postgres12` pointing to Cloud SQL
- Run schema init/migration as a Kubernetes Job before Helm upgrade (automate via Pulumi or CD pipeline)
- Set `server.config.numHistoryShards: 512` (sufficient for low-to-medium throughput; 2048 is for large clusters)

**Confidence:** HIGH ([Temporal Helm charts](https://github.com/temporalio/helm-charts), [Temporal deployment docs](https://docs.temporal.io/self-hosted-guide/deployment))

### 3. OpenSearch: Replace with Cloud Logging + Jaeger v2 In-Memory (Dev/Staging), Managed OpenSearch via Aiven (Prod)

**Decision:** Do NOT self-host OpenSearch in GKE Autopilot.

**Rationale:**
- GCP has no managed OpenSearch service. Self-hosting OpenSearch in Autopilot is painful: privileged containers are restricted, memory/storage tuning conflicts with Autopilot's pod-level resource model, and operational burden is high.
- Jaeger v2 supports multiple storage backends. For dev/staging, use Badger (embedded) or in-memory storage -- traces are ephemeral in non-prod.
- For prod, two viable paths:
  - **Option A (recommended): Aiven for OpenSearch on GCP Marketplace.** Managed, billed through GCP, minimal ops. Jaeger config stays nearly identical to current docker-compose setup.
  - **Option B: Switch Jaeger backend to Cloud Trace.** GCP-native, zero ops, but loses Jaeger UI and custom queries. Not recommended -- too much workflow disruption.

**Revised observability namespace (prod):**
```
Namespace: observability
  Deployment: jaeger-collector  (OTLP receiver -> Aiven OpenSearch)
  Deployment: jaeger-query      (reads from Aiven OpenSearch)
  Deployment: prometheus
  Deployment: grafana
```

**Dev/staging:**
```
Namespace: observability
  Deployment: jaeger-all-in-one (OTLP receiver + query + Badger storage)
  Deployment: prometheus
  Deployment: grafana
```

**Confidence:** MEDIUM (Jaeger v2 Badger backend is supported but less commonly used in production; Aiven recommendation based on [BigData Boutique analysis](https://bigdataboutique.com/blog/google-cloud-opensearch-deployment-options-and-best-practices))

### 4. Ingress: GKE Gateway API (not nginx-ingress)

**Decision:** Use GKE's native Gateway API (GKE Gateway Controller) for ingress and TLS.

**Rationale:** Autopilot natively supports Gateway API. No need for nginx-ingress-controller. Google-managed TLS certificates via Certificate Manager. Simpler than deploying an ingress controller.

**Confidence:** HIGH (GKE Autopilot docs)

## Data Flow

```
Internet
  |
  v
GKE Gateway (TLS termination, env-specific hostname)
  |
  +-- /api/*  --> vici-app Service (FastAPI)
  +-- /grafana --> grafana Service
  +-- /jaeger  --> jaeger-query Service
  +-- /temporal-ui --> temporal-ui Service
  |
vici-app pod:
  [FastAPI container] --OTLP--> otel-collector/jaeger-collector :4317
  [FastAPI container] --SQL via Auth Proxy sidecar--> Cloud SQL (vici DB)
  [FastAPI container] --gRPC--> temporal-server:7233
  [FastAPI container] --HTTPS--> Pinecone (external SaaS)
  |
temporal-worker pod:
  [Worker container] --SQL via Auth Proxy sidecar--> Cloud SQL (vici DB)
  [Worker container] --gRPC--> temporal-server:7233
  [Worker container] --HTTPS--> OpenAI, Pinecone, Twilio (external SaaS)
  |
temporal-server pod:
  [Temporal container] --SQL via Auth Proxy sidecar--> Cloud SQL (temporal + temporal_visibility DBs)
```

## Integration Points Summary

| Source | Target | Protocol | Notes |
|--------|--------|----------|-------|
| GitHub Actions | Artifact Registry | Docker push | Image build + push |
| GitHub Actions | Pulumi | CLI | `pulumi up --stack <env>` |
| FastAPI app | Cloud SQL | PostgreSQL (via Auth Proxy) | App database |
| FastAPI app | Temporal server | gRPC :7233 | Workflow dispatch |
| FastAPI app | Pinecone | HTTPS | External SaaS, unchanged |
| FastAPI app | Jaeger collector | OTLP gRPC :4317 | Traces |
| Temporal worker | Cloud SQL | PostgreSQL (via Auth Proxy) | App database |
| Temporal worker | External APIs | HTTPS | Twilio, OpenAI, Pinecone, Braintrust |
| Temporal server | Cloud SQL | PostgreSQL (via Auth Proxy) | temporal + temporal_visibility DBs |
| Jaeger collector | OpenSearch/Aiven (prod) or Badger (dev/staging) | HTTPS / local | Trace storage |
| Prometheus | All pods | HTTP scrape | Metrics collection |
| External Secrets Operator | GCP Secret Manager | GCP API | Secret sync |
| All GCP-touching pods | GCP APIs | Workload Identity | No static keys |

## Suggested Build Order (Phases)

Build order is driven by dependency chains. Each phase produces a testable, deployable increment.

### Phase 1: Foundation (GCP project + core infra)
- GCP project setup (if not existing)
- Artifact Registry repository
- Cloud SQL instance + three databases (vici, temporal, temporal_visibility)
- GKE Autopilot cluster (dev only first)
- Workload Identity setup (GCP SAs + IAM bindings)
- Secret Manager secrets populated
- Pulumi program skeleton with `dev` stack

**Why first:** Everything else depends on cluster + database + identity.

### Phase 2: Secrets + Database Connectivity
- External Secrets Operator (Helm install via Pulumi)
- SecretStore + ExternalSecret resources for `vici` namespace
- Cloud SQL Auth Proxy sidecar pattern (reusable component)
- Alembic migration Job (validates DB connectivity end-to-end)

**Why second:** Validates the credential chain (Workload Identity -> Secret Manager -> K8s Secret -> Auth Proxy -> Cloud SQL) before deploying any workload.

### Phase 3: Temporal Server
- Temporal Helm chart deployment (temporal namespace)
- Temporal schema init Job
- SecretStore + ExternalSecret for temporal namespace
- Cloud SQL Auth Proxy on Temporal pods
- Validate with `tctl cluster health`

**Why third:** App and worker both depend on Temporal. Deploy and validate it before consumers.

### Phase 4: Application Workloads
- FastAPI Deployment + Service + HPA
- Temporal Worker Deployment
- Ingress / Gateway for FastAPI
- Validate end-to-end: HTTP request -> FastAPI -> Temporal workflow -> worker execution

**Why fourth:** Core application. Depends on Phases 1-3.

### Phase 5: Observability
- Jaeger collector + query (dev: all-in-one with Badger)
- OTel SDK config in app (env vars only, no code changes)
- Prometheus + Grafana with existing dashboards
- Ingress routes for Grafana, Jaeger UI, Temporal UI

**Why fifth:** Non-blocking for app functionality. Can iterate independently.

### Phase 6: CD Pipeline + Multi-Environment
- GitHub Actions workflow: build -> push -> pulumi up
- Replicate to staging stack, then prod stack
- Aiven OpenSearch for prod (if traces needed in prod)
- Production Ingress with real domain + TLS
- Smoke test suite

**Why last:** CD automates what was done manually in Phases 1-5. Staging/prod are config-only differences once dev is proven.

## Anti-Patterns to Avoid

### Anti-Pattern: Separate Pulumi Programs per Environment
**Why bad:** Drift between environments. Triple maintenance. Defeats the purpose of mirrored infra.
**Instead:** Single program, three stacks. All env differences live in `Pulumi.<env>.yaml`.

### Anti-Pattern: Self-Hosting OpenSearch in Autopilot
**Why bad:** Privileged container restrictions, memory tuning conflicts, high ops burden for a trace store.
**Instead:** Badger/in-memory for non-prod. Aiven managed OpenSearch for prod.

### Anti-Pattern: Temporal and App Sharing a Namespace
**Why bad:** Blast radius. Temporal server has its own lifecycle, scaling, and RBAC needs.
**Instead:** Separate `temporal` namespace with its own ServiceAccount and secrets.

### Anti-Pattern: Running Alembic in App Container Init
**Why bad:** Every pod replica runs migrations on startup; race conditions; rollback complexity.
**Instead:** Dedicated Kubernetes Job that runs once before deployment rollout.

## Scalability Considerations

| Concern | Dev | Staging | Prod |
|---------|-----|---------|------|
| FastAPI replicas | 1 (HPA min) | 2 | 2-10 (HPA) |
| Temporal workers | 1 | 1 | 2-4 |
| Temporal server | 1 | 1 | 2 (frontend + history) |
| Cloud SQL | db-f1-micro | db-g1-small | db-custom-2-4096 |
| Trace storage | Badger (ephemeral) | Badger (ephemeral) | Aiven OpenSearch |

## Sources

- [Temporal Helm Charts](https://github.com/temporalio/helm-charts)
- [Temporal Deployment Docs](https://docs.temporal.io/self-hosted-guide/deployment)
- [Tips for Running Temporal on Kubernetes](https://temporal.io/blog/tips-for-running-temporal-on-kubernetes)
- [Pulumi: Organizing Projects and Stacks](https://www.pulumi.com/docs/using-pulumi/organizing-projects-stacks/)
- [Pulumi: IaC Best Practices Code Organization](https://www.pulumi.com/blog/iac-recommended-practices-code-organization-and-stacks/)
- [BigData Boutique: Google Cloud OpenSearch Options](https://bigdataboutique.com/blog/google-cloud-opensearch-deployment-options-and-best-practices)
- [Elastic: ECK on GKE Autopilot](https://www.elastic.co/guide/en/cloud-on-k8s/master/k8s-autopilot.html)
- [Jaeger Storage Backends](https://www.jaegertracing.io/docs/2.dev/storage/)
- [Jaeger v2 Released](https://www.cncf.io/blog/2024/11/12/jaeger-v2-released-opentelemetry-in-the-core/)
