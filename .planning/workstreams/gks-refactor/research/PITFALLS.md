# Domain Pitfalls: GKE Autopilot Migration

**Domain:** Python/FastAPI + Temporal migration from Render.com to GKE Autopilot with Pulumi
**Researched:** 2026-04-04

## Critical Pitfalls

Mistakes that cause rewrites, outages, or major delays.

### Pitfall 1: Pulumi Triggers Cluster Replacement on DNS Config Drift

**What goes wrong:** After initial `pulumi up` creates a GKE Autopilot cluster, subsequent runs detect a diff on `dnsConfig` (GCP applies defaults silently) and Pulumi proposes to **replace the entire cluster** -- a destructive operation that tears down all workloads.
**Why it happens:** GCP sets `clusterDns: CLOUD_DNS`, `clusterDnsDomain: cluster.local`, `clusterDnsScope: CLUSTER_SCOPE` by default but Pulumi sees the absence of these in your code as a removal.
**Consequences:** Cluster destruction and recreation. Total environment outage. All pods, PVCs, and in-cluster state lost.
**Prevention:** Always set `dns_config` explicitly in your Pulumi cluster definition. Additionally, add `verticalPodAutoscaling` and `dns_config` to `ignore_changes` as a safety net.
**Detection:** `pulumi preview` shows `replace` on the cluster resource. Never skip preview before apply.
**Confidence:** HIGH -- confirmed via [pulumi/pulumi-gcp#1170](https://github.com/pulumi/pulumi-gcp/issues/1170).
**Phase:** IaC foundation (Phase 1). Must be correct from first cluster creation.

### Pitfall 2: Cloud SQL Auth Proxy Sidecar Startup Race Condition

**What goes wrong:** The FastAPI app or Temporal worker container starts before the Cloud SQL Auth Proxy sidecar is ready, causing DB connection failures on pod startup. The app crashes or enters a restart loop.
**Why it happens:** Standard Kubernetes containers in a pod start concurrently with no ordering guarantees. The proxy needs time to establish its IAM-authenticated tunnel.
**Consequences:** Intermittent pod startup failures, CrashLoopBackOff, flaky deployments.
**Prevention:** Use Kubernetes **native sidecar containers** (available since K8s 1.28, GA in 1.29). Declare the Cloud SQL Auth Proxy as an `initContainer` with `restartPolicy: Always` -- this makes it a true sidecar that starts and becomes ready before regular containers. GKE Autopilot on recent versions supports this.
**Detection:** Pods in CrashLoopBackOff with "connection refused" errors to `127.0.0.1:5432`.
**Confidence:** HIGH -- well-documented in [cloud-sql-proxy#2063](https://github.com/GoogleCloudPlatform/cloud-sql-proxy/issues/2063).
**Phase:** Workload deployment (Phase 2). Critical for both `vici-app` and `vici-temporal-worker`.

### Pitfall 3: Cloud SQL Auth Proxy Sidecar Blocks Job Completion

**What goes wrong:** The Alembic migration Job runs, completes successfully, but the pod never terminates because the Cloud SQL Auth Proxy sidecar keeps running.
**Why it happens:** Sidecars have no awareness of the main container exiting. The proxy stays alive, Kubernetes sees the pod as still running, and the Job never reaches `Completed`.
**Consequences:** Migration jobs hang indefinitely. CD pipeline blocks waiting for job completion.
**Prevention:** Two options: (1) Use native sidecar containers (K8s 1.28+) which terminate automatically when all regular containers exit. (2) If native sidecars are unavailable, use the proxy's `--quitquitquit` endpoint -- have the migration container send a POST to `localhost:9091/quitquitquit` on exit.
**Detection:** Job pods stuck in `Running` state with exit code 0 on the main container.
**Confidence:** HIGH -- this is one of the most reported Cloud SQL Auth Proxy issues.
**Phase:** Migration job setup (Phase 2).

### Pitfall 4: External Secrets Operator Bootstrap Ordering

**What goes wrong:** ESO needs Workload Identity to authenticate to Secret Manager. Workload Identity requires the K8s ServiceAccount to be annotated. The ESO Helm chart or Pulumi resource may try to create ExternalSecrets before the ServiceAccount binding, SecretStore, or even the ESO operator itself is ready.
**Why it happens:** Pulumi deploys resources concurrently by default. If the ExternalSecret is created before the ClusterSecretStore is ready, or the ClusterSecretStore before ESO's webhook is running, resources fail silently or error out.
**Consequences:** Pods start with missing secrets. App crashes or connects to wrong services. Secrets appear empty.
**Prevention:**
1. Deploy in strict order via Pulumi `depends_on`: GCP SA + IAM bindings -> K8s SA annotation -> ESO Helm release -> ClusterSecretStore -> ExternalSecrets -> App deployments.
2. Use `ClusterSecretStore` (not namespace-scoped `SecretStore`) to avoid per-namespace bootstrap.
3. Set `refreshInterval` on ExternalSecrets to catch eventual consistency (30s is reasonable).
**Detection:** `kubectl get externalsecret` shows `SecretSyncedError` or the target K8s Secret does not exist.
**Confidence:** MEDIUM -- synthesized from multiple practitioner reports, not one canonical source.
**Phase:** Secrets infrastructure (Phase 1 or early Phase 2). Must be solved before any workload deployment.

### Pitfall 5: Temporal Helm Chart on GKE Autopilot -- Privileged Containers Blocked

**What goes wrong:** The default Temporal Helm chart bundles Elasticsearch with a `configure-sysctl` init container that requires privileged mode. GKE Autopilot rejects privileged containers outright.
**Why it happens:** Autopilot enforces a strict security posture -- no privileged pods, no host-level access.
**Consequences:** Temporal server deployment fails entirely. Error: "container configure-sysctl is privileged; not allowed in Autopilot."
**Prevention:** Deploy Temporal **without bundled Elasticsearch**. Set `elasticsearch.enabled: false` in Helm values. For visibility/search, either skip advanced visibility initially or use a managed Elasticsearch/OpenSearch outside the cluster.
**Detection:** Pod creation fails immediately with Autopilot admission webhook rejection.
**Confidence:** HIGH -- confirmed via [Temporal Community Forum](https://community.temporal.io/t/issues-deploying-temporal-on-google-kubernetes-engine-autopilot-mode/8490).
**Phase:** Temporal deployment (Phase 2). Architecture decision needed upfront.

## Moderate Pitfalls

### Pitfall 6: Autopilot Resource Request Minimums Inflate Costs

**What goes wrong:** Autopilot enforces minimum resource requests (currently 250m CPU, 512Mi memory per container). Small utility containers (sidecars, init containers) get bumped up to minimums. You are billed on requests, not usage.
**Prevention:** Be deliberate about container count per pod. Each container in a pod costs at least the minimum. Consolidate where possible. Audit requests with `kubectl describe pod` and compare to actual usage.
**Confidence:** HIGH -- [documented by Google](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-resource-requests).
**Phase:** All phases. Budget planning should account for per-container minimums.

### Pitfall 7: Autopilot DaemonSet Restrictions Affect OTel Collector

**What goes wrong:** DaemonSets on Autopilot are restricted -- they cannot use hostPath volumes, privileged mode, or host networking. Standard OTel Collector DaemonSet configs may include hostPath for log collection.
**Prevention:** Use the OTel Collector in **Deployment mode** (not DaemonSet) or as a **sidecar** via the OpenTelemetry Operator. For trace collection (your primary use case with Jaeger), a Deployment-mode collector receiving OTLP over gRPC is simpler and avoids DaemonSet restrictions entirely. Reserve DaemonSet mode for node-level metrics only if needed later.
**Detection:** DaemonSet created but no pods scheduled; events show Autopilot admission rejection.
**Confidence:** MEDIUM -- based on Autopilot partner docs and OTel Operator docs.
**Phase:** Observability setup (Phase 3).

### Pitfall 8: Temporal Worker HPA Based on CPU/Memory is Misleading

**What goes wrong:** You set up HPA for Temporal workers on CPU utilization. Workers spend most time waiting on external I/O (API calls, DB), so CPU stays low even when task queues are backed up. HPA never scales up.
**Prevention:** Scale Temporal workers based on **custom metrics** -- specifically Temporal SDK metrics like `temporal_activity_schedule_to_start_latency` or task queue depth. Use Prometheus Adapter to expose these to the HPA. Alternatively, use a fixed replica count initially and tune later.
**Confidence:** HIGH -- [Temporal's own guidance](https://temporal.io/blog/tips-for-running-temporal-on-kubernetes).
**Phase:** Autoscaling tuning (Phase 3 or later). Start with fixed replicas.

### Pitfall 9: Pulumi State Backend Choice Affects CI/CD Reliability

**What goes wrong:** Using the default Pulumi Cloud backend without org-level state locking, or using a GCS self-managed backend without proper locking, leads to concurrent `pulumi up` runs corrupting state.
**Prevention:** Use **Pulumi Cloud** (app.pulumi.com) as the state backend -- it provides built-in state locking, audit trail, and secrets encryption. It is free for individual use and handles concurrency safely. If you must self-manage, use GCS with state locking enabled. Never use local filesystem backend in CI.
**Confidence:** MEDIUM -- based on Pulumi docs and general IaC best practices.
**Phase:** CI/CD pipeline setup (Phase 1).

### Pitfall 10: Workload Identity Propagation Delay

**What goes wrong:** After creating the IAM binding between a K8s ServiceAccount and a GCP ServiceAccount, pods using that SA still get 403 errors for several minutes.
**Prevention:** IAM bindings can take up to 7 minutes to propagate. In CI/CD, add a verification step (e.g., deploy a test pod that calls `gcloud auth list`) before deploying workloads. In Pulumi, add explicit `depends_on` and consider a small sleep or retry in the CD pipeline after IAM changes.
**Detection:** Pods log "Permission denied" or "403 Forbidden" on GCP API calls despite correct IAM configuration.
**Confidence:** MEDIUM -- well-known GCP IAM behavior but timing varies.
**Phase:** Identity setup (Phase 1).

## Minor Pitfalls

### Pitfall 11: Pulumi `ignoreChanges` Needed for Autopilot-Managed Fields

**What goes wrong:** Pulumi detects drift on fields that Autopilot manages (VPA settings, node pool configs, resource adjustments) and proposes unwanted updates every run.
**Prevention:** Add `ignore_changes` for: `vertical_pod_autoscaling`, `node_pool`, `node_config`, `initial_node_count`.
**Confidence:** HIGH -- multiple Pulumi community reports.
**Phase:** IaC foundation (Phase 1).

### Pitfall 12: Helm Chart Version Mismatch with Temporal Server

**What goes wrong:** Using Temporal Server 1.30+ with Helm chart below 0.73.1 causes deployment failures due to breaking changes in admin-tools images.
**Prevention:** Pin compatible versions. Check the [Temporal Helm chart repo](https://github.com/temporalio/helm-charts) compatibility matrix before upgrading.
**Confidence:** HIGH -- documented in Temporal Helm chart README.
**Phase:** Temporal deployment (Phase 2).

### Pitfall 13: Autopilot HPA and VPA Conflict

**What goes wrong:** Setting both HPA and VPA on the same resource with overlapping metrics (e.g., both on CPU) causes oscillating scale decisions.
**Prevention:** Use HPA for horizontal scaling on CPU/custom metrics. Let Autopilot's built-in VPA handle vertical sizing. Do not deploy a separate VPA resource for HPA-managed workloads.
**Confidence:** HIGH -- documented GKE best practice.
**Phase:** Autoscaling (Phase 3).

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Pulumi IaC foundation | Cluster replacement on drift (#1) | Explicit `dns_config`, `ignore_changes` |
| Pulumi IaC foundation | State backend concurrency (#9) | Use Pulumi Cloud backend |
| Pulumi IaC foundation | Autopilot-managed field drift (#11) | `ignore_changes` on VPA, node config |
| Workload Identity | Propagation delay (#10) | Verification step, retry logic |
| External Secrets | Bootstrap ordering (#4) | Strict `depends_on` chain in Pulumi |
| Cloud SQL Auth Proxy | Startup race (#2), Job hang (#3) | Native sidecar containers (K8s 1.28+) |
| Temporal server | Privileged container rejection (#5) | Disable bundled Elasticsearch |
| Temporal server | Helm version compat (#12) | Pin compatible versions |
| Temporal workers | CPU-based HPA misleading (#8) | Custom metrics or fixed replicas |
| OTel collector | DaemonSet restrictions (#7) | Deployment mode, not DaemonSet |
| Cost management | Container minimum inflation (#6) | Audit container count per pod |
| Autoscaling | HPA/VPA conflict (#13) | Separate metric dimensions |

## Sources

- [pulumi/pulumi-gcp#1170 - Cluster replacement](https://github.com/pulumi/pulumi-gcp/issues/1170)
- [cloud-sql-proxy#2063 - Sidecar ordering](https://github.com/GoogleCloudPlatform/cloud-sql-proxy/issues/2063)
- [Temporal Community - GKE Autopilot issues](https://community.temporal.io/t/issues-deploying-temporal-on-google-kubernetes-engine-autopilot-mode/8490)
- [Temporal - Tips for K8s](https://temporal.io/blog/tips-for-running-temporal-on-kubernetes)
- [GKE Autopilot resource requests](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-resource-requests)
- [GKE Autopilot overview](https://docs.google.com/kubernetes-engine/docs/concepts/autopilot-overview)
- [External Secrets Operator - GCP provider](https://external-secrets.io/latest/provider/google-secrets-manager/)
- [Pulumi state and backends](https://www.pulumi.com/docs/iac/concepts/state-and-backends/)
- [Temporal Helm charts](https://github.com/temporalio/helm-charts)
