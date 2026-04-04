# Feature Landscape: GKE Migration

**Domain:** Infrastructure migration (Render.com to GKE Autopilot)
**Researched:** 2026-04-04

## Table Stakes

Features required for production parity with Render.com. Missing any of these blocks go-live.

| Feature | Why Expected | Complexity | Dependencies | Notes |
|---------|--------------|------------|--------------|-------|
| GKE Autopilot cluster provisioning | Runtime environment for all workloads | Low | GCP project, billing | Autopilot is opinionated -- no node config needed. Pulumi `gcp.container.Cluster` with `enableAutopilot: true` |
| Workload Identity Federation | Eliminates static GCP credentials; Autopilot enables this by default | Medium | GCP IAM, K8s ServiceAccounts | KSA-to-GSA binding per workload. Required for Cloud SQL Auth Proxy and ESO |
| Cloud SQL Postgres 16 (managed) | Production database; replaces Render Postgres | Low | GCP project, VPC | Private IP preferred. Managed backups, point-in-time recovery out of the box |
| Cloud SQL Auth Proxy sidecar | Secure, IAM-authed DB connections without managing SSL certs or allowlisting IPs | Medium | Workload Identity, Cloud SQL instance | Sidecar on FastAPI app + Temporal worker pods. CPU: 100m/200m, Memory: 128Mi/256Mi. Consider the Cloud SQL Proxy Operator as an alternative to manual sidecar injection |
| External Secrets Operator (ESO) | Syncs GCP Secret Manager secrets to K8s Secrets | Medium | Workload Identity, Secret Manager secrets populated | ClusterSecretStore + ExternalSecret per namespace. Covers Twilio, OpenAI, Pinecone, Braintrust, Temporal credentials |
| GCP Secret Manager | Centralized secret storage replacing Render env vars | Low | GCP project | One secret per credential per environment. ESO reads from here |
| Artifact Registry | Container image storage replacing implicit Render builds | Low | GCP project | Single multi-env registry. GitHub Actions pushes tagged images |
| GKE Ingress + Google-managed TLS | HTTPS endpoints per environment | Medium | DNS records, static IP | Use `ManagedCertificate` CRD + `networking.gke.io/managed-certificates` annotation. No wildcard support -- one cert per env hostname. TLS terminates at GCP load balancer |
| HPA for FastAPI deployment | Auto-scaling matching Render auto-scale behavior | Low | Metrics server (built into Autopilot) | CPU-based scaling is sufficient for webhook-driven workload |
| Alembic migration Job | Pre-deploy schema migrations | Medium | Cloud SQL Auth Proxy sidecar on Job pod, Workload Identity | K8s Job with `ttlSecondsAfterFinished`. Must complete before app Deployment rolls out. Needs sidecar lifecycle coordination (proxy must stay alive until migration completes, then exit) |
| Pulumi Python IaC (3 stacks) | Infrastructure parity across dev/staging/prod | High | Pulumi account, GCP credentials in CI | Single program, three stacks. Env differences are config only. This is the highest-effort table-stakes item |
| GitHub Actions CD pipeline | Automated deploy replacing Render auto-deploy | Medium | Artifact Registry, Pulumi token, GCP Workload Identity Federation for CI | Build, push, `pulumi up --stack <env>`. Dev on push to main; staging/prod on manual trigger |
| Temporal server deployment | Workflow orchestration runtime | Medium | Namespace isolation, persistence (Cloud SQL or separate DB) | Deploy in `temporal` namespace. Temporal server itself needs a persistence store -- confirm whether it shares the app Cloud SQL instance or gets its own |
| Observability stack (Prometheus, Grafana, Jaeger, OTel Collector) | Monitoring/tracing parity with current setup | Medium | `observability` namespace, existing dashboard JSON | Self-hosted in-cluster. Prometheus ServiceMonitor CRDs for scrape targets. Grafana provisioned with existing dashboards via ConfigMap |

## Differentiators

Features not present in Render.com setup that GKE enables. Not required for parity but high value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Pod Disruption Budgets | Zero-downtime deploys for FastAPI and Temporal worker | Low | `minAvailable: 1` on each Deployment. Free reliability win |
| NetworkPolicy isolation | Namespace-level network segmentation (vici, temporal, observability) | Low | Autopilot supports NetworkPolicy. Restrict cross-namespace traffic to only what is needed |
| Resource quotas per namespace | Prevent runaway workloads from starving others | Low | Autopilot enforces its own minimums, but quotas add guardrails |
| Liveness/readiness probes | Automatic restart of unhealthy pods, traffic routing only to ready pods | Low | FastAPI `/health` endpoint likely exists. Add to all Deployments |
| Rolling update strategy | Controlled rollout with `maxSurge`/`maxUnavailable` | Low | Default is fine for most cases; tune if webhook latency matters |
| Cloud SQL high availability (regional) | Automatic failover for database | Low | Flag on Cloud SQL instance. Cost increase but significant for prod |
| VPA (Vertical Pod Autoscaler) | Right-size resource requests over time | Low | Autopilot has built-in resource adjustment, but explicit VPA gives more control |
| GKE Gateway API (instead of Ingress) | More flexible routing, native Certificate Manager integration, wildcard TLS | Medium | Newer API, replaces Ingress long-term. Not required for v1 but worth knowing about |
| Cloud SQL automated backups + PITR | Database disaster recovery | Low | Enabled by default on Cloud SQL; just configure retention |
| Pulumi policy packs | Enforce infrastructure guardrails (no public IPs, require labels, etc.) | Medium | Nice governance layer for multi-env setup |

## Anti-Features

Features to explicitly NOT build in this migration.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Static service account key JSON in pods | Security anti-pattern; keys leak, rotate poorly | Workload Identity Federation -- always |
| Self-hosted Postgres in K8s | Operational burden: backups, HA, upgrades all on you | Cloud SQL managed instance |
| cert-manager + Let's Encrypt | Unnecessary complexity when Google-managed certs handle the same job natively | `ManagedCertificate` CRD with GKE Ingress |
| ArgoCD / Flux GitOps | Over-engineering for a three-env single-team setup | Direct `pulumi up` from GitHub Actions |
| Multi-region / multi-cluster | Premature; adds cost and complexity with no current requirement | Single region per environment |
| Helm charts for app workloads | Indirection layer that Pulumi already handles natively via `kubernetes.apps.v1.Deployment` | Pulumi K8s provider directly. Helm only if needed for third-party charts (Temporal, Prometheus) |
| Istio / service mesh | Massive complexity for inter-service communication that can be solved with simple K8s Services | Plain ClusterIP Services + NetworkPolicy |
| Manual `kubectl apply` deployments | Drift, no state tracking, no rollback | Pulumi manages all K8s resources |
| Shared Cloud SQL instance for Temporal + app | Temporal's DB usage patterns (visibility store, history) can interfere with app queries | Evaluate separate Cloud SQL instance or at minimum separate databases within the same instance with connection limits |

## Feature Dependencies

```
GCP Project + Billing
  |
  +-- GKE Autopilot Cluster
  |     |
  |     +-- Workload Identity Federation (enabled by default on Autopilot)
  |     |     |
  |     |     +-- Cloud SQL Auth Proxy sidecar (needs WI to authenticate)
  |     |     |     |
  |     |     |     +-- FastAPI Deployment (app connects to proxy on localhost:5432)
  |     |     |     +-- Temporal Worker Deployment
  |     |     |     +-- Alembic Migration Job
  |     |     |
  |     |     +-- External Secrets Operator (needs WI to read Secret Manager)
  |     |           |
  |     |           +-- K8s Secrets (consumed by all workloads)
  |     |
  |     +-- Ingress + ManagedCertificate (needs static IP + DNS)
  |     +-- HPA (needs Deployment + metrics-server)
  |     +-- Observability namespace (Prometheus, Grafana, Jaeger, OTel)
  |     +-- Temporal namespace (Temporal server)
  |
  +-- Cloud SQL Postgres 16 (needs VPC, private IP)
  +-- GCP Secret Manager (secrets must be populated before ESO can sync)
  +-- Artifact Registry (images must exist before Deployments can pull)
```

## MVP Recommendation

Prioritize in this order (respects dependency chain):

1. **Pulumi program skeleton + GKE Autopilot cluster** -- everything depends on this
2. **Cloud SQL + Artifact Registry + Secret Manager** -- external GCP resources
3. **Workload Identity bindings** -- unlocks secure access to Cloud SQL and Secret Manager
4. **External Secrets Operator + SecretStore** -- secrets flowing into cluster
5. **Cloud SQL Auth Proxy sidecar pattern** -- database connectivity
6. **FastAPI Deployment + Alembic Job** -- core application running
7. **Temporal server + worker** -- workflow engine
8. **Observability stack** -- monitoring and tracing
9. **Ingress + TLS** -- external traffic
10. **HPA + PDBs + probes** -- production hardening
11. **GitHub Actions CD pipeline** -- automated deploys

**Defer:** Gateway API migration (do after v1 is stable), VPA tuning (let Autopilot handle initially), Pulumi policy packs (governance layer for later).

## Key Integration Notes

- **Autopilot resource bumping:** Autopilot enforces minimum resource requests per container. If you request less than the minimum, it silently bumps up. Budget for this -- your actual resource consumption will be higher than what you specify for small sidecars.
- **Sidecar lifecycle on Jobs:** The Cloud SQL Auth Proxy sidecar on the Alembic migration Job will not terminate when the main container exits. You need a sidecar termination strategy (e.g., `shareProcessNamespace: true` + signal, or a `/quitquitquit` endpoint on the proxy).
- **ManagedCertificate provisioning time:** Google-managed certs can take 15-60 minutes to provision. DNS must resolve to the load balancer IP before provisioning succeeds.
- **ESO sync interval:** Default sync period is configurable. Set to something reasonable (e.g., 1h) -- too frequent wastes Secret Manager API quota.

## Sources

- [GKE Autopilot overview](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview)
- [GKE Autopilot resource requests](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-resource-requests)
- [Autopilot vs Standard feature comparison](https://docs.google.com/kubernetes-engine/docs/resources/autopilot-standard-feature-comparison)
- [Secure traffic for GKE Ingress (managed certs)](https://cloud.google.com/kubernetes-engine/docs/how-to/managed-certs)
- [Connect to Cloud SQL from GKE](https://cloud.google.com/sql/docs/mysql/connect-kubernetes-engine)
- [Cloud SQL Proxy Operator](https://github.com/GoogleCloudPlatform/cloud-sql-proxy-operator)
- [External Secrets Operator with GCP Secret Manager](https://medium.com/google-cloud/secrets-management-using-external-secret-operator-for-goole-secret-manager-on-gke-2e20f38a66bf)
- [GKE Workload Identity with secrets](https://docs.google.com/kubernetes-engine/docs/tutorials/workload-identity-secrets)
