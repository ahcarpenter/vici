# Phase 1: GKE Cluster and Networking Baseline — Research

**Researched:** 2026-04-04
**Domain:** Pulumi Python / GKE Autopilot / GCS backend / Artifact Registry
**Confidence:** HIGH

---

## Summary

Phase 1 provisions the entire infrastructure foundation from a single `pulumi up --stack dev` command: a GKE Autopilot cluster with Workload Identity, required Kubernetes namespaces, and an Artifact Registry repository. All architecture decisions are locked (Pulumi Python, GKE Autopilot, GCS backend, Workload Identity Federation, us-central1, three mirrored environments).

The primary technical challenge in this phase is idempotency. GKE Autopilot silently mutates several cluster fields post-creation (notably `dns_config` and `vertical_pod_autoscaling`), causing Pulumi to propose cluster replacement on the second run. The fix is two-pronged: explicitly set `dns_config` in the resource definition AND add volatile fields to `ignore_changes`. Both must be done at initial cluster creation — they cannot be applied retroactively without a replacement cycle.

The secondary challenge is bootstrapping: the GCS state buckets must exist before `pulumi up` can run (Pulumi cannot create its own state backend). A small manual bootstrap procedure (five gcloud commands) is required once per environment before the IaC takes over.

**Primary recommendation:** Use `pulumi-gcp` 9.18.0 (latest as of 2026-04-04), set `dns_config` explicitly on the cluster resource, and add `["vertical_pod_autoscaling", "node_config", "node_pool", "initial_node_count"]` to `ignore_changes`. Do NOT add `dns_config` to `ignore_changes` — set it explicitly instead so future DNS changes remain manageable.

---

## Project Constraints (from CLAUDE.md / AGENTS.md)

The following directives from AGENTS.md apply to the `infra/` Pulumi codebase:

- Organize code by domain, not by file type (maps to: one file per component, not `all_resources.py`)
- Apply SOLID principles and DRY relentlessly
- All magic numbers must be constantized (port numbers, CIDR blocks, shard counts)
- Prefer explicit module imports: `from infra.components import cluster as cluster_component`
- Database naming: `lower_case_snake`, singular table names — not directly applicable to IaC but apply to any K8s resource names
- Domain language: use canonical GKE/GCP terms (e.g., "workload pool" not "identity pool", "release channel" not "upgrade channel")

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pulumi` | `3.229.0` | IaC runtime and CLI | Latest stable; project constraint |
| `pulumi-gcp` | `9.18.0` | GCP resource provisioning (GKE, IAM, Artifact Registry, GCS) | Latest v9 series; verified on PyPI 2026-04-04 |
| `pulumi-kubernetes` | `4.28.0` | Kubernetes namespace provisioning | Creates namespaces after cluster is ready |

**Version verification (run on 2026-04-04):**
```
pulumi       3.229.0  (pip3 index versions)
pulumi-gcp   9.18.0   (pip3 index versions)
```

### Installation

`infra/requirements.txt`:
```
pulumi>=3.229.0,<4.0.0
pulumi-gcp>=9.18.0,<10.0.0
pulumi-kubernetes>=4.28.0,<5.0.0
```

---

## Architecture Patterns

### Recommended Project Structure

```
infra/
├── __main__.py              # Entry point — composes all components
├── Pulumi.yaml              # Project definition + backend URL
├── Pulumi.dev.yaml          # Stack config: dev values
├── Pulumi.staging.yaml      # Stack config: staging values
├── Pulumi.prod.yaml         # Stack config: prod values
├── requirements.txt         # Python dependencies
├── config.py                # Typed config wrapper (reads stack values)
└── components/
    ├── cluster.py           # GKE Autopilot cluster resource
    ├── registry.py          # Artifact Registry repository + IAM
    ├── namespaces.py        # Kubernetes namespace resources
    └── identity.py          # Workload Identity: GCP SAs + IAM bindings
```

This is the canonical Pulumi "single program, multiple stacks" pattern. All per-environment differences are config values in `Pulumi.<env>.yaml`. The program itself contains zero environment conditionals.

### Pattern 1: GCS Backend Configuration

**What:** The Pulumi backend is specified in `Pulumi.yaml` at the project level. Each environment gets its own GCS bucket. Since `Pulumi.yaml` cannot interpolate stack names into the backend URL, the standard approach is to use `PULUMI_BACKEND_URL` as an environment variable in CI, overriding the project default.

**When to use:** Always in CI. Local dev can use `pulumi login gs://vici-pulumi-state-dev` directly.

`infra/Pulumi.yaml`:
```yaml
name: vici-infra
description: Vici GKE infrastructure — all environments
runtime: python
backend:
  url: gs://vici-pulumi-state-dev   # default for local dev; CI overrides via PULUMI_BACKEND_URL
```

CI/CD pipeline (one per environment):
```bash
# dev
export PULUMI_BACKEND_URL="gs://vici-pulumi-state-dev"
pulumi up --stack dev --yes

# staging
export PULUMI_BACKEND_URL="gs://vici-pulumi-state-staging"
pulumi up --stack staging --yes

# prod
export PULUMI_BACKEND_URL="gs://vici-pulumi-state-prod"
pulumi up --stack prod --yes
```

**Confidence:** HIGH — verified via Pulumi state/backends docs and `PULUMI_BACKEND_URL` env var documentation.

### Pattern 2: Stack Config Files

**What:** Stack config files store per-environment values. The Python program reads them via `pulumi.Config()`.

`infra/Pulumi.dev.yaml`:
```yaml
config:
  gcp:project: vici-dev-PROJECT_ID
  gcp:region: us-central1
  vici-infra:env: dev
  vici-infra:cluster_name: vici-dev
  vici-infra:registry_name: vici-images
```

`infra/Pulumi.staging.yaml`:
```yaml
config:
  gcp:project: vici-staging-PROJECT_ID
  gcp:region: us-central1
  vici-infra:env: staging
  vici-infra:cluster_name: vici-staging
  vici-infra:registry_name: vici-images
```

`infra/Pulumi.prod.yaml`:
```yaml
config:
  gcp:project: vici-prod-PROJECT_ID
  gcp:region: us-central1
  vici-infra:env: prod
  vici-infra:cluster_name: vici-prod
  vici-infra:registry_name: vici-images
```

`infra/config.py`:
```python
import pulumi

cfg = pulumi.Config()
gcp_cfg = pulumi.Config("gcp")

ENV = cfg.require("env")                    # "dev" | "staging" | "prod"
CLUSTER_NAME = cfg.require("cluster_name")  # "vici-dev" | "vici-staging" | "vici-prod"
REGISTRY_NAME = cfg.require("registry_name")
PROJECT_ID = gcp_cfg.require("project")
REGION = gcp_cfg.get("region") or "us-central1"
```

### Pattern 3: GKE Autopilot Cluster (Idempotent)

This is the most critical pattern. Two rules must both be satisfied:
1. Set `dns_config` explicitly (prevents GCP defaults from causing drift)
2. Add `vertical_pod_autoscaling`, `node_config`, `node_pool`, `initial_node_count` to `ignore_changes` (prevents Autopilot-managed fields from causing replacement)

`infra/components/cluster.py`:
```python
import pulumi
import pulumi_gcp as gcp
from pulumi import ResourceOptions
from infra.config import PROJECT_ID, REGION, CLUSTER_NAME, ENV

# Release channel options: RAPID, REGULAR, STABLE
# REGULAR is recommended for non-prod dev. STABLE for prod.
RELEASE_CHANNEL = "REGULAR" if ENV != "prod" else "STABLE"

# Volatile fields that Autopilot manages post-creation.
# Adding to ignore_changes prevents Pulumi from proposing
# replace on second run.
AUTOPILOT_IGNORE_FIELDS = [
    "vertical_pod_autoscaling",
    "node_config",
    "node_pool",
    "initial_node_count",
]

cluster = gcp.container.Cluster(
    "vici-cluster",
    name=CLUSTER_NAME,
    location=REGION,                    # regional (not zonal) — required for Autopilot HA
    project=PROJECT_ID,
    enable_autopilot=True,

    # Required for Autopilot — GKE allocates pod/service CIDRs automatically.
    # Empty args object is sufficient; GKE fills in CIDRs.
    ip_allocation_policy=gcp.container.ClusterIpAllocationPolicyArgs(),

    # Explicitly set DNS config to prevent GCP from silently applying defaults
    # that Pulumi then detects as drift and proposes cluster replacement.
    # Source: github.com/pulumi/pulumi-gcp/issues/1170
    dns_config=gcp.container.ClusterDnsConfigArgs(
        cluster_dns="CLOUD_DNS",
        cluster_dns_scope="CLUSTER_SCOPE",
        cluster_dns_domain="cluster.local",
    ),

    # Workload Identity: enables pod-to-GCP IAM binding without static keys.
    # Format: "<project_id>.svc.id.goog"
    workload_identity_config=gcp.container.ClusterWorkloadIdentityConfigArgs(
        workload_pool=f"{PROJECT_ID}.svc.id.goog",
    ),

    release_channel=gcp.container.ClusterReleaseChannelArgs(
        channel=RELEASE_CHANNEL,
    ),

    # Prevent accidental cluster deletion via Pulumi.
    deletion_protection=True,

    opts=ResourceOptions(
        ignore_changes=AUTOPILOT_IGNORE_FIELDS,
    ),
)
```

**Note on `deletion_protection`:** Set to `True` for safety. To destroy the cluster intentionally, first set it to `False` with a targeted update, then run `pulumi destroy`. This prevents accidental environment wipe.

### Pattern 4: Kubernetes Provider from Cluster Outputs

After the cluster is created, the Kubernetes provider must be initialized with a kubeconfig constructed from cluster outputs. This uses `pulumi.Output.all()` to combine async outputs.

```python
import pulumi
import pulumi_kubernetes as k8s
from pulumi import Output

def make_kubeconfig(cluster):
    """
    Constructs a kubeconfig that uses gke-gcloud-auth-plugin for authentication.
    This is the modern GKE approach (plugin required: gke-gcloud-auth-plugin).
    """
    return Output.all(
        cluster.name,
        cluster.endpoint,
        cluster.master_auth,
        cluster.location,
    ).apply(
        lambda args: {
            "apiVersion": "v1",
            "clusters": [{
                "cluster": {
                    "certificate-authority-data": args[2]["cluster_ca_certificate"],
                    "server": f"https://{args[1]}",
                },
                "name": args[0],
            }],
            "contexts": [{
                "context": {
                    "cluster": args[0],
                    "user": args[0],
                },
                "name": args[0],
            }],
            "current-context": args[0],
            "kind": "Config",
            "users": [{
                "name": args[0],
                "user": {
                    "exec": {
                        "apiVersion": "client.authentication.k8s.io/v1beta1",
                        "command": "gke-gcloud-auth-plugin",
                        "installHint": "Install gke-gcloud-auth-plugin: gcloud components install gke-gcloud-auth-plugin",
                        "provideClusterInfo": True,
                    }
                },
            }],
        }
    )

k8s_provider = k8s.Provider(
    "k8s-provider",
    kubeconfig=make_kubeconfig(cluster),
    opts=ResourceOptions(depends_on=[cluster]),
)
```

**Dependency note:** `depends_on=[cluster]` is required. Without it, Pulumi may attempt to create namespaces before the cluster API server is ready.

### Pattern 5: Kubernetes Namespaces

```python
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

# Phase 1 required namespaces (INFRA-06)
REQUIRED_NAMESPACES = [
    "vici",
    "temporal",
    "observability",
    "cert-manager",
    "external-secrets",
]

namespaces = {
    name: k8s.core.v1.Namespace(
        f"ns-{name}",
        metadata=k8s.meta.v1.ObjectMetaArgs(name=name),
        opts=ResourceOptions(
            provider=k8s_provider,
            depends_on=[cluster],
        ),
    )
    for name in REQUIRED_NAMESPACES
}
```

### Pattern 6: Artifact Registry Repository

```python
import pulumi_gcp as gcp
from infra.config import PROJECT_ID, REGION, REGISTRY_NAME

registry = gcp.artifactregistry.Repository(
    "vici-registry",
    project=PROJECT_ID,
    location=REGION,
    repository_id=REGISTRY_NAME,
    format="DOCKER",
    description="Vici application Docker images",
)

# CI service account for image pushes from GitHub Actions
ci_sa = gcp.serviceaccount.Account(
    "ci-push-sa",
    project=PROJECT_ID,
    account_id="vici-ci-push",
    display_name="Vici CI — Artifact Registry push",
)

# Grant push access to CI service account
registry_push_iam = gcp.artifactregistry.RepositoryIamMember(
    "ci-push-iam",
    project=PROJECT_ID,
    location=REGION,
    repository=registry.repository_id,
    role="roles/artifactregistry.writer",
    member=ci_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)
```

### Pattern 7: Workload Identity IAM Binding

For each workload that needs GCP API access, bind the Kubernetes ServiceAccount to a GCP ServiceAccount. This is required by INFRA-03 but the actual KSA annotation happens in the application namespace setup (Phase 2). The GCP SA creation and IAM project role bindings are Phase 1 responsibilities.

```python
import pulumi_gcp as gcp

# Example: app service account (repeated per workload in later phases)
app_gsa = gcp.serviceaccount.Account(
    "app-gsa",
    project=PROJECT_ID,
    account_id="vici-app",
    display_name="Vici FastAPI application GSA",
)

# Workload Identity binding: K8s SA -> GCP SA
# This allows pods in vici/vici-app KSA to impersonate the GCP SA.
wi_binding = gcp.serviceaccount.IAMBinding(
    "app-wi-binding",
    service_account_id=app_gsa.name,
    role="roles/iam.workloadIdentityUser",
    members=[
        # Format: "serviceAccount:<project>.svc.id.goog[<namespace>/<ksa-name>]"
        pulumi.Output.concat(
            "serviceAccount:",
            PROJECT_ID,
            ".svc.id.goog[vici/vici-app]",
        )
    ],
)
```

### Anti-Patterns to Avoid

- **Anti-pattern: `ignore_changes=["dns_config"]`** — Do not add dns_config to ignore_changes. Set it explicitly instead. Ignoring it prevents any future DNS change from being applied; setting it explicitly lets Pulumi manage it intentionally.
- **Anti-pattern: `location="us-central1-a"` (zonal)** — Autopilot requires a regional location (`us-central1`), not a zonal one (`us-central1-a`). Zonal Autopilot is not supported.
- **Anti-pattern: single GCS bucket for all environments** — Use one bucket per environment. This prevents a staging `pulumi up` from seeing dev state, and makes bucket-level IAM cleaner.
- **Anti-pattern: hardcoding project IDs in Python** — All project IDs live in stack config files, not in Python code. The program reads them via `pulumi.Config("gcp").require("project")`.

---

## Resource Reference

| Resource | Pulumi Class | Key Arguments |
|----------|-------------|---------------|
| GKE Autopilot Cluster | `gcp.container.Cluster` | `enable_autopilot=True`, `location` (regional), `ip_allocation_policy`, `dns_config`, `workload_identity_config`, `release_channel`, `deletion_protection` |
| Artifact Registry Repo | `gcp.artifactregistry.Repository` | `location`, `repository_id`, `format="DOCKER"` |
| Registry IAM | `gcp.artifactregistry.RepositoryIamMember` | `repository`, `role`, `member` |
| GCP Service Account | `gcp.serviceaccount.Account` | `account_id`, `display_name`, `project` |
| Workload Identity Binding | `gcp.serviceaccount.IAMBinding` | `service_account_id`, `role="roles/iam.workloadIdentityUser"`, `members` |
| K8s Namespace | `k8s.core.v1.Namespace` | `metadata.name`, `opts.provider` |
| K8s Provider | `k8s.Provider` | `kubeconfig` (Output from cluster outputs) |

---

## Pre-requisites (Manual Bootstrap Steps)

These steps must be performed ONCE per environment BEFORE `pulumi up` can run. They cannot be automated by Pulumi because Pulumi needs its state bucket to already exist.

### Step 1: Enable Required GCP APIs

```bash
gcloud services enable \
  container.googleapis.com \
  artifactregistry.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  --project=PROJECT_ID
```

**Required APIs:**
| API | Service Name | Why |
|-----|-------------|-----|
| Kubernetes Engine | `container.googleapis.com` | GKE cluster creation |
| Artifact Registry | `artifactregistry.googleapis.com` | Docker image repository |
| Cloud Resource Manager | `cloudresourcemanager.googleapis.com` | IAM policy management |
| IAM | `iam.googleapis.com` | Service account creation |
| Secret Manager | `secretmanager.googleapis.com` | Needed in Phase 2; enable now to avoid second bootstrap |
| Cloud Storage | `storage.googleapis.com` | GCS state bucket |

### Step 2: Create GCS State Bucket

One bucket per environment. Enable versioning for state file history and recovery.

```bash
# dev
gsutil mb -p PROJECT_ID -l us-central1 gs://vici-pulumi-state-dev
gsutil versioning set on gs://vici-pulumi-state-dev

# staging
gsutil mb -p PROJECT_ID -l us-central1 gs://vici-pulumi-state-staging
gsutil versioning set on gs://vici-pulumi-state-staging

# prod
gsutil mb -p PROJECT_ID -l us-central1 gs://vici-pulumi-state-prod
gsutil versioning set on gs://vici-pulumi-state-prod
```

**Naming convention:** `vici-pulumi-state-{env}`. GCS bucket names are globally unique — if these names are taken, use `vici-{org}-pulumi-state-{env}`.

### Step 3: Authenticate Pulumi to GCS Backend

```bash
# For local dev (one-time per machine):
pulumi login gs://vici-pulumi-state-dev

# Or use application default credentials:
gcloud auth application-default login
export PULUMI_BACKEND_URL="gs://vici-pulumi-state-dev"
```

### Step 4: Install gke-gcloud-auth-plugin

Required on any machine that will run `kubectl` against GKE clusters or where Pulumi creates the kubernetes Provider.

```bash
gcloud components install gke-gcloud-auth-plugin
# or on Ubuntu/Debian:
apt-get install google-cloud-sdk-gke-gcloud-auth-plugin
```

### Step 5: Initialize Pulumi Stack

```bash
cd infra
pulumi stack init dev      # creates the dev stack in GCS backend
pulumi stack init staging
pulumi stack init prod
```

---

## Idempotency Analysis

This is the highest-risk area for Phase 1. GKE Autopilot mutates cluster state post-creation in ways that Pulumi detects as drift.

### Fields That Cause Drift / Replacement on Second Run

| Field | What GCP Does | Pulumi's Reaction | Fix |
|-------|--------------|-------------------|-----|
| `dns_config` | GCP applies `CLOUD_DNS`, `CLUSTER_SCOPE`, `cluster.local` defaults silently | Sees absence of field as removal; proposes cluster **replace** | Set explicitly in resource definition |
| `vertical_pod_autoscaling` | Autopilot enables VPA automatically | Sees enabled VPA as unexpected; proposes update or replace | Add to `ignore_changes` |
| `node_config` | Autopilot manages node config | Detects diff; may propose update | Add to `ignore_changes` |
| `node_pool` | Autopilot creates default node pool | Proposes removal of auto-created pool | Add to `ignore_changes` |
| `initial_node_count` | GCP sets this post-creation | Detects diff from code value | Add to `ignore_changes` |

**Source:** [pulumi/pulumi-gcp#1170](https://github.com/pulumi/pulumi-gcp/issues/1170) — confirmed HIGH confidence.

### Recommended `ignore_changes` List

```python
opts=ResourceOptions(
    ignore_changes=[
        "vertical_pod_autoscaling",
        "node_config",
        "node_pool",
        "initial_node_count",
    ],
)
```

**Do NOT include:** `dns_config` (set it explicitly instead), `workload_identity_config` (stable once set), `release_channel` (stable once set).

### Idempotency Verification Checklist

Before considering Phase 1 complete, run `pulumi up --stack dev` twice and confirm the second run shows:
```
Previewing update (dev)...
Resources:
    X unchanged
```
Zero proposed changes is the gate.

---

## Common Pitfalls

### Pitfall 1: Cluster Replacement on Second `pulumi up`

**What goes wrong:** `pulumi up` on second run proposes `replace` on the cluster resource.
**Root cause:** `dns_config` drift — GCP applied defaults that Pulumi sees as a requested removal.
**Prevention:** Set `dns_config` explicitly in the cluster resource (see Pattern 3 above).
**Detection:** `pulumi preview` shows `[replace]` next to the cluster resource before `pulumi up`.
**Source:** [pulumi/pulumi-gcp#1170](https://github.com/pulumi/pulumi-gcp/issues/1170)
**Confidence:** HIGH

### Pitfall 2: Kubernetes Provider Before Cluster is Ready

**What goes wrong:** Pulumi creates the `k8s.Provider` and namespace resources before the GKE API server is accessible, causing timeout errors.
**Root cause:** Pulumi parallelizes resource creation by default.
**Prevention:** `opts=ResourceOptions(depends_on=[cluster])` on both the Provider and all namespace resources.
**Detection:** Pulumi errors mentioning "connection refused" or "dial tcp" during namespace creation.
**Confidence:** HIGH

### Pitfall 3: Zonal vs Regional Location

**What goes wrong:** `location="us-central1-a"` fails or creates a Standard cluster instead of Autopilot.
**Root cause:** Autopilot requires a regional location. Zonal locations are for Standard clusters.
**Prevention:** Use `location="us-central1"` (the region, not a zone).
**Confidence:** HIGH — confirmed in GKE Autopilot docs.

### Pitfall 4: GCS Bucket Does Not Exist Before `pulumi up`

**What goes wrong:** `pulumi up` fails immediately with a backend error.
**Root cause:** Pulumi cannot create its own state backend.
**Prevention:** Run Step 2 (bucket creation) before any Pulumi operations.
**Confidence:** HIGH

### Pitfall 5: Missing `gke-gcloud-auth-plugin`

**What goes wrong:** Kubernetes provider fails to authenticate to the cluster with "exec plugin" error.
**Root cause:** Modern GKE clusters require the auth plugin; the old certificate-based auth is deprecated.
**Prevention:** Install `gke-gcloud-auth-plugin` on all machines running Pulumi (dev machines + CI runners).
**Confidence:** HIGH — GKE deprecated built-in auth in 1.26+.

### Pitfall 6: IAM Propagation Delay for Workload Identity

**What goes wrong:** Pods get 403 errors for up to 7 minutes after Workload Identity IAM bindings are created.
**Root cause:** GCP IAM bindings have eventual consistency — typically 1–7 minutes to propagate.
**Prevention:** In CI, add a verification step after IAM changes before deploying workloads. In Phase 1, this means not running any workload validation immediately after `pulumi up`.
**Confidence:** MEDIUM — well-known GCP behavior; timing varies.

### Pitfall 7: `deletion_protection=True` Blocks Teardown

**What goes wrong:** `pulumi destroy` fails with "deletion protection enabled."
**Root cause:** `deletion_protection=True` prevents accidental cluster destruction.
**Prevention (intentional teardown):** Set `deletion_protection=False`, run `pulumi up` to apply that change, then run `pulumi destroy`.
**Confidence:** HIGH — documented Pulumi/GCP behavior.

---

## Open Decisions

### OD-1: GCP Project Structure (one project vs three)

The REQUIREMENTS scope the cluster to `us-central1`. What is unclear is whether dev/staging/prod each have their own GCP project, or share one project with env-prefixed resource names.

- **Option A (recommended):** Three separate GCP projects (`vici-dev`, `vici-staging`, `vici-prod`). Cleaner IAM isolation. Each project has its own GCS state bucket. Stack config files each specify a different `gcp:project`.
- **Option B:** One GCP project, resource names prefixed with env (`vici-dev-cluster`, `vici-prod-cluster`). Cheaper (fewer project-level resources), but IAM is harder to isolate.

**Recommendation:** Option A (separate projects). The Pulumi program handles this transparently — project ID is just a config value.

**Impact on Phase 1:** The planner needs to decide this before writing the stack config files. The Python code is identical either way.

### OD-2: CI Service Account vs Workload Identity Federation for GitHub Actions

The INFRA-07 requirement says "CI service account has push access." This could mean:
- **Option A:** A GCP Service Account key file stored as a GitHub Actions secret (simple but uses static keys — contradicts WIF principle).
- **Option B (recommended):** Workload Identity Federation for GitHub Actions (keyless auth). The `google-github-actions/auth@v2` action supports this. Requires an additional WIF pool and provider resource in Pulumi.

**Recommendation:** Option B (WIF for GitHub Actions). This is consistent with the project's "no static keys" principle. The WIF pool/provider resource is ~10 lines of Pulumi Python and is standard for GCP + GitHub Actions.

**Impact on Phase 1:** If Option B is chosen, add a `gcp.iam.WorkloadIdentityPool` and `gcp.iam.WorkloadIdentityPoolProvider` to the Phase 1 Pulumi program. If Option A, create a service account key and store as GitHub secret.

### OD-3: Pulumi Passphrase for GCS Backend Secret Encryption

When using a self-managed GCS backend (not Pulumi Cloud), Pulumi uses a passphrase to encrypt secrets in state. This passphrase must be stored somewhere (CI environment variable, Secret Manager).

**Required:** Set `PULUMI_CONFIG_PASSPHRASE` as an environment variable in CI before any `pulumi up`. For local dev, set it in `.envrc` or shell profile.

**The planner should specify** where this passphrase is stored (GitHub Actions secret, GCP Secret Manager, developer `.env` file).

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Cluster replacement on second `pulumi up` (dns_config drift) | HIGH if not addressed | Critical — destroys all workloads | Set `dns_config` explicitly (Pattern 3) |
| GCS state bucket name collision (globally unique) | MEDIUM | Blocks bootstrap | Have fallback names ready (`vici-{initials}-pulumi-state-{env}`) |
| `gke-gcloud-auth-plugin` not installed in CI | MEDIUM | Blocks K8s namespace provisioning | Add install step to CI bootstrap or use Docker image with plugin pre-installed |
| IAM propagation delay causing flaky CI | MEDIUM | CI fails intermittently | Add explicit wait/retry after IAM changes |
| `deletion_protection=True` during first cluster bring-up if iteration is needed | LOW | Slows teardown during dev | Keep `deletion_protection=False` during initial development; flip to `True` when stable |
| Pulumi state lock contention (multiple engineers running `pulumi up`) | LOW | Concurrent update failure | GCS backend has locking; communicate before running; CI is the only automated runner |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python 3 | Pulumi runtime | Yes | 3.12.7 | — |
| `pulumi` CLI | All IaC operations | No — not installed | — | Install via `brew install pulumi` or `pip install pulumi` |
| `gcloud` CLI | Bootstrap, kubeconfig | No — not detected | — | Install Google Cloud SDK |
| `gke-gcloud-auth-plugin` | K8s Provider auth | Unknown | — | `gcloud components install gke-gcloud-auth-plugin` |

**Missing dependencies with no fallback:**
- `pulumi` CLI — must be installed before Phase 1 work begins
- `gcloud` CLI — must be installed for bootstrap steps and local cluster access

**Note:** `pulumi` and `gcloud` are not installed in this workspace's shell environment as detected. These are developer-machine prerequisites, not project code dependencies.

---

## Code Examples

### Complete `__main__.py` skeleton

```python
# infra/__main__.py
import pulumi
from components.cluster import cluster
from components.registry import registry, registry_push_iam
from components.namespaces import namespaces
from components.identity import app_gsa, wi_binding

# Export useful values for downstream consumers
pulumi.export("cluster_name", cluster.name)
pulumi.export("cluster_endpoint", cluster.endpoint)
pulumi.export("registry_url", registry.id.apply(
    lambda id: f"us-central1-docker.pkg.dev/{id}"
))
```

### Constructing Artifact Registry push URI

```python
# The full Docker image URI for pushing from CI:
# us-central1-docker.pkg.dev/<project>/<repo>/<image>:<tag>

registry_url = pulumi.Output.concat(
    "us-central1-docker.pkg.dev/",
    PROJECT_ID,
    "/",
    registry.repository_id,
)
pulumi.export("registry_url", registry_url)
```

### `pulumi preview` gate command (idempotency verification)

```bash
# After initial provisioning, verify no changes on second run:
pulumi preview --stack dev --expect-no-changes
# Exit code 1 if any changes are proposed — use as CI gate
```

---

## Sources

### Primary (HIGH confidence)
- [Pulumi GCP Cluster Resource Docs](https://www.pulumi.com/registry/packages/gcp/api-docs/container/cluster/) — resource arguments, Python syntax
- [Pulumi State and Backends](https://www.pulumi.com/docs/iac/concepts/state-and-backends/) — GCS backend URL format, `PULUMI_BACKEND_URL`
- [Pulumi Stack Config Docs](https://www.pulumi.com/docs/iac/concepts/config/) — `Pulumi.<env>.yaml` format, Python `Config` access
- [Pulumi Artifact Registry Resource](https://www.pulumi.com/registry/packages/gcp/api-docs/artifactregistry/repository/) — `gcp.artifactregistry.Repository` arguments
- [PyPI: pulumi-gcp](https://pypi.org/project/pulumi-gcp/) — version 9.18.0 confirmed latest
- [PyPI: pulumi](https://pypi.org/project/pulumi/) — version 3.229.0 confirmed latest

### Secondary (MEDIUM confidence)
- [pulumi/pulumi-gcp#1170](https://github.com/pulumi/pulumi-gcp/issues/1170) — dns_config replacement issue; fix pattern verified in multiple comments
- [pulumi/examples gcp-py-gke](https://github.com/pulumi/examples/blob/master/gcp-py-gke/__main__.py) — kubeconfig construction from cluster outputs using `Output.all()`
- [Pulumi Manage Artifact Registry IAM Guide](https://www.pulumi.com/guides/how-to/gcp-artifactregistry-iambinding/) — `RepositoryIamMember` with `roles/artifactregistry.writer`

### Tertiary (LOW confidence — flag for validation)
- GKE API enablement list (`container.googleapis.com` etc.) — synthesized from multiple web sources; verify against current GCP project setup

---

## Metadata

**Confidence breakdown:**
- Standard stack versions: HIGH — verified against PyPI on 2026-04-04
- GKE Autopilot Pulumi resource pattern: HIGH — confirmed via Pulumi registry docs + GitHub issue tracker
- ignore_changes field list: HIGH — confirmed via pulumi/pulumi-gcp#1170 + terraform-provider-google#11133
- GCS backend configuration: HIGH — confirmed via official Pulumi docs
- Stack config pattern: HIGH — confirmed via official Pulumi docs
- Workload Identity cluster argument: HIGH — confirmed via Pulumi registry and community examples
- IAM propagation timing: MEDIUM — known behavior, exact timing varies

**Research date:** 2026-04-04
**Valid until:** 2026-05-04 (stable ecosystem; Pulumi GCP provider releases frequently but patterns are stable)
