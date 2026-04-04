# Phase 3: Temporal In-Cluster - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Temporal Server runs in-cluster with OpenSearch-backed visibility, schema migrations complete, and workers can connect via `temporal-frontend.temporal.svc.cluster.local:7233`. OpenSearch is deployed in the `observability` namespace as a shared resource (Phase 4 Jaeger will use the same instance). Application workloads (FastAPI, Temporal worker) are NOT deployed in this phase.

</domain>

<decisions>
## Implementation Decisions

### Temporal Helm Deployment
- **D-01:** Deploy Temporal Server via official `temporalio/helm-charts` in the `temporal` namespace as a new `infra/components/temporal.py` Pulumi component, following the established component pattern
- **D-02:** Disable all bundled chart dependencies: `cassandra.enabled: false`, `elasticsearch.enabled: false`, `prometheus.enabled: false`, `grafana.enabled: false`
- **D-03:** Configure persistence with `postgres12` driver for both `default` (temporal DB) and `visibility` (temporal_visibility DB) stores, pointing to the `temporal_db_instance` already provisioned in Phase 2
- **D-04:** Use the `temporal-app` KSA + Cloud SQL Auth Proxy native sidecar pattern (identical to `migration.py`) for Temporal pods connecting to Cloud SQL
- **D-05:** Set `numHistoryShards: 512` (sufficient for Vici's workload; 2048 is for large clusters)

### OpenSearch Deployment
- **D-06:** Deploy OpenSearch in the `observability` namespace (ahead of Phase 4) so Temporal can use it for visibility. Phase 4 Jaeger will share this same instance — no duplicate deployment needed
- **D-07:** Deploy with `number_of_replicas: 0` on index templates (single-node safe, per OBS-01 requirement)
- **D-08:** Deploy via Pulumi `kubernetes.helm.v3.Release` using the official OpenSearch Helm chart from `https://opensearch-project.github.io/helm-charts/`
- **D-09:** OpenSearch readiness must be satisfied before Temporal Helm release is applied (`depends_on` in Pulumi), per TEMPORAL-03

### Schema Migration
- **D-10:** Run Temporal schema init as a dedicated Kubernetes Job before the Temporal Helm release (`depends_on`), reusing the Cloud SQL Auth Proxy native sidecar pattern from `infra/components/migration.py`
- **D-11:** Use the official `temporalio/admin-tools` image for the schema Job; it includes `temporal-sql-tool` for both `temporal` and `temporal_visibility` database schemas
- **D-12:** Job runs in the `temporal` namespace under the `temporal-app` KSA; backoff_limit = 0 (fail fast, per established pattern)

### Temporal UI
- **D-13:** Temporal UI deployed as a ClusterIP-only service in the `temporal` namespace — accessible within the cluster, no external Ingress in Phase 3. Dev/staging Ingress exposure is deferred to Phase 5 (which owns all Ingress work), per TEMPORAL-06

### Pulumi Component Structure
- **D-14:** New file `infra/components/temporal.py` registered in `infra/__main__.py` following existing import pattern
- **D-15:** Component exports: `temporal_frontend_service` (for use by Phase 5 when wiring `TEMPORAL_HOST` secret), `opensearch_service`

### Claude's Discretion
- Exact OpenSearch chart version to pin (verify latest stable at deploy time)
- Temporal Helm chart version to pin (verify latest v1.x at deploy time — temporalio/helm-charts uses 1.x versioning)
- OpenSearch resource requests/limits for GKE Autopilot (start conservative, tune if needed)
- Exact Temporal server component resource requests (frontend, history, matching, worker services)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/workstreams/gks-refactor/REQUIREMENTS.md` §TEMPORAL — TEMPORAL-01 through TEMPORAL-06 define all Temporal requirements
- `.planning/workstreams/gks-refactor/REQUIREMENTS.md` §OBS-01 — OpenSearch single-node index template config requirement

### Architecture decisions
- `.planning/workstreams/gks-refactor/research/ARCHITECTURE.md` §"Temporal Server: Official Helm Chart" — Helm chart config, disabled dependencies, numHistoryShards
- `.planning/workstreams/gks-refactor/research/ARCHITECTURE.md` §"OpenSearch: Replace with Cloud Logging..." — Contains the original anti-recommendation for self-hosting; **decision overrides this: Option A (self-host) was chosen**
- `.planning/workstreams/gks-refactor/research/STACK.md` — Pulumi package versions in use

### Existing Pulumi components (patterns to follow)
- `infra/components/migration.py` — Cloud SQL Auth Proxy native sidecar pattern (Job + sidecar init container) — MUST follow for schema Job
- `infra/components/database.py` — `temporal_db_instance` connection name; `temporal_database` and `temporal_visibility_database` exports
- `infra/components/iam.py` — `temporal_gsa`, `temporal_app_ksa`, `temporal_wi_binding` (already provisioned, Phase 3 reuses)
- `infra/components/secrets.py` — SecretStore for `temporal` namespace already provisioned
- `infra/components/namespaces.py` — `temporal` and `observability` namespaces already exist

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `infra/components/migration.py` — The Auth Proxy native sidecar init container pattern (volumes, socket mount, security context, `run_as_non_root`) is reusable verbatim for both the schema Job and Temporal server pods
- `infra/components/iam.py` — `temporal_app_ksa` (KSA `temporal-app` in `temporal` namespace) and `temporal_gsa` (with `roles/cloudsql.client`) are already provisioned — Phase 3 references these, does not create them
- `infra/components/database.py` — `temporal_db_instance.connection_name` is already exported; both `temporal` and `temporal_visibility` databases exist

### Established Patterns
- **Helm release via Pulumi**: See `infra/components/secrets.py` ESO release — `kubernetes.helm.v3.Release` with `repository_opts`, pinned `chart_version`, `create_namespace=False` (namespaces pre-created), `opts=ResourceOptions(provider=k8s_provider, depends_on=[...])`
- **Native sidecar**: K8s 1.28+ `restart_policy: Always` on init containers; established in `migration.py`
- **Backoff limit 0**: Fail fast on Jobs, per `migration.py` pattern
- **Component constants**: Magic numbers at module top as `_CONST_NAME`, per `migration.py` and `database.py`
- **No magic numbers**: All image tags, chart versions, port numbers must be named constants

### Integration Points
- Temporal server → Cloud SQL `temporal` + `temporal_visibility` databases via Auth Proxy socket
- Temporal server → OpenSearch for visibility (Helm `visibility.elasticsearch.*` config pointing to in-cluster OpenSearch service)
- Phase 4 Jaeger → same OpenSearch instance (no changes needed to OpenSearch in Phase 4, just consume it)
- Phase 5 FastAPI/worker → `temporal-frontend.temporal.svc.cluster.local:7233` (this is the ClusterIP service Phase 3 creates; Phase 5 sets `TEMPORAL_HOST` secret to this value)

</code_context>

<specifics>
## Specific Ideas

- No specific requirements beyond what's captured in decisions — standard Temporal Helm deployment following established Pulumi patterns in this repo
- OpenSearch single-node (dev/staging/prod all start single-node given Autopilot constraints); `number_of_replicas: 0` on index templates

</specifics>

<deferred>
## Deferred Ideas

- Temporal UI Ingress for dev/staging — Phase 5 (owns all Ingress work)
- OpenSearch scaling to multi-node — post-v1.0 future requirement
- Separate OpenSearch instances for Jaeger and Temporal (better blast-radius isolation) — listed in REQUIREMENTS.md post-v1.0

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-temporal-in-cluster*
*Context gathered: 2026-04-04*
