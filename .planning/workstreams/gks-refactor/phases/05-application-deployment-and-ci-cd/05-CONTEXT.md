# Phase 5: Application Deployment and CI/CD - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

FastAPI app serves traffic on environment-specific public hostnames with TLS, auto-scales under load via HPA, and deploys automatically via GitHub Actions CD pipeline. Temporal worker runs in the same pod as the app (lifespan background task). cert-manager provides TLS. Internal UIs (Grafana, Jaeger, Temporal UI) remain ClusterIP-only until authentication is added.

</domain>

<decisions>
## Implementation Decisions

### Hostname & DNS Convention
- **D-01:** Use real DNS with purchased domain usevici.com (purchased on Squarespace)
- **D-02:** Use `usevici.com` subdomain scheme in Pulumi stack configs (`dev.usevici.com`, `staging.usevici.com`, `usevici.com`). Domain purchased on Squarespace; DNS configuration required before Phase 5 execution.
- **D-03:** Only the FastAPI app gets public Ingress in Phase 5. Temporal UI, Grafana, and Jaeger UI remain ClusterIP-only — operators use `kubectl port-forward`
- **D-04:** Internal UIs must NOT be exposed via Ingress until authentication is in place for each service (deferred — see todo)

### CI/CD Pipeline Design
- **D-05:** Per-environment workflow files (`cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`) that call a shared reusable workflow (`.github/workflows/cd-base.yml`) to stay DRY. CI stays separate in `ci.yml`
- **D-06:** Image tagging: short git SHA (e.g., `abc1234`) + environment tag (e.g., `dev`, `staging`, `prod`). SHA for traceability, env tag for latest-per-env convenience
- **D-07:** GitHub Actions authenticates to GCP via Workload Identity Federation (GitHub OIDC -> GCP WIF pool + provider). No static GCP service account keys in GitHub secrets (per CD-04)
- **D-08:** `cd-dev.yml` triggers on push to `main` — builds, pushes to Artifact Registry, runs `pulumi up --stack dev`
- **D-09:** `cd-staging.yml` runs `pulumi preview --stack staging` on PRs; `pulumi up --stack staging` on explicit workflow dispatch (per CD-02)
- **D-10:** `cd-prod.yml` requires manual workflow dispatch with GitHub environment approval gate (per CD-03)
- **D-11:** CI test job (`ci.yml`) unchanged — pytest with SQLite, no GCP dependency (per CD-05)

### cert-manager Deployment
- **D-12:** Deploy cert-manager via Helm in the `cert-manager` namespace (namespace already exists from Phase 1) as a new `infra/components/certmanager.py` Pulumi component
- **D-13:** Use namespace-scoped `Issuer` (not ClusterIssuer) — consistent with namespace-scoped SecretStore pattern from Phase 2
- **D-14:** Deploy with Let's Encrypt staging issuer first to avoid rate limits during testing; switch to Let's Encrypt production issuer once Ingress is verified working. Both issuers can coexist.

### App Deployment Shape
- **D-15:** Three Pulumi component files: `infra/components/app.py` (Deployment + Service + HPA + ServiceMonitor), `infra/components/ingress.py` (Ingress + cert-manager Issuer + Certificate), `infra/components/cd.py` (WIF pool + provider + CI service account bindings)
- **D-16:** Environment variables injected via `envFrom` per ExternalSecret-generated K8s Secret — one envFrom ref per secret (matches `migration.py` pattern). 11 secrets -> 11 envFrom entries.
- **D-17:** FastAPI Deployment in `vici` namespace with Cloud SQL Auth Proxy native sidecar (reuse pattern from `migration.py`), referencing `vici-app` KSA
- **D-18:** Temporal worker runs as a lifespan background task in the same pod — no separate Deployment (per APP-02)
- **D-19:** HPA configured for FastAPI Deployment: min 1, max 3 replicas, CPU target 70% (per APP-03)

### Claude's Discretion
- cert-manager Helm chart version to pin (verify latest stable at deploy time)
- Readiness/liveness probe configuration (path, intervals, thresholds)
- Resource requests/limits for FastAPI pods on GKE Autopilot
- GCP WIF pool and provider naming convention
- Exact reusable workflow input parameters and secret passing
- Whether to include Temporal dashboards in Grafana provisioning (already have FastAPI dashboard from Phase 4)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/workstreams/gks-refactor/REQUIREMENTS.md` SS APP — APP-01 through APP-06 define all application workload requirements
- `.planning/workstreams/gks-refactor/REQUIREMENTS.md` SS CD — CD-01 through CD-05 define all CI/CD pipeline requirements

### Architecture decisions
- `.planning/workstreams/gks-refactor/research/ARCHITECTURE.md` SS "Pulumi Program Structure" — Single program, three stacks pattern
- `.planning/workstreams/gks-refactor/research/ARCHITECTURE.md` SS "Namespace Layout" — vici namespace for app workloads

### Existing Pulumi components (patterns to follow)
- `infra/components/migration.py` — Cloud SQL Auth Proxy native sidecar pattern (Job + sidecar init container). App Deployment MUST follow this same pattern for DB connectivity.
- `infra/components/secrets.py` — All 11 ExternalSecrets already defined. `envFrom` ref pattern for secret injection.
- `infra/components/prometheus.py` — `fastapi_service_monitor` already created; app Service must match its selector labels
- `infra/components/jaeger.py` — `OTEL_EXPORTER_OTLP_ENDPOINT` already wired via ExternalSecret
- `infra/components/namespaces.py` — `k8s_provider`, `namespaces` dict (vici, cert-manager already exist)
- `infra/components/registry.py` — `registry_url` export (used for image reference in Deployment)
- `infra/components/iam.py` — `vici_app_ksa` (KSA `vici-app` in `vici` namespace) already provisioned
- `infra/__main__.py` — Entry point; new components registered here

### Existing CI/CD
- `.github/workflows/ci.yml` — Current CI pipeline (pytest + ruff). CD-05 says this stays unchanged.

### Application
- `Dockerfile` — Multi-stage build, non-root user, HEALTHCHECK on /health. Ready for GKE as-is.
- `src/main.py` — FastAPI app with lifespan (Temporal worker starts here)

### Prior phase context
- `.planning/workstreams/gks-refactor/phases/03-temporal-in-cluster/03-CONTEXT.md` — D-13: Temporal UI Ingress deferred to Phase 5
- `.planning/workstreams/gks-refactor/phases/04-observability-stack/04-CONTEXT.md` — D-10: All observability UIs deferred to Phase 5 as ClusterIP-only

### Pulumi config
- `infra/Pulumi.yaml` — Project definition
- `infra/config.py` — Typed config wrapper (ENV, PROJECT_ID, REGION, CLUSTER_NAME)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `infra/components/migration.py` — Auth Proxy sidecar pattern (volumes, socket mount, security context, `run_as_non_root`, `restart_policy: Always` on init container). Reuse verbatim for app Deployment's DB sidecar.
- `infra/components/secrets.py` — `external_secrets` dict keyed by slug (e.g., `external_secrets["database-url"]`). App Deployment depends_on these.
- `infra/components/registry.py` — `registry_url` Output for constructing image references (`registry_url + "/vici:" + ENV`)
- `infra/components/prometheus.py` — `fastapi_service_monitor` already targets app pods; app Service needs matching labels
- `Dockerfile` — Production-ready, CMD runs uvicorn on port 8000, HEALTHCHECK on /health

### Established Patterns
- **Helm release via Pulumi**: `k8s.helm.v3.Release` with `repository_opts`, pinned `chart_version`, `create_namespace=False`, `ResourceOptions(provider=k8s_provider, depends_on=[...])` — see `opensearch.py`, `temporal.py`, `secrets.py`
- **Module-level constants**: All image tags, chart versions, port numbers as `_CONST_NAME` at module top
- **Component registration**: New file in `infra/components/`, imported in `infra/__main__.py`
- **Native sidecar**: K8s 1.28+ `restart_policy: Always` on init containers — established in `migration.py`
- **No magic numbers**: All values must be named constants

### Integration Points
- FastAPI app -> Cloud SQL via Auth Proxy sidecar (DATABASE_URL secret uses socket format)
- FastAPI app -> Temporal via `TEMPORAL_HOST` secret (`temporal-frontend.temporal.svc.cluster.local:7233`)
- FastAPI app -> Jaeger via `OTEL_EXPORTER_OTLP_ENDPOINT` secret (`http://jaeger-collector.observability.svc.cluster.local:4317`)
- Prometheus -> FastAPI `/metrics` via `fastapi_service_monitor` (already created in Phase 4)
- GKE Ingress -> FastAPI Service (port 8000)
- cert-manager Issuer -> Let's Encrypt (ACME HTTP-01 challenge via Ingress)
- GitHub Actions -> GCP via WIF (OIDC token exchange)
- GitHub Actions -> Artifact Registry (docker push)
- GitHub Actions -> Pulumi (pulumi up with GCS state backend)

</code_context>

<specifics>
## Specific Ideas

- Reusable workflow pattern: `.github/workflows/cd-base.yml` defines the build-push-deploy job; per-env files (`cd-dev.yml`, etc.) call it with env-specific inputs (stack name, trigger conditions, approval requirements)
- usevici.com subdomain scheme in Pulumi stack configs — DNS must be configured in Squarespace pointing subdomains to GKE Ingress IPs after first pulumi up
- Let's Encrypt staging issuer name should be clearly distinguishable (e.g., `letsencrypt-staging` vs `letsencrypt-prod`) so switching is a single value change in Ingress annotations

</specifics>

<deferred>
## Deferred Ideas

- Expose Temporal UI, Grafana, and Jaeger UI via public Ingress — requires authentication for each service first (todo created)
- Semver image tagging from git tags — todo created for future CD enhancement
- Auto port-forward for in-cluster MCP servers on dev — reviewed, kept as separate backlog item
- Custom domain activation (usevici.com) — DNS configuration in Squarespace required before Phase 5 execution. Point dev.usevici.com, staging.usevici.com, and usevici.com to GKE Ingress IPs after first pulumi up.

### Reviewed Todos (not folded)
- "Auto port-forward for in-cluster MCP servers on dev" — out of scope for Phase 5; DX tooling, not production deployment

</deferred>

---

*Phase: 05-application-deployment-and-ci-cd*
*Context gathered: 2026-04-05*
