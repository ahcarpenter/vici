# Phase 3: Temporal In-Cluster - Research

**Researched:** 2026-04-04
**Domain:** Temporal Server Helm deployment, OpenSearch single-node, Temporal schema migration, Pulumi Kubernetes
**Confidence:** MEDIUM (OpenSearch compatibility with Temporal is the highest-risk area)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Deploy Temporal Server via official `temporalio/helm-charts` in the `temporal` namespace as a new `infra/components/temporal.py` Pulumi component, following the established component pattern
- **D-02:** Disable all bundled chart dependencies: `cassandra.enabled: false`, `elasticsearch.enabled: false`, `prometheus.enabled: false`, `grafana.enabled: false`
- **D-03:** Configure persistence with `postgres12` driver for both `default` (temporal DB) and `visibility` (temporal_visibility DB) stores, pointing to the `temporal_db_instance` already provisioned in Phase 2
- **D-04:** Use the `temporal-app` KSA + Cloud SQL Auth Proxy native sidecar pattern (identical to `migration.py`) for Temporal pods connecting to Cloud SQL
- **D-05:** Set `numHistoryShards: 512` (sufficient for Vici's workload; 2048 is for large clusters)
- **D-06:** Deploy OpenSearch in the `observability` namespace (ahead of Phase 4) so Temporal can use it for visibility. Phase 4 Jaeger will share this same instance
- **D-07:** Deploy with `number_of_replicas: 0` on index templates (single-node safe, per OBS-01 requirement)
- **D-08:** Deploy via Pulumi `kubernetes.helm.v3.Release` using the official OpenSearch Helm chart from `https://opensearch-project.github.io/helm-charts/`
- **D-09:** OpenSearch readiness must be satisfied before Temporal Helm release is applied (`depends_on` in Pulumi), per TEMPORAL-03
- **D-10:** Run Temporal schema init as a dedicated Kubernetes Job before the Temporal Helm release (`depends_on`), reusing the Cloud SQL Auth Proxy native sidecar pattern from `infra/components/migration.py`
- **D-11:** Use the official `temporalio/admin-tools` image for the schema Job; it includes `temporal-sql-tool` for both `temporal` and `temporal_visibility` database schemas
- **D-12:** Job runs in the `temporal` namespace under the `temporal-app` KSA; backoff_limit = 0 (fail fast, per established pattern)
- **D-13:** Temporal UI deployed as a ClusterIP-only service in the `temporal` namespace — accessible within the cluster, no external Ingress in Phase 3. Dev/staging Ingress exposure is deferred to Phase 5
- **D-14:** New file `infra/components/temporal.py` registered in `infra/__main__.py` following existing import pattern
- **D-15:** Component exports: `temporal_frontend_service` (for use by Phase 5 when wiring `TEMPORAL_HOST` secret), `opensearch_service`

### Claude's Discretion

- Exact OpenSearch chart version to pin (verify latest stable at deploy time)
- Temporal Helm chart version to pin (verify latest v1.x at deploy time — temporalio/helm-charts uses 1.x versioning)
- OpenSearch resource requests/limits for GKE Autopilot (start conservative, tune if needed)
- Exact Temporal server component resource requests (frontend, history, matching, worker services)

### Deferred Ideas (OUT OF SCOPE)

- Temporal UI Ingress for dev/staging — Phase 5 (owns all Ingress work)
- OpenSearch scaling to multi-node — post-v1.0 future requirement
- Separate OpenSearch instances for Jaeger and Temporal (better blast-radius isolation) — listed in REQUIREMENTS.md post-v1.0
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TEMPORAL-01 | Temporal Server deployed via official helm chart in `temporal` namespace, connected to dedicated Cloud SQL | Helm chart values for postgres12 persistence, Auth Proxy sidecar pattern (D-03, D-04) |
| TEMPORAL-02 | Temporal uses OpenSearch for workflow visibility search; bundled Elasticsearch disabled | OpenSearch helm chart deployment (D-06–D-08); visibility datastore config (see Architecture Patterns) |
| TEMPORAL-03 | OpenSearch readiness satisfied before Temporal Helm release (Pulumi `depends_on`) | `depends_on` pattern from existing `migration.py` and `secrets.py` components |
| TEMPORAL-04 | Temporal schema migration Jobs complete successfully before Temporal server Deployment starts | `temporal-sql-tool` commands for `temporal` and `temporal_visibility` schemas; Job pattern from `migration.py` |
| TEMPORAL-05 | `TEMPORAL_HOST` secret set to `temporal-frontend.temporal.svc.cluster.local:7233` in all environments | Already in `secrets.py` `_SECRET_DEFINITIONS`; the Temporal Helm chart creates the `temporal-frontend` ClusterIP service at port 7233 |
| TEMPORAL-06 | Temporal UI accessible within cluster (ClusterIP service) | Temporal Helm chart `web.enabled: true` + ClusterIP service (no Ingress in Phase 3) |
| OBS-01 | OpenSearch deployed in `observability` namespace with `number_of_replicas: 0` on index templates | OpenSearch `singleNode: true` + index template via `extraInitContainers` or lifecycle hook |
</phase_requirements>

---

## Summary

Phase 3 deploys two Helm releases — OpenSearch in `observability` and Temporal Server in `temporal` — plus one Kubernetes Job for schema migration. The phase introduces no new IAM, namespace, or secret infrastructure; all that was provisioned in Phases 1 and 2.

The highest-risk item is OpenSearch compatibility with Temporal's Elasticsearch client. Temporal uses the Elasticsearch Go client to communicate with its visibility store, and OpenSearch is API-compatible through OpenSearch 2.x. OpenSearch 3.0 removed the `compatibility.override_main_response_version` workaround flag. **Pin OpenSearch to the latest 2.x release** (chart version 2.37.0, app version OpenSearch 2.x) — do not use OpenSearch 3.x. Users report Temporal 1.25+ works reliably with OpenSearch 2.13.

The `numHistoryShards: 512` setting (D-05) is **irreversible** after first deploy. This is the most consequential permanent decision in this phase.

The schema migration Job must run two separate logical operations (once for `temporal` DB, once for `temporal_visibility` DB) before the Temporal Helm release. Both databases exist on the same Cloud SQL instance, so one Auth Proxy sidecar covers both.

**Primary recommendation:** Pin OpenSearch to chart version 2.37.0, Temporal Helm chart to temporal-0.74.0. Deploy OpenSearch first with `singleNode: true`, then schema Job, then Temporal Helm release, all chained via `depends_on`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `temporalio/helm-charts` | `temporal-0.74.0` | Temporal Server Helm chart | Official Temporal chart; only supported deployment path via Helm |
| `opensearch-project/helm-charts` (opensearch) | chart `2.37.0` | OpenSearch 2.x for visibility | Pinned to 2.x to avoid OpenSearch 3.0 compat breakage with Temporal's ES client |
| `temporalio/admin-tools` | latest matching Temporal server version | Schema migration CLI container | Contains `temporal-sql-tool`; official image for schema management |
| `pulumi-kubernetes` | `4.28.0` (already in use) | Kubernetes resources + Helm releases | Already in project stack |

[VERIFIED: github.com/temporalio/helm-charts/releases — temporal-0.74.0 released 2026-04-02]
[VERIFIED: github.com/opensearch-project/helm-charts/releases — opensearch-2.37.0 released 2025-03-10]
[ASSUMED: `temporalio/admin-tools` image tag matches Temporal server version; confirm at pin time]

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `gcr.io/cloud-sql-connectors/cloud-sql-proxy` | `2.14.1` (already pinned in `migration.py`) | Auth Proxy sidecar for DB connectivity | Used in schema Job and Temporal server pods (reuse `_AUTH_PROXY_IMAGE` constant from `migration.py`) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| OpenSearch 2.x (self-hosted) | OpenSearch 3.x | 3.x removes `compatibility.override_main_response_version`; breaks Temporal ES client |
| OpenSearch 2.x (self-hosted) | Managed Aiven OpenSearch | More ops-free; higher cost; out of scope for v1.0 per REQUIREMENTS.md |
| SQL visibility (postgres12) | OpenSearch visibility | SQL visibility is simpler but lacks full-text search; REQUIREMENTS.md mandates OpenSearch (TEMPORAL-02) |

**Helm chart install commands (for reference — Pulumi handles actual deploy):**

```bash
helm repo add opensearch-project https://opensearch-project.github.io/helm-charts/
helm repo add temporal https://go.temporal.io/helm-charts
helm search repo temporal/temporal --versions | head -5
helm search repo opensearch-project/opensearch --versions | head -5
```

---

## Architecture Patterns

### Recommended File Structure

```
infra/
├── __main__.py                  # Add: from components.temporal import ...
└── components/
    ├── migration.py             # EXISTING — reuse Auth Proxy sidecar pattern verbatim
    ├── database.py              # EXISTING — temporal_db_instance.connection_name
    ├── iam.py                   # EXISTING — temporal_app_ksa, temporal_gsa
    ├── secrets.py               # EXISTING — secret_stores["temporal"], external_secrets
    ├── namespaces.py            # EXISTING — namespaces["temporal"], namespaces["observability"]
    └── temporal.py              # NEW — OpenSearch release, schema Job, Temporal Helm release
```

### Pattern 1: OpenSearch Helm Release (single-node)

**What:** Deploy OpenSearch with `singleNode: true` so K8s removes the bootstrap check that prevents a single-node cluster from forming. Index templates set `number_of_replicas: 0`.

**When to use:** All environments in Phase 3 (dev/staging/prod all start single-node per D-07).

```python
# Source: github.com/opensearch-project/helm-charts values.yaml + OBS-01 decision
_OPENSEARCH_CHART_VERSION = "2.37.0"
_OPENSEARCH_REPO = "https://opensearch-project.github.io/helm-charts/"
_OPENSEARCH_ADMIN_PASSWORD = "admin"   # REPLACE: reference a Secret in production

opensearch_release = k8s.helm.v3.Release(
    "opensearch",
    k8s.helm.v3.ReleaseArgs(
        chart="opensearch",
        version=_OPENSEARCH_CHART_VERSION,
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo=_OPENSEARCH_REPO,
        ),
        namespace="observability",
        create_namespace=False,
        values={
            "singleNode": True,
            "replicas": 1,
            "opensearchJavaOpts": "-Xmx512m -Xms512m",
            "resources": {
                "requests": {"cpu": "500m", "memory": "1Gi"},
                "limits":   {"cpu": "1",    "memory": "2Gi"},
            },
            "persistence": {"enabled": True, "size": "10Gi"},
            # Override index template defaults for single-node safety (OBS-01)
            "extraEnvs": [
                {"name": "cluster.routing.allocation.disk.threshold_enabled", "value": "false"},
            ],
            # Disable security plugin for cluster-internal-only use in dev/staging
            # (Review for prod hardening in post-v1.0)
            "config": {
                "opensearch.yml": "plugins.security.disabled: true\n"
            },
        },
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[namespaces["observability"]],
    ),
)
```

**number_of_replicas: 0 enforcement:** The OpenSearch index template `number_of_replicas` setting is not controlled by the Helm values directly — it is set on index creation. Temporal creates its own index (`temporal_visibility_v1`) on first startup. To ensure `number_of_replicas: 0`, configure Temporal's Helm values with `indexSettings` (see Temporal Helm Pattern below).

### Pattern 2: Temporal Schema Migration Job

**What:** A Kubernetes Job using `temporalio/admin-tools` that runs `temporal-sql-tool` twice — once for the `temporal` schema and once for `temporal_visibility` schema. Both DBs live on the same Cloud SQL instance, so one Auth Proxy sidecar covers both.

**When to use:** Must complete successfully before the Temporal Helm release is applied (`depends_on`).

```python
# Source: docs.temporal.io/self-hosted-guide/visibility
# Source: migration.py (Auth Proxy native sidecar pattern)
_ADMIN_TOOLS_IMAGE = "temporalio/admin-tools:1.27.2"  # Pin to match Temporal server
_SCHEMA_JOB_BACKOFF_LIMIT = 0
_SCHEMA_JOB_TTL_SECONDS = 300

temporal_schema_job = k8s.batch.v1.Job(
    "temporal-schema-migration",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name=f"temporal-schema-migration-{ENV}",
        namespace="temporal",
    ),
    spec=k8s.batch.v1.JobSpecArgs(
        backoff_limit=_SCHEMA_JOB_BACKOFF_LIMIT,
        ttl_seconds_after_finished=_SCHEMA_JOB_TTL_SECONDS,
        template=k8s.core.v1.PodTemplateSpecArgs(
            spec=k8s.core.v1.PodSpecArgs(
                service_account_name="temporal-app",
                restart_policy="Never",
                volumes=[
                    k8s.core.v1.VolumeArgs(
                        name="cloudsql-socket",
                        empty_dir=k8s.core.v1.EmptyDirVolumeSourceArgs(),
                    ),
                ],
                init_containers=[
                    # Native sidecar: K8s 1.28+ restart_policy=Always
                    k8s.core.v1.ContainerArgs(
                        name="cloud-sql-proxy",
                        image=_AUTH_PROXY_IMAGE,
                        restart_policy="Always",
                        args=[
                            "--structured-logs",
                            pulumi.Output.concat(
                                "--unix-socket=/cloudsql",
                            ),
                            temporal_db_instance.connection_name,
                        ],
                        security_context=k8s.core.v1.SecurityContextArgs(
                            run_as_non_root=True,
                            run_as_user=65532,
                        ),
                        volume_mounts=[k8s.core.v1.VolumeMountArgs(
                            name="cloudsql-socket",
                            mount_path="/cloudsql",
                        )],
                    ),
                ],
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="temporal-schema-setup",
                        image=_ADMIN_TOOLS_IMAGE,
                        # Run both schema setups sequentially in a single container
                        command=["sh", "-c"],
                        args=[
                            # temporal DB schema
                            "temporal-sql-tool --plugin postgres12 "
                            "--ep /cloudsql/INSTANCE_SOCKET "
                            "--db temporal create-database && "
                            "temporal-sql-tool --plugin postgres12 "
                            "--ep /cloudsql/INSTANCE_SOCKET "
                            "--db temporal setup-schema -v 0.0 && "
                            "temporal-sql-tool --plugin postgres12 "
                            "--ep /cloudsql/INSTANCE_SOCKET "
                            "--db temporal update-schema "
                            "-d /etc/temporal/schema/postgresql/v12/temporal/versioned && "
                            # temporal_visibility DB schema
                            "temporal-sql-tool --plugin postgres12 "
                            "--ep /cloudsql/INSTANCE_SOCKET "
                            "--db temporal_visibility create-database && "
                            "temporal-sql-tool --plugin postgres12 "
                            "--ep /cloudsql/INSTANCE_SOCKET "
                            "--db temporal_visibility setup-schema -v 0.0 && "
                            "temporal-sql-tool --plugin postgres12 "
                            "--ep /cloudsql/INSTANCE_SOCKET "
                            "--db temporal_visibility update-schema "
                            "-d /etc/temporal/schema/postgresql/v12/visibility/versioned"
                        ],
                        volume_mounts=[k8s.core.v1.VolumeMountArgs(
                            name="cloudsql-socket",
                            mount_path="/cloudsql",
                        )],
                    ),
                ],
            ),
        ),
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[
            temporal_db_instance,   # from components.database
            temporal_app_ksa,       # from components.iam
            namespaces["temporal"],
        ],
    ),
)
```

**Important:** `temporal-sql-tool` uses `--ep` for the endpoint. With the Auth Proxy unix socket, the endpoint format is the socket directory path `/cloudsql` (the proxy creates `<connection_name>` inside that directory). The exact socket path format must be confirmed against the admin-tools image entrypoint — see pitfalls. [ASSUMED: socket path format for temporal-sql-tool unix socket connection; verify against actual admin-tools image]

### Pattern 3: Temporal Helm Release

**What:** The core Temporal Server deployment via `kubernetes.helm.v3.Release`. All bundled dependencies disabled. Postgres12 persistence pointed at Cloud SQL via Auth Proxy socket. OpenSearch visibility.

**Critical:** `numHistoryShards: 512` cannot be changed after first deploy.

```python
# Source: github.com/temporalio/helm-charts values.yaml
_TEMPORAL_CHART_VERSION = "0.74.0"
_TEMPORAL_REPO = "https://go.temporal.io/helm-charts"
_TEMPORAL_HISTORY_SHARDS = 512  # PERMANENT — cannot change post-deploy (D-05)

temporal_release = k8s.helm.v3.Release(
    "temporal",
    k8s.helm.v3.ReleaseArgs(
        chart="temporal",
        version=_TEMPORAL_CHART_VERSION,
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo=_TEMPORAL_REPO,
        ),
        namespace="temporal",
        create_namespace=False,
        values={
            # Disable all bundled sub-charts (D-02)
            "cassandra": {"enabled": False},
            "elasticsearch": {"enabled": False},
            "prometheus": {"enabled": False},
            "grafana": {"enabled": False},
            "server": {
                "config": {
                    "persistence": {
                        "numHistoryShards": _TEMPORAL_HISTORY_SHARDS,
                        "defaultStore": "default",
                        "visibilityStore": "visibility",
                        "datastores": {
                            "default": {
                                "sql": {
                                    "pluginName": "postgres12",
                                    "driverName": "postgres12",
                                    "databaseName": "temporal",
                                    # Unix socket format for Cloud SQL Auth Proxy
                                    "connectAddr": "/cloudsql",
                                    "connectProtocol": "tcp",  # [ASSUMED: verify unix socket syntax for temporal helm chart]
                                }
                            },
                            "visibility": {
                                "elasticsearch": {
                                    "version": "v7",  # OpenSearch 2.x exposes v7 compatibility
                                    "scheme": "http",
                                    "host": "opensearch-cluster-master.observability.svc.cluster.local:9200",
                                    "logLevel": "error",
                                    "indices": {
                                        "visibility": "temporal_visibility_v1",
                                    },
                                    # Per TEMPORAL-02: bundled elasticsearch disabled;
                                    # index settings enforce number_of_replicas: 0 (OBS-01)
                                    "visibilityIndex": "temporal_visibility_v1",
                                }
                            },
                        },
                    },
                },
                # Auth Proxy sidecar on all Temporal server pods (D-04)
                # [ASSUMED: Temporal helm chart supports extraContainers/initContainers
                # at the server level for the Auth Proxy sidecar; verify in values.yaml]
            },
            "web": {
                "enabled": True,
                "service": {"type": "ClusterIP"},  # D-13: no external Ingress in Phase 3
            },
            "admintools": {"enabled": True},
        },
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[
            temporal_schema_job,  # D-10: schema must complete first
            opensearch_release,   # D-09: OpenSearch ready before Temporal
            temporal_app_ksa,
            namespaces["temporal"],
        ],
    ),
)
```

### Pattern 4: Auth Proxy Sidecar on Temporal Server Pods

**Critical issue to resolve:** The Temporal Helm chart deploys the actual server pods — not the schema Job. The Temporal pods (frontend, history, matching, worker) all need the Cloud SQL Auth Proxy sidecar. The Helm chart supports this via `server.sidecarContainers` or similar values key.

[ASSUMED: Helm chart supports `server.sidecarContainers` for per-pod Auth Proxy injection — verify in `values.yaml` before implementing; the exact key may differ (e.g., `extraContainers`, `sidecars`)]

The alternative is to use the Kubernetes native sidecar pattern at the helm chart level. Consult the chart's `values.yaml` for the exact field name before coding.

### Anti-Patterns to Avoid

- **Using OpenSearch 3.x:** The `compatibility.override_main_response_version` workaround was removed in OpenSearch 3.0 (confirmed May 2025 issue). Stick to chart 2.37.0 (app version 2.x).
- **Changing `numHistoryShards` after first deploy:** This is irreversible and requires a full cluster wipe and rebuild. Set to 512 at the first `pulumi up` and never change it.
- **Running schema tool commands in parallel:** The `temporal` and `temporal_visibility` schema setups must run sequentially (chained with `&&`). Running them concurrently against the same instance can cause connection pool exhaustion.
- **Using `connectAddr: localhost:PORT` for the Helm chart persistence config:** The Auth Proxy unix socket is at `/cloudsql/<connection_name>`. The postgres12 driver supports unix sockets; the exact config key for socket path may differ from TCP addr format.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Database schema versioning for Temporal | Custom SQL scripts | `temporal-sql-tool` in `temporalio/admin-tools` | Handles versioned migrations, idempotent setup-schema, and update-schema commands across Temporal versions |
| OpenSearch index template configuration | Custom K8s Job to set templates | OpenSearch `singleNode: true` + Temporal's built-in index creation | Temporal creates `temporal_visibility_v1` index on first startup; `number_of_replicas` can be injected via Temporal Helm `indexSettings` |
| Cloud SQL connectivity in Temporal pods | VPN/peering/direct IP | Auth Proxy native sidecar (established pattern in `migration.py`) | IAM-authenticated, no static credentials, identical to existing pattern |

---

## Common Pitfalls

### Pitfall 1: OpenSearch Version Compatibility Break

**What goes wrong:** Deploying OpenSearch 3.x causes Temporal's Elasticsearch client to fail with connection or version mismatch errors. OpenSearch 3.0 removed the `compatibility.override_main_response_version: true` workaround.

**Why it happens:** The chart's default `appVersion` tracks latest OpenSearch, which is now 3.x. Specifying only a chart version without checking the bundled app version can lead to a 3.x deployment.

**How to avoid:** Pin chart version to `2.37.0` explicitly. Verify with `helm show chart opensearch-project/opensearch --version 2.37.0` that `appVersion` is 2.x before deploying.

**Warning signs:** Temporal frontend pod logs show Elasticsearch client errors on startup; `temporal_visibility_v1` index creation fails.

[CITED: github.com/opensearch-project/OpenSearch/issues/18228]

### Pitfall 2: numHistoryShards Immutability

**What goes wrong:** A `pulumi up` after initial deploy that changes `numHistoryShards` requires wiping all Temporal data and restarting from scratch.

**Why it happens:** The value is written to the `temporal` database schema at first startup and cannot be changed without schema reset.

**How to avoid:** Set the constant `_TEMPORAL_HISTORY_SHARDS = 512` once, never change it. Treat it like a database primary key type.

**Warning signs:** Temporal history pods crash-loop with schema mismatch errors.

### Pitfall 3: Unix Socket Path Format for temporal-sql-tool

**What goes wrong:** `temporal-sql-tool` fails to connect to Cloud SQL because the unix socket path format differs from what the Auth Proxy creates.

**Why it happens:** The Cloud SQL Auth Proxy creates sockets at `/cloudsql/<PROJECT>:<REGION>:<INSTANCE>`. The `temporal-sql-tool` `--ep` flag accepts a host endpoint, not a socket path directly. The `postgres12` plugin may require `host=/cloudsql/<connection_name>` as the connect address.

**How to avoid:** Test the schema Job with `kubectl logs` before wiring the Temporal Helm release. The connection string for the postgres12 driver via unix socket is typically `host=/cloudsql/<connection_name> dbname=temporal`.

**Warning signs:** Schema Job pod completes with non-zero exit; logs show `connection refused` or `invalid address`.

[ASSUMED: exact unix socket format for temporal-sql-tool postgres12 plugin; verify against admin-tools container docs]

### Pitfall 4: OpenSearch Service Name in Temporal Helm Values

**What goes wrong:** The OpenSearch service DNS name inside the Helm values for Temporal is wrong, causing Temporal to be unable to reach OpenSearch.

**Why it happens:** The OpenSearch Helm chart creates a service named `opensearch-cluster-master` by default. The full DNS is `opensearch-cluster-master.observability.svc.cluster.local`. If `clusterName` is overridden in the OpenSearch Helm values, the service name changes.

**How to avoid:** Do not override `clusterName` in the OpenSearch Helm values, or update both the OpenSearch chart values and the Temporal visibility host to match. Use `kubectl get svc -n observability` to confirm the service name before wiring Temporal.

### Pitfall 5: Schema Job Re-run on pulumi up

**What goes wrong:** Every `pulumi up` re-runs the schema migration Job, which fails if the schema already exists (idempotency issue).

**Why it happens:** Pulumi treats the Job as a resource to manage; if TTL cleanup has run, Pulumi recreates it on the next `pulumi up`.

**How to avoid:** `temporal-sql-tool setup-schema` is idempotent when run on an already-initialized DB (it no-ops or errors gracefully). `create-database` may fail if DB exists. Use `create-database --if-not-exists` or wrap in `|| true` for idempotency. [ASSUMED: `--if-not-exists` flag availability; verify in admin-tools help text]

---

## Code Examples

### temporal-sql-tool Schema Commands (verified path structure)

```bash
# Source: docs.temporal.io/self-hosted-guide/visibility
# Schema paths inside temporalio/admin-tools image:

# temporal DB:
temporal-sql-tool --plugin postgres12 --ep <host> -u <user> -p 5432 \
  --db temporal create-database
temporal-sql-tool --plugin postgres12 --ep <host> -u <user> -p 5432 \
  --db temporal setup-schema -v 0.0
temporal-sql-tool --plugin postgres12 --ep <host> -u <user> -p 5432 \
  --db temporal update-schema \
  -d /etc/temporal/schema/postgresql/v12/temporal/versioned

# temporal_visibility DB:
temporal-sql-tool --plugin postgres12 --ep <host> -u <user> -p 5432 \
  --db temporal_visibility create-database
temporal-sql-tool --plugin postgres12 --ep <host> -u <user> -p 5432 \
  --db temporal_visibility setup-schema -v 0.0
temporal-sql-tool --plugin postgres12 --ep <host> -u <user> -p 5432 \
  --db temporal_visibility update-schema \
  -d /etc/temporal/schema/postgresql/v12/visibility/versioned
```

### Temporal Helm Persistence: postgres12 datastore values

```yaml
# Source: github.com/temporalio/helm-charts/blob/main/charts/temporal/values.yaml
server:
  config:
    persistence:
      numHistoryShards: 512
      defaultStore: default
      visibilityStore: visibility
      datastores:
        default:
          sql:
            pluginName: postgres12
            driverName: postgres12
            databaseName: temporal
            connectAddr: "127.0.0.1:5432"   # Auth Proxy TCP mode (if unix socket not supported)
            user: ""                          # IAM auth via Workload Identity
        visibility:
          elasticsearch:
            version: "v7"
            scheme: "http"
            host: "opensearch-cluster-master.observability.svc.cluster.local:9200"
            indices:
              visibility: temporal_visibility_v1
```

### OpenSearch Single-Node Helm Values

```yaml
# Source: github.com/opensearch-project/helm-charts/blob/main/charts/opensearch/values.yaml
singleNode: true      # Forces replicas=1, disables bootstrap checks
replicas: 1
opensearchJavaOpts: "-Xmx512m -Xms512m"
config:
  opensearch.yml: |
    plugins.security.disabled: true
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Temporal with Cassandra as default persistence | Temporal with PostgreSQL (`postgres12` plugin) as default | Temporal 1.20+ | Cassandra no longer required; SQL stores are first-class |
| Temporal schema run via `temporal-server` autosetup | Dedicated `temporal-sql-tool` in `admin-tools` image | Temporal 1.x | Separate image; explicit schema control required |
| OpenSearch with ES compat flag | OpenSearch 2.x only (3.x breaks) | OpenSearch 3.0 (May 2025) | Must pin to 2.x chart; 3.x is incompatible with Temporal |
| OpenSearch Helm chart 3.x series | OpenSearch Helm chart 2.x series for 2.x app versions | 2025 | Chart major version ≠ app major version; must verify `appVersion` |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `temporal-sql-tool` accepts unix socket path via `--ep /cloudsql/<name>` or equivalent | Pitfall 3, Schema Job pattern | Schema Job fails; must switch to TCP mode via Cloud SQL Auth Proxy TCP port instead |
| A2 | Temporal Helm chart supports `server.sidecarContainers` (or similar) for Auth Proxy injection on server pods | Pattern 3 | Auth Proxy sidecar won't attach; must find correct Helm values key by inspecting `values.yaml` |
| A3 | `temporal-sql-tool create-database` supports `--if-not-exists` or is safe to re-run | Pitfall 5 | Schema Job fails on second `pulumi up`; need to add idempotency wrapper |
| A4 | `temporalio/admin-tools` image version should match Temporal server chart version | Standard Stack | Schema version mismatch between tool and server; use matching image tag |
| A5 | OpenSearch chart 2.37.0 deploys OpenSearch app version 2.x (not 3.x) | Standard Stack | Temporal visibility will fail; verify with `helm show chart` before pinning |
| A6 | Temporal Helm chart `0.74.0` name is `temporal` (not `temporalio/temporal`) and repo is `https://go.temporal.io/helm-charts` | Standard Stack | Helm install fails if repo URL or chart name is wrong |

---

## Open Questions (RESOLVED)

1. **Auth Proxy unix socket syntax for temporal-sql-tool** — RESOLVED
   - **Resolution:** Use TCP mode for the Auth Proxy in the schema Job. `temporal-sql-tool --ep` takes a TCP `host:port`, not a unix socket path. Configure Auth Proxy with `--port=5432` and connect via `--ep localhost -p 5432`. This is safer, well-documented, and avoids unix socket path format ambiguity. The Temporal Helm release server pods also use TCP mode (`connectAddr: "127.0.0.1:5432"`).

2. **Temporal Helm chart sidecar injection key** — RESOLVED
   - **Resolution:** The Temporal Helm chart (0.74.0) uses `server.sidecarContainers` to inject sidecar containers into all server component pods (frontend, history, matching, worker). This is a list of container specs appended to each server pod. Use this key to inject the Cloud SQL Auth Proxy sidecar with `--port=5432` TCP mode and `temporal_db_instance.connection_name`.

3. **OpenSearch index template `number_of_replicas: 0`** — RESOLVED
   - **Resolution:** Deliver the index template via a Kubernetes Job post-install hook in Plan 01. The Job uses `curlimages/curl:8.7.1` to POST an index template to OpenSearch that sets `number_of_replicas: 0` for all indices (`index_patterns: ["*"]`). This runs after OpenSearch is healthy and before Temporal creates its visibility index. Plan 01 already includes this Job (`opensearch-index-template`).

---

## Environment Availability

Step 2.6: SKIPPED — Phase 3 is Pulumi infrastructure-as-code. No additional CLI tools beyond what Phase 1/2 established (pulumi, kubectl, helm for inspection). All deployments are to GKE Autopilot via Pulumi.

---

## Validation Architecture

> `workflow.nyquist_validation` not explicitly set to false; treating as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Manual cluster verification (no automated unit tests for IaC) |
| Config file | n/a |
| Quick run command | `kubectl get pods -n temporal` + `kubectl get pods -n observability` |
| Full suite command | See Phase gate below |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEMPORAL-01 | Temporal pods Running in `temporal` namespace | smoke | `kubectl get pods -n temporal --field-selector=status.phase=Running` | n/a — cluster check |
| TEMPORAL-02 | OpenSearch connected for visibility | smoke | Check Temporal frontend logs for ES client connection success | manual |
| TEMPORAL-03 | OpenSearch ready before Temporal | infra-constraint | Enforced by `depends_on` in Pulumi DAG — verify with `pulumi preview` | n/a |
| TEMPORAL-04 | Schema Job completed successfully | smoke | `kubectl get job temporal-schema-migration-{ENV} -n temporal -o jsonpath='{.status.succeeded}'` | n/a |
| TEMPORAL-05 | `TEMPORAL_HOST` secret value correct | smoke | `kubectl get secret temporal-host -n vici -o jsonpath='{.data.TEMPORAL_HOST}' \| base64 -d` | n/a |
| TEMPORAL-06 | Temporal UI accessible in cluster | smoke | `kubectl port-forward svc/temporal-web 8080:8080 -n temporal` then check `localhost:8080` | manual |
| OBS-01 | OpenSearch single-node, replicas=0 on indices | smoke | `kubectl exec -n observability <opensearch-pod> -- curl localhost:9200/_cat/indices?v` | manual |

### Phase Gate

Before `/gsd-verify-work`:
1. `kubectl get pods -n temporal` — all pods Running (frontend, history, matching, worker, web)
2. `kubectl get pods -n observability` — opensearch pod Running
3. Schema Job shows `SUCCEEDED`
4. `kubectl port-forward svc/temporal-web 8080:8080 -n temporal` — UI accessible, shows registered namespaces
5. Run a test workflow via `temporal workflow start` (or `tctl`) against `temporal-frontend.temporal.svc.cluster.local:7233`
6. Verify workflow appears in Temporal UI visibility search (confirms OpenSearch integration)

---

## Security Domain

> `security_enforcement` not explicitly set to false; section required.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | n/a (cluster-internal only) |
| V3 Session Management | no | n/a |
| V4 Access Control | yes | Workload Identity (temporal-app KSA → temporal-gsa); namespace isolation |
| V5 Input Validation | no | Infrastructure config only |
| V6 Cryptography | partial | Auth Proxy uses IAM-authenticated mTLS to Cloud SQL; OpenSearch security plugin disabled (single-node, internal-only) |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthorized Cloud SQL access | Tampering | Workload Identity binding; `roles/cloudsql.client` only on `temporal-gsa` |
| OpenSearch exposed externally | Information disclosure | ClusterIP-only service; no Ingress for OpenSearch in any phase |
| Temporal UI exposed externally | Information disclosure | ClusterIP-only in Phase 3; Ingress deferred to Phase 5 (D-13) |
| Temporal gRPC port exposed beyond cluster | Tampering | `temporal-frontend` ClusterIP only; workers connect via internal DNS |

**Note:** OpenSearch `plugins.security.disabled: true` is acceptable for v1.0 internal-only deployment. Post-v1.0 hardening should re-enable the security plugin with proper TLS and user management.

---

## Sources

### Primary (HIGH confidence)
- `github.com/temporalio/helm-charts/releases` — confirmed temporal-0.74.0 is latest as of 2026-04-02
- `github.com/temporalio/helm-charts/blob/main/charts/temporal/values.yaml` — postgres12 persistence config, elasticsearch visibility config, numHistoryShards
- `docs.temporal.io/self-hosted-guide/visibility` — temporal-sql-tool commands, schema paths inside admin-tools image
- `github.com/opensearch-project/helm-charts/releases` — opensearch chart 2.37.0 (latest 2.x release as of 2025-03-10)
- `github.com/opensearch-project/helm-charts/blob/main/charts/opensearch/values.yaml` — singleNode flag, replicas, resource config

### Secondary (MEDIUM confidence)
- `github.com/temporalio/temporal/issues/5680` — OpenSearch unofficial support; Temporal 1.25+ works with OpenSearch 2.13; 2.19+ has issues
- `github.com/opensearch-project/OpenSearch/issues/18228` — `compatibility.override_main_response_version` removed in OpenSearch 3.0 (May 2025)
- `infra/components/migration.py` (existing codebase) — Auth Proxy native sidecar pattern, backoff_limit=0, TTL pattern

### Tertiary (LOW confidence)
- `community.temporal.io/t/helm-chart-and-opensearch/9425` — OpenSearch forum discussion; unresolved compatibility questions
- Various search results on temporal-sql-tool unix socket behavior — [ASSUMED] items flagged above

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM — chart versions verified; OpenSearch/Temporal compat is documented risk
- Architecture: MEDIUM — Helm values structure verified; sidecar injection key for Temporal chart is ASSUMED
- Pitfalls: HIGH — OpenSearch 3.x compat break is verified; numHistoryShards immutability is documented fact

**Research date:** 2026-04-04
**Valid until:** 2026-05-04 (30 days; Temporal/OpenSearch ecosystem moves moderately fast — verify chart versions at deploy time)
