# Technology Stack: GKE Migration

**Project:** Vici GKE Migration
**Researched:** 2026-04-04
**Scope:** Infrastructure tooling only -- no application stack changes

## Recommended Stack

### IaC Core (Pulumi Python)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `pulumi` | `>=3.x` (latest) | IaC runtime | Project constraint; Python-native IaC |
| `pulumi-gcp` | `9.16.0` | GCP resource provisioning | Latest v9 series; covers GKE Autopilot, Cloud SQL, Secret Manager, Artifact Registry, IAM |
| `pulumi-kubernetes` | `4.28.0` | K8s resource provisioning | Deploys Deployments, Services, Jobs, Ingress, HPA, Helm charts from Pulumi |
| `pulumi-docker-build` | `0.x` (latest) | Build + push images in Pulumi | Preferred over `pulumi-docker` for multi-stage builds; uses BuildKit natively |

**Note:** `pulumi-docker-build` is the newer replacement for `pulumi-docker`'s image building. However, for this project the CD pipeline builds images via `docker build` in GitHub Actions and pushes to Artifact Registry directly -- Pulumi only references the image URI. So `pulumi-docker-build` is **not needed**. The CD pipeline handles the build step.

### GKE Autopilot (via `pulumi-gcp`)

| Resource Type | Pulumi Class | Purpose |
|---------------|-------------|---------|
| GKE Autopilot Cluster | `gcp.container.Cluster` with `enable_autopilot=True` | Managed K8s cluster, no node pools to manage |
| Cloud SQL Postgres 16 | `gcp.sql.DatabaseInstance` | Managed Postgres per environment |
| Cloud SQL Database | `gcp.sql.Database` | Database within the instance |
| Cloud SQL User | `gcp.sql.User` | IAM-authenticated DB user |
| Artifact Registry | `gcp.artifactregistry.Repository` | Docker image storage (replaces GCR) |
| Secret Manager Secret | `gcp.secretmanager.Secret` + `SecretVersion` | Store external secrets (Twilio, OpenAI, Pinecone, Braintrust, Temporal) |
| IAM Service Account | `gcp.serviceaccount.Account` | Per-workload GCP identity |
| IAM Binding | `gcp.serviceaccount.IAMBinding` | Workload Identity KSA-to-GSA binding |
| IAM Member | `gcp.projects.IAMMember` | Grant roles (Cloud SQL Client, Secret Manager Accessor) |

**Key GKE Autopilot config:**
```python
cluster = gcp.container.Cluster("vici-cluster",
    name=f"vici-{env}",
    location="us-central1",  # regional, not zonal
    enable_autopilot=True,
    ip_allocation_policy=gcp.container.ClusterIpAllocationPolicyArgs(),  # required for Autopilot
    release_channel=gcp.container.ClusterReleaseChannelArgs(
        channel="REGULAR",
    ),
)
```

### Kubernetes Add-ons (deployed via Pulumi Helm/K8s resources)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| External Secrets Operator | Helm chart `0.12.x` (app `v0.12.x`) | Sync GCP Secret Manager to K8s Secrets | De facto standard for external secret sync; GCP SecretManager provider built-in |
| cert-manager | `v1.20.0` | TLS certificate automation via Let's Encrypt | Standard K8s TLS solution; Ingress integration |
| Cloud SQL Auth Proxy | `v2.21.1` (image: `gcr.io/cloud-sql-connectors/cloud-sql-auth-proxy:2.21.1`) | Sidecar for IAM-authed DB connections | Google-maintained; Workload Identity native; no VPC peering needed |

**Confidence note on ESO version:** The Helm chart versioning (0.12.x) and app versioning (v0.12.x vs v2.x) are confusing in ESO's ecosystem. The Helm chart `external-secrets` from `https://charts.external-secrets.io` should be pinned to whatever `helm search repo external-secrets` returns as latest stable. MEDIUM confidence on exact version -- verify at install time.

### GitHub Actions CD Additions

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `google-github-actions/auth` | `v2` | Workload Identity Federation for CI | Keyless GCP auth from GitHub Actions; no service account key files |
| `google-github-actions/setup-gcloud` | `v2` | gcloud CLI in CI | Needed for `gcloud container clusters get-credentials` and Artifact Registry auth |
| `pulumi/actions` | `v6` | Run `pulumi up` in CI | Official Pulumi GitHub Action; supports stack selection, preview, up |
| `docker/build-push-action` | `v6` | Build and push to Artifact Registry | Multi-platform builds, layer caching, direct push |

### CLI Tools (developer machines + CI)

| Tool | Version | Purpose |
|------|---------|---------|
| `gcloud` CLI | latest | GKE credentials, Artifact Registry auth, Secret Manager admin |
| `kubectl` | matches GKE server version | K8s resource inspection, debugging |
| `pulumi` CLI | `>=3.x` | IaC operations |
| `helm` | `>=3.x` | Chart inspection (Pulumi handles actual deployment) |

## What NOT to Add

| Technology | Why Not |
|------------|---------|
| Terraform | Project constraint: Pulumi Python only |
| ArgoCD / Flux | Out of scope per PROJECT.md; direct `pulumi up` in CI is sufficient for v1 |
| `pulumi-gcp-native` (Google Native provider) | Deprecated in favor of `pulumi-gcp` Classic; Classic has better stability and community support |
| Istio / Linkerd | No service mesh needed; simple Ingress + internal ClusterIP services suffice |
| NGINX Ingress Controller | GKE Autopilot provides GKE-managed Ingress (backed by Google Cloud Load Balancer) out of the box |
| Crossplane | Overkill; Pulumi already manages GCP resources |
| Sealed Secrets | External Secrets Operator is the chosen approach per PROJECT.md |
| VPC peering for Cloud SQL | Cloud SQL Auth Proxy sidecar eliminates this need |
| Static service account keys | Workload Identity Federation eliminates this need |

## Installation

### Pulumi project (`infra/requirements.txt` or `infra/pyproject.toml`)

```
pulumi>=3.0.0,<4.0.0
pulumi-gcp>=9.16.0,<10.0.0
pulumi-kubernetes>=4.28.0,<5.0.0
```

### Helm charts (deployed via Pulumi `kubernetes.helm.v3.Release`)

```python
# External Secrets Operator
kubernetes.helm.v3.Release("external-secrets",
    chart="external-secrets",
    repository_opts=kubernetes.helm.v3.RepositoryOptsArgs(
        repo="https://charts.external-secrets.io",
    ),
    namespace="external-secrets",
    create_namespace=True,
)

# cert-manager
kubernetes.helm.v3.Release("cert-manager",
    chart="cert-manager",
    version="v1.20.0",
    repository_opts=kubernetes.helm.v3.RepositoryOptsArgs(
        repo="https://charts.jetstack.io",
    ),
    namespace="cert-manager",
    create_namespace=True,
    values={"crds": {"enabled": True}},
)
```

## Confidence Assessment

| Component | Confidence | Notes |
|-----------|------------|-------|
| `pulumi-gcp` v9.16.0 | HIGH | Verified via Pulumi Registry and PyPI |
| `pulumi-kubernetes` v4.28.0 | HIGH | Verified via PyPI |
| GKE Autopilot via `enable_autopilot=True` | HIGH | Verified via Pulumi Registry docs |
| cert-manager v1.20.0 | HIGH | Verified via cert-manager.io and ArtifactHub |
| Cloud SQL Auth Proxy v2.21.1 | MEDIUM | Version from Google docs; verify against GitHub releases at deploy time |
| External Secrets Operator version | MEDIUM | Helm chart vs app versioning is unclear; pin at install time |
| GitHub Actions action versions | MEDIUM | v2/v6 tags verified via search; confirm exact latest at pipeline build time |

## Sources

- [Pulumi GCP Registry](https://www.pulumi.com/registry/packages/gcp/)
- [Pulumi GCP Cluster Resource](https://www.pulumi.com/registry/packages/gcp/api-docs/container/cluster/)
- [Pulumi Kubernetes Registry](https://www.pulumi.com/registry/packages/kubernetes/)
- [External Secrets Operator - GitHub](https://github.com/external-secrets/external-secrets/releases)
- [cert-manager Releases](https://cert-manager.io/docs/releases/)
- [Cloud SQL Auth Proxy - GitHub](https://github.com/GoogleCloudPlatform/cloud-sql-proxy/releases)
- [GCP 9.0 Migration Guide](https://www.pulumi.com/registry/packages/gcp/how-to-guides/9-0-migration/)
