# Phase 6: Infra Best-Practice Audit and Edge-Case Hardening - Research

**Researched:** 2026-04-06
**Domain:** Pulumi resource protection, Kubernetes NetworkPolicy, ESO credential migration, PodDisruptionBudgets, operational runbook
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** All stateful resources get `protect=True` in all environments (dev, staging, prod)
- **D-02:** Protected resources: Cloud SQL instances (app + Temporal), GKE cluster, Artifact Registry, GCS state bucket
- **D-03:** Default deny ingress and egress per namespace, then explicit allow rules for declared ports
- **D-04:** All 5 namespaces get NetworkPolicy resources: vici, temporal, observability, cert-manager, external-secrets
- **D-05:** Allow rules follow actual traffic patterns (e.g., app->temporal:7233, app->jaeger-collector:4317, temporal->cloudsql, etc.)
- **D-06:** Migrate Temporal DB credentials from Pulumi stack secrets to GCP Secret Manager, synced via ESO to K8s Secrets
- **D-07:** Temporal Helm chart should reference credentials via `existingSecret` — consistent with how all other secrets are managed
- **D-08:** PDBs are env-conditional: staging and prod get PDBs, dev skips them
- **D-09:** PDBs apply to: vici-app, Temporal frontend, Temporal history
- **D-10:** Mitigations documented in `infra/OPERATIONS.md`
- **D-11:** Covers: cold-start ordering, secret rotation procedure, cluster upgrade playbook

### Claude's Discretion
- Specific resource limit values for migration/schema Jobs (informed by observed usage)
- NetworkPolicy port numbers and label selectors (derived from actual service manifests)
- PDB minAvailable values per workload
- OPERATIONS.md structure and section ordering

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

## Summary

Phase 6 hardens an already-operational GKE Autopilot infrastructure across five distinct areas: Pulumi resource protection (`protect=True`), namespace-scoped default-deny NetworkPolicies, Temporal DB credential migration from Pulumi stack secrets to ESO, PodDisruptionBudgets for multi-replica workloads, and an operational runbook. No new infrastructure is introduced — the work is entirely audit-and-harden.

The most architecturally significant task is the GCS state bucket: it is currently not a Pulumi-managed resource (it is the backend itself), so achieving `protect: true` in `pulumi preview` requires importing it as a `gcp.storage.Bucket` resource into the Pulumi program with `ResourceOptions(protect=True)`. The Temporal credential migration requires adding two new GCP Secret Manager secrets to `_SECRET_DEFINITIONS` in `secrets.py`, a new `SecretStore` scope for the `temporal` namespace (already exists), and replacing inline credentials in `temporal.py` with `existingSecret` references in the Helm values.

NetworkPolicies for GKE Autopilot must include DNS egress (port 53 UDP/TCP to kube-dns) on every namespace — without it, pods cannot resolve service names and all service-to-service traffic breaks. The actual traffic map derived from the codebase is the authoritative source for allow rules.

**Primary recommendation:** Implement all five hardening areas as separate, independently verifiable Pulumi component modules. Each area maps to a discrete set of resource changes with clear `pulumi preview` verification criteria.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pulumi-kubernetes | already in use (4.x) | NetworkPolicy, PDB resources | Already established in project |
| pulumi-gcp | already in use (7.x) | `protect=True` on GCP resources, new SM secrets | Already established in project |
| external-secrets (ESO) | 1.3.2 (already deployed) | Sync new Temporal DB creds from GCP SM | Established ESO pattern |

### No New Libraries Required
This phase adds no new dependencies. All tooling is already installed.

**Version verification:** [VERIFIED: codebase grep] — `_ESO_CHART_VERSION = "1.3.2"` in `secrets.py`, `pulumi-kubernetes` and `pulumi-gcp` already in `requirements.txt`.

## Architecture Patterns

### Recommended Project Structure

New files to add to `infra/components/`:
```
infra/
├── components/
│   ├── network_policy.py    # All 5 namespace NetworkPolicies (new)
│   ├── pdb.py               # PodDisruptionBudgets (new, env-conditional)
│   └── state_bucket.py      # GCS state bucket as managed resource (new)
├── OPERATIONS.md            # Operational runbook (new, at infra/ root)
```

Modifications to existing files:
```
infra/components/
├── cluster.py      # Add ResourceOptions(protect=True)
├── database.py     # Add ResourceOptions(protect=True) to both instances
├── registry.py     # Add ResourceOptions(protect=True)
├── temporal.py     # Replace inline creds with existingSecret; add resource limits to schema Job
├── secrets.py      # Add temporal-db-user + temporal-db-password to _SECRET_DEFINITIONS
├── migration.py    # Add resource limits to Job containers
├── opensearch.py   # Add resource limits to index-template Job container
infra/
└── __main__.py     # Import new modules (network_policy, pdb, state_bucket)
```

### Pattern 1: Pulumi `protect=True` on Existing Resources

**What:** Add `protect=True` to `ResourceOptions` on stateful resources. Pulumi will refuse to delete these resources even during `pulumi destroy` until the flag is removed.

**When to use:** All stateful resources per D-01/D-02.

**Key distinction from `deletion_protection`:** The cluster already has GCP-level `deletion_protection=True`. `protect=True` in `ResourceOptions` is a separate, Pulumi-engine-level guard — it prevents `pulumi destroy` from touching the resource at all, regardless of GCP-level settings. Both layers should coexist.

**Example (database.py pattern):**
```python
# Source: Pulumi docs - ResourceOptions
app_db_instance = gcp.sql.DatabaseInstance(
    f"vici-app-db-{ENV}",
    # ... existing args unchanged ...
    opts=ResourceOptions(
        depends_on=[vpc_peering_connection],
        protect=True,   # ADD THIS
    ),
)
```

**GCS State Bucket — special case:** The state bucket (`vici-app-pulumi-state-{env}`) is NOT currently a Pulumi-managed resource — it is the backend. To show `protect: true` in `pulumi preview`, it must be imported into the program as a managed `gcp.storage.Bucket` resource with `protect=True`. [VERIFIED: codebase — no `gcp.storage.Bucket` resource exists in any component file; `Pulumi.yaml` references `gs://vici-app-pulumi-state-dev` as backend URL only]

**Import command pattern:**
```bash
pulumi import gcp:storage/bucket:Bucket pulumi-state-bucket vici-app-pulumi-state-{env}
```

After import, define in `state_bucket.py`:
```python
import pulumi_gcp as gcp
from pulumi import ResourceOptions
from config import ENV, PROJECT_ID

state_bucket = gcp.storage.Bucket(
    "pulumi-state-bucket",
    name=f"vici-app-pulumi-state-{ENV}",
    project=PROJECT_ID,
    location="US",
    opts=ResourceOptions(protect=True),
)
```

### Pattern 2: NetworkPolicy — Default-Deny + Allow Rules

**What:** Two NetworkPolicy resources per namespace: (1) a blanket default-deny that selects all pods, (2) explicit allow rules for actual traffic.

**GKE Autopilot specifics:** [VERIFIED: Google Cloud docs] GKE Autopilot has GKE Dataplane V2 (Cilium-based) with network policy enforcement always enabled. Pod-to-pod traffic is NOT covered by `ipBlock` rules — use `namespaceSelector` + `podSelector` instead. When implementing egress default-deny, DNS egress to `kube-dns` (port 53 UDP+TCP) MUST be explicitly allowed or service name resolution breaks entirely.

**Standard default-deny NetworkPolicy:**
```python
# Source: Kubernetes NetworkPolicy docs
k8s.networking.v1.NetworkPolicy(
    f"netpol-default-deny-{ns}",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="default-deny-all",
        namespace=ns,
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),  # selects ALL pods
        policy_types=["Ingress", "Egress"],             # deny both directions
        # no ingress/egress rules = deny all
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces[ns]]),
)
```

**DNS allow rule (required for every namespace):**
```python
k8s.networking.v1.NetworkPolicy(
    f"netpol-allow-dns-{ns}",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="allow-dns-egress", namespace=ns),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),
        policy_types=["Egress"],
        egress=[
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=53, protocol="UDP"),
                    k8s.networking.v1.NetworkPolicyPortArgs(port=53, protocol="TCP"),
                ],
            ),
        ],
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces[ns]]),
)
```

### Traffic Map (derived from codebase audit)

The actual allow rules must be derived from the services defined in the component files. [VERIFIED: codebase read of all component files]

**vici namespace:**
| Direction | From | To | Port | Protocol | Source |
|-----------|------|----|------|----------|--------|
| Ingress | GKE Load Balancer / kube-system | vici-app | 8000 | TCP | ingress.py — GKE Ingress |
| Ingress | observability namespace (prometheus) | vici-app | 8000 | TCP | prometheus.py — ServiceMonitor scrapes /metrics |
| Egress | vici-app | temporal namespace (temporal-frontend) | 7233 | TCP | app.py — TEMPORAL_HOST secret |
| Egress | vici-app | observability namespace (jaeger-collector) | 4317 | TCP | app.py — OTEL_EXPORTER_OTLP_ENDPOINT |
| Egress | vici-app | Cloud SQL Auth Proxy (localhost) | — | — | Unix socket (same pod, not network) |
| Egress | vici-app | GCP Secret Manager | 443 | TCP | ESO pattern |
| Egress | vici-app | External APIs (Twilio, OpenAI, Pinecone) | 443 | TCP | app.py env vars |
| Egress | vici-app | DNS (kube-dns) | 53 | UDP/TCP | Required for hostname resolution |

**temporal namespace:**
| Direction | From | To | Port | Protocol | Source |
|-----------|------|----|------|----------|--------|
| Ingress | vici namespace | temporal-frontend | 7233 | TCP | temporal.py |
| Ingress | observability (prometheus) | temporal metrics | 7233 (or 9090) | TCP | kube-prometheus |
| Egress | temporal-* | observability namespace (opensearch) | 9200 | TCP | temporal.py visibility config |
| Egress | temporal-* | DNS | 53 | UDP/TCP | Required |

**observability namespace:**
| Direction | From | To | Port | Protocol | Source |
|-----------|------|----|------|----------|--------|
| Ingress | vici namespace | jaeger-collector | 4317 | TCP | jaeger.py OTLP gRPC |
| Ingress | any | jaeger-query | 16686 | TCP | jaeger.py UI port |
| Ingress | prometheus-operator | opensearch | 9200 | TCP | kube-prometheus scrape |
| Egress | jaeger-collector | opensearch (in-namespace) | 9200 | TCP | jaeger.py config |
| Egress | jaeger-query | opensearch (in-namespace) | 9200 | TCP | jaeger.py config |
| Egress | observability | temporal namespace | 7233 | TCP | prometheus ServiceMonitor |
| Egress | observability | vici namespace | 8000 | TCP | prometheus ServiceMonitor |
| Egress | observability | DNS | 53 | UDP/TCP | Required |

**cert-manager namespace:**
| Direction | From | To | Port | Protocol | Source |
|-----------|------|----|------|----------|--------|
| Egress | cert-manager | Let's Encrypt ACME | 443 | TCP | certmanager.py — HTTP-01/DNS-01 challenge |
| Egress | cert-manager | Kubernetes API | 443 | TCP | cert-manager needs API server access |
| Egress | cert-manager | DNS | 53 | UDP/TCP | Required |

**external-secrets namespace:**
| Direction | From | To | Port | Protocol | Source |
|-----------|------|----|------|----------|--------|
| Egress | eso | GCP Secret Manager API | 443 | TCP | ESO controller syncs secrets |
| Egress | eso | Kubernetes API | 443 | TCP | ESO writes K8s Secrets |
| Egress | eso | DNS | 53 | UDP/TCP | Required |

### Pattern 3: Temporal DB Credentials via ESO

**What:** Remove `cfg.require_secret("temporal_db_user")` and `cfg.require_secret("temporal_db_password")` from `temporal.py`. Add the credentials to GCP Secret Manager and sync via ESO. Reference via Helm `existingSecret`.

**Step 1 — Extend `_SECRET_DEFINITIONS` in `secrets.py`:**
```python
# Add to _SECRET_DEFINITIONS list:
("temporal-db-user", "temporal", "temporal-db-credentials"),
("temporal-db-password", "temporal", "temporal-db-credentials"),
```

Wait — the ESO pattern creates one K8s Secret per `ExternalSecret`. For Temporal, the Helm chart's `existingSecret` reads a single K8s Secret with a key named `password`. The cleanest approach: one ExternalSecret for `temporal-db-password` targeting a K8s Secret named `temporal-db-credentials` with key `password`. The username is not sensitive and can remain in Helm values.

**Correct `_SECRET_DEFINITIONS` entry:**
```python
("temporal-db-password", "temporal", "temporal-db-credentials"),
```

The ExternalSecret must map the `password` key to the GCP SM secret value. This requires a custom data key mapping (the default uppercases the slug). The planner should derive the exact `secretKey` mapping.

**Step 2 — Remove from Pulumi stack configs:** `temporal_db_user` and `temporal_db_password` removed from `Pulumi.dev.yaml` (only dev currently has them; staging and prod never had them — confirmed by reading stack yaml files).

**Step 3 — Temporal Helm values (`temporal.py`):** [VERIFIED: temporalio helm-charts values.yaml]

The `existingSecret` field lives under `server.config.persistence.datastores.default.sql` and `server.config.persistence.datastores.visibility.sql`:

```python
# In temporal.py Helm values — replace inline user/password:
"persistence": {
    "defaultStore": "default",
    "visibilityStore": "visibility",
    "default": {
        "driver": "sql",
        "sql": {
            "driver": "postgres12",
            "database": "temporal",
            "host": "127.0.0.1",
            "port": 5432,
            "user": "temporal",          # username stays (not sensitive)
            "existingSecret": "temporal-db-credentials",
            "secretKey": "password",
        },
    },
},
```

**Key requirement:** The `temporal` namespace already has a `SecretStore` (`secret_stores["temporal"]` in `secrets.py`) — confirmed by `_SECRETSTORE_NAMESPACES = ["vici", "temporal", "observability"]`. The new ExternalSecret will depend on this existing store.

### Pattern 4: PodDisruptionBudgets

**What:** `k8s.policy.v1.PodDisruptionBudget` resources, env-conditional (staging and prod only).

**Pulumi API:** [VERIFIED: Pulumi Registry — kubernetes.policy.v1.PodDisruptionBudget]

```python
# Source: https://www.pulumi.com/registry/packages/kubernetes/api-docs/policy/v1/poddisruptionbudget/
import pulumi_kubernetes as k8s
from config import ENV

if ENV in ("staging", "prod"):
    vici_pdb = k8s.policy.v1.PodDisruptionBudget(
        "vici-app-pdb",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name="vici-app",
            namespace="vici",
        ),
        spec=k8s.policy.v1.PodDisruptionBudgetSpecArgs(
            min_available=1,
            selector=k8s.meta.v1.LabelSelectorArgs(
                match_labels={"app": "vici"},
            ),
        ),
        opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["vici"]]),
    )
```

**PDB targets and minAvailable values (Claude's Discretion):**

| Workload | Namespace | Label Selector | minAvailable | Rationale |
|----------|-----------|----------------|--------------|-----------|
| vici-app | vici | `app: vici` | 1 | HPA min=1, max=3; 1 ensures rolling update possible with 2+ replicas |
| temporal-frontend | temporal | Helm-managed labels | 1 | Frontend handles client gRPC connections |
| temporal-history | temporal | Helm-managed labels | 1 | History shards = 512; losing a pod is recoverable, but want 1 up |

**Temporal pod label selectors:** The Temporal Helm chart uses labels like `app.kubernetes.io/name: temporal`, `app.kubernetes.io/component: frontend` (and `history` for the history service). These are Helm-generated. The PDB selector must match what the chart actually renders. [ASSUMED — Temporal chart label conventions; the planner should verify by inspecting rendered Helm templates or checking `helm template` output]

### Pattern 5: Resource Limits on Jobs

**What:** Add `resources` blocks to the main containers of `temporal_schema_job`, `migration_job`, and `opensearch_index_template_job`. These Jobs currently have no resource limits (the Auth Proxy sidecar in the schema job has none either).

**Recommended limits (Claude's Discretion — based on what similar workloads use in the codebase):**

| Job | Container | CPU Request | CPU Limit | Mem Request | Mem Limit |
|-----|-----------|-------------|-----------|-------------|-----------|
| temporal-schema-migration | temporal-schema-migration | 100m | 500m | 256Mi | 512Mi |
| temporal-schema-migration | cloud-sql-proxy (sidecar) | 100m | 200m | 128Mi | 256Mi |
| alembic-migration | alembic-migration | 100m | 500m | 256Mi | 512Mi |
| opensearch-index-template | index-template | 50m | 100m | 64Mi | 128Mi |

These are conservative estimates modeled on the Auth Proxy limits already set in `app.py`.

### Anti-Patterns to Avoid

- **Adding `protect=True` to the k8s_provider resource itself** — this would make future cluster credential rotation impossible without manually editing Pulumi state.
- **NetworkPolicy without DNS egress** — pods will fail all hostname resolution silently; this is the #1 NetworkPolicy mistake in GKE.
- **Setting `protect=True` on namespaces** — namespaces are not stateful data stores; protecting them makes namespace recreation or Pulumi stack teardown impossible.
- **Using `ipBlock` for pod-to-pod NetworkPolicy rules in GKE** — GKE Dataplane V2 does not apply `ipBlock` to Pod traffic; use `namespaceSelector` + `podSelector` instead.
- **Applying PDBs in dev** — single-replica pods make PDBs with `minAvailable=1` eviction-blocking (GKE node upgrades cannot proceed), which defeats the point on dev.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Secret syncing | Custom K8s Job to copy GCP SM values | ESO ExternalSecret (already deployed) | ESO handles rotation, RBAC, TTL refresh |
| NetworkPolicy enforcement | Application-level firewall rules | Kubernetes NetworkPolicy | K8s-native, enforced by Dataplane V2 always-on |
| PDB | Custom webhook to block evictions | k8s.policy.v1.PodDisruptionBudget | K8s-native, zero overhead |
| Resource protection | IAM conditions to block deletion | Pulumi `protect=True` | Pulumi-engine enforced before API calls |

## Common Pitfalls

### Pitfall 1: DNS Egress Forgotten on Default-Deny
**What goes wrong:** Default-deny blocks port 53. All pod hostname resolution fails. Services connect to Cloud SQL Proxy (unix socket — unaffected) but cannot reach `temporal-frontend.temporal.svc.cluster.local`.
**Why it happens:** DNS traffic looks "internal" so engineers forget it needs an explicit egress rule.
**How to avoid:** Add a dedicated `allow-dns-egress` NetworkPolicy to every namespace that uses default-deny egress.
**Warning signs:** Pods start but all service-to-service health checks timeout immediately after applying NetworkPolicies.

### Pitfall 2: Temporal Helm `existingSecret` Path Mismatch
**What goes wrong:** The `existingSecret` field must be nested under `server.config.persistence.default.sql` (and `.visibility.sql`), not at the top level of `server.config.persistence`.
**Why it happens:** The chart has multiple persistence configuration sections and the correct nesting depth is non-obvious.
**How to avoid:** Follow the exact path: `server.config.persistence.default.sql.existingSecret`.
**Warning signs:** Temporal server pods start but fail authentication to Cloud SQL — check `temporal-frontend` pod logs for "authentication failed for user".

### Pitfall 3: GCS State Bucket Import Conflict
**What goes wrong:** Importing the GCS state bucket as a Pulumi resource when the same bucket is the active backend can cause confusing Pulumi state errors during stack teardown.
**Why it happens:** Pulumi attempts to write to the bucket during `pulumi up` but the resource is also managed IN the state stored in that bucket.
**How to avoid:** Mark the bucket with `protect=True` and `retain_on_delete=True` in ResourceOptions. Never run `pulumi destroy` on a stack whose state bucket is managed by itself — document this in OPERATIONS.md.
**Warning signs:** `pulumi destroy` errors with "cannot delete resource: protect" — this is actually the desired behavior.

### Pitfall 4: Temporal Helm Labels Not Matching PDB Selector
**What goes wrong:** PDB selector `{"app": "temporal-frontend"}` doesn't match pods because Helm renders pods with `app.kubernetes.io/component: frontend`.
**Why it happens:** The Temporal Helm chart uses Kubernetes recommended labels, not a simple `app` label.
**How to avoid:** Run `kubectl get pods -n temporal --show-labels` post-deploy (or `helm template`) to get actual pod labels before writing the PDB selector.
**Warning signs:** PDB is created but `kubectl get pdb -n temporal` shows `CURRENT=0` (no pods matched).

### Pitfall 5: `protect=True` Blocks Stack-Level Cleanup in Dev
**What goes wrong:** Applying `protect=True` in dev makes it impossible to run `pulumi destroy --stack dev` to clean up a dev environment without first removing protection.
**Why it happens:** D-01 applies protection to all environments including dev.
**How to avoid:** Document the teardown procedure in OPERATIONS.md: (1) Set `protect=False` on protected resources, (2) `pulumi up`, (3) `pulumi destroy`. This is intentional — the friction is the point.
**Warning signs:** `pulumi destroy` shows `error: Resource ... is protected`.

## Code Examples

### Temporal ExternalSecret with Correct Key Name

The ESO ExternalSecret must produce a K8s Secret where the key is `password` (not the default uppercase slug derived from the secret name), because that's what Helm's `existingSecret: temporal-db-credentials, secretKey: password` expects:

```python
# In secrets.py — custom data key mapping for temporal DB password
k8s.apiextensions.CustomResource(
    "ext-secret-temporal-db-password",
    api_version="external-secrets.io/v1",
    kind="ExternalSecret",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="temporal-db-credentials",
        namespace="temporal",
    ),
    spec={
        "refreshInterval": _REFRESH_INTERVAL,
        "secretStoreRef": {"name": "gcp-secret-manager", "kind": "SecretStore"},
        "target": {"name": "temporal-db-credentials", "creationPolicy": "Owner"},
        "data": [
            {
                "secretKey": "password",            # key name Helm expects
                "remoteRef": {"key": f"{ENV}-temporal-db-password"},
            },
        ],
    },
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[secret_stores["temporal"], sm_secrets["temporal-db-password"]],
    ),
)
```

Note: Because this ExternalSecret has a custom key mapping, it should be created directly (not through the generic loop in `secrets.py`) to avoid the slug-to-uppercase default.

### NetworkPolicy Module Structure

```python
# infra/components/network_policy.py
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions
from components.namespaces import k8s_provider, namespaces

_NAMESPACES = ["vici", "temporal", "observability", "cert-manager", "external-secrets"]

for _ns in _NAMESPACES:
    # 1. Default deny all
    k8s.networking.v1.NetworkPolicy(
        f"netpol-default-deny-{_ns}",
        metadata=k8s.meta.v1.ObjectMetaArgs(name="default-deny-all", namespace=_ns),
        spec=k8s.networking.v1.NetworkPolicySpecArgs(
            pod_selector=k8s.meta.v1.LabelSelectorArgs(),
            policy_types=["Ingress", "Egress"],
        ),
        opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces[_ns]]),
    )
    # 2. Allow DNS egress (required for all namespaces)
    k8s.networking.v1.NetworkPolicy(
        f"netpol-allow-dns-{_ns}",
        metadata=k8s.meta.v1.ObjectMetaArgs(name="allow-dns-egress", namespace=_ns),
        spec=k8s.networking.v1.NetworkPolicySpecArgs(
            pod_selector=k8s.meta.v1.LabelSelectorArgs(),
            policy_types=["Egress"],
            egress=[k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=53, protocol="UDP"),
                    k8s.networking.v1.NetworkPolicyPortArgs(port=53, protocol="TCP"),
                ],
            )],
        ),
        opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces[_ns]]),
    )

# 3. Per-namespace allow rules (one NetworkPolicy per traffic direction per namespace)
# ... (see traffic map in Architecture Patterns section)
```

## Runtime State Inventory

This is a hardening phase, not a rename/refactor phase. However, the credential migration (D-06) involves stored state that must be accounted for.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | `temporal_db_user` and `temporal_db_password` encrypted in `Pulumi.dev.yaml` as Pulumi stack secrets | Remove from stack yaml after adding to GCP Secret Manager |
| Live service config | Temporal server Helm release reads credentials from Pulumi Output values at deploy time — no live service memory of old credentials once redeployed | Helm release update replaces credential source |
| OS-registered state | None — no OS-level registrations | None |
| Secrets/env vars | `vici-infra:temporal_db_user` and `vici-infra:temporal_db_password` in `Pulumi.dev.yaml` | Delete with `pulumi config rm vici-infra:temporal_db_user` etc. after SM migration |
| Build artifacts | None — no egg-info or compiled artifacts affected | None |

**Staging and prod:** Staging and prod Pulumi yaml files do NOT currently contain `temporal_db_user` or `temporal_db_password` (confirmed by reading both files). Only dev has these secrets. The plan must add SM secrets and ESO for all three environments but only remove stack secrets from dev.

## Validation Architecture

Nyquist validation is enabled (`nyquist_validation: true` in `.planning/config.json`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pyproject.toml` (existing) |
| Quick run command | `pytest tests/infra/ -x` |
| Full suite command | `pytest -x` |

### Phase Requirements → Test Map

This is a hardening phase with no formal REQ IDs. The 5 success criteria map to static AST tests (same pattern as Phase 4's `test_observability_static.py`):

| Success Criterion | Behavior | Test Type | Automated Command |
|-------------------|----------|-----------|-------------------|
| SC-1: protect=True on stateful resources | cluster.py, database.py, registry.py, state_bucket.py contain `protect=True` | static AST | `pytest tests/infra/test_phase6_static.py::TestProtect -x` |
| SC-2: NetworkPolicy default-deny + allow in all 5 namespaces | network_policy.py defines default-deny and allow rules for each namespace | static AST | `pytest tests/infra/test_phase6_static.py::TestNetworkPolicy -x` |
| SC-3: Temporal credentials via ESO existingSecret | temporal.py has no `cfg.require_secret("temporal_db")`, secrets.py has temporal-db-password | static AST | `pytest tests/infra/test_phase6_static.py::TestTemporalESO -x` |
| SC-4: PDBs exist for vici-app, temporal-frontend, temporal-history in staging+prod | pdb.py has ENV conditional and 3 PDB definitions | static AST | `pytest tests/infra/test_phase6_static.py::TestPDB -x` |
| SC-5: OPERATIONS.md exists with required sections | infra/OPERATIONS.md contains cold-start, secret rotation, cluster upgrade | file content check | `pytest tests/infra/test_phase6_static.py::TestOperationsDoc -x` |

### Wave 0 Gaps
- [ ] `tests/infra/test_phase6_static.py` — covers all 5 success criteria (new file, following pattern of `test_observability_static.py`)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A — infra hardening, not auth flows |
| V3 Session Management | No | N/A |
| V4 Access Control | Yes | NetworkPolicy least-privilege; `protect=True` prevents unauthorized deletion |
| V5 Input Validation | No | N/A |
| V6 Cryptography | Yes | Temporal DB credentials moved to GCP SM (managed, encrypted at rest); removed from Pulumi plaintext-risk stack secrets |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Accidental infrastructure deletion (pulumi destroy) | Tampering / Denial of Service | `protect=True` on all stateful resources |
| Credentials in version-controlled Pulumi stack config | Information Disclosure | Migrate to GCP Secret Manager + ESO |
| Unrestricted pod-to-pod network access | Elevation of Privilege | Default-deny NetworkPolicy per namespace |
| Node-drain eviction removes all replicas | Denial of Service | PodDisruptionBudget with minAvailable=1 |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `policy/v1beta1` PodDisruptionBudget | `policy/v1` PodDisruptionBudget | K8s 1.25 (v1beta1 deprecated) | Use `k8s.policy.v1.PodDisruptionBudget` — v1beta1 removed |
| NetworkPolicy enforcement optional in GKE | GKE Dataplane V2 always-on in Autopilot | GKE 1.28+ Autopilot | No need to enable network policy — it's on by default |

**Deprecated/outdated:**
- `policy/v1beta1.PodDisruptionBudget`: Removed in K8s 1.25. Use `policy/v1` only.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Temporal Helm chart 0.74.0 uses `app.kubernetes.io/component` labels for pod selectors (frontend, history) | Architecture Patterns — Pattern 4 | PDB selector matches no pods; PDB is created but has no effect. Fix: inspect actual pod labels post-deploy |
| A2 | Staging and prod have never had `temporal_db_user`/`temporal_db_password` as stack secrets | Runtime State Inventory | If they do exist, they also need to be removed after SM migration |
| A3 | The GCS state bucket naming convention is `vici-app-pulumi-state-{ENV}` for all three environments | Architecture Patterns — Pattern 1 | If bucket names differ, import command targets wrong resource |

## Open Questions

1. **Temporal Helm pod labels for PDB selector**
   - What we know: The chart uses Helm standard labels; `fullnameOverride: "temporal"` is set
   - What's unclear: Exact label set rendered on temporal-frontend and temporal-history pods with chart 0.74.0
   - Recommendation: Planner should note that the implementer must run `helm template` or `kubectl get pods -n temporal --show-labels` to confirm before writing PDB selectors; plan task should include this discovery step

2. **GCS state bucket for staging and prod**
   - What we know: `Pulumi.yaml` backend URL references `vici-app-pulumi-state-dev` as default
   - What's unclear: Whether staging/prod buckets are named `vici-app-pulumi-state-staging` and `vici-app-pulumi-state-prod` (likely but not confirmed in repo)
   - Recommendation: Add discovery step to confirm bucket names before import commands

3. **cert-manager Kubernetes API egress**
   - What we know: cert-manager needs to read/write Kubernetes resources (Certificates, Secrets)
   - What's unclear: Whether GKE Autopilot's network architecture requires explicit NetworkPolicy egress to the API server, or if API server traffic bypasses NetworkPolicy enforcement
   - Recommendation: [ASSUMED] Add explicit egress rule from cert-manager pods to the Kubernetes API server CIDR on port 443. If GKE Autopilot handles this automatically, the extra rule is harmless.

## Environment Availability

This phase is code/config changes only — no new external tools required. All dependencies (Pulumi, GCP provider, pulumi-kubernetes, ESO) are already installed.

Step 2.6: SKIPPED (no new external dependencies; all tools already available from prior phases)

## Sources

### Primary (HIGH confidence)
- Codebase audit (`infra/components/*.py`, `infra/Pulumi.*.yaml`) — all existing resource definitions, labels, ports, and patterns verified by direct file reads
- [Pulumi ResourceOptions — protect](https://www.pulumi.com/docs/concepts/options/protect/) — protect=True behavior, interaction with deletion_protection
- [kubernetes.policy.v1.PodDisruptionBudget | Pulumi Registry](https://www.pulumi.com/registry/packages/kubernetes/api-docs/policy/v1/poddisruptionbudget/) — Python API and field names verified
- [Kubernetes NetworkPolicy docs](https://kubernetes.io/docs/concepts/services-networking/network-policies/) — default-deny pattern, policy_types
- [GKE NetworkPolicy docs](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/network-policy) — Autopilot DataPlane V2 always-on, ipBlock limitation for pod traffic
- [temporalio/helm-charts values.yaml](https://github.com/temporalio/helm-charts/blob/main/charts/temporal/values.yaml) — existingSecret / secretKey field structure under datastores.default.sql

### Secondary (MEDIUM confidence)
- [Temporal Community Forum — existingSecret](https://community.temporal.io/t/how-do-you-use-existingsecret-in-the-helm-chart/3558) — confirmed pattern works for SQL datastores
- [GKE Autopilot Network Policy Deep-dive](https://medium.com/google-cloud/deep-dive-kubernetes-network-policy-in-gke-e9842ec6b1be) — DNS egress requirement confirmed across multiple sources

### Tertiary (LOW confidence)
- Temporal Helm chart pod label conventions (A1) — training knowledge; verify with `helm template` at implementation time

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in use, no new dependencies
- Architecture (protect=True, ESO, PDB): HIGH — verified against official Pulumi docs and codebase
- Architecture (NetworkPolicy traffic map): HIGH — derived directly from codebase port constants and service definitions
- Architecture (Temporal existingSecret path): HIGH — verified against temporalio/helm-charts values.yaml
- Pitfalls: HIGH — DNS egress and PDB label mismatch are well-documented GKE pitfalls

**Research date:** 2026-04-06
**Valid until:** 2026-05-06 (stable ecosystem — Pulumi, K8s NetworkPolicy, ESO patterns are not fast-moving)
