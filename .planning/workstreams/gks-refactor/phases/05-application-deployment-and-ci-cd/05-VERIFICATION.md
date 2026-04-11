---
phase: 05-application-deployment-and-ci-cd
verified: 2026-04-05T12:00:00Z
status: human_needed
score: 3/5 must-haves verified (2 require runtime/human confirmation)
re_verification: false
human_verification:
  - test: "GET /health returns HTTP 200 from public GKE Ingress hostname with valid TLS"
    expected: "curl https://dev.usevici.com/health returns HTTP 200 with a valid Let's Encrypt certificate"
    why_human: "Requires DNS to be configured in Squarespace pointing dev.usevici.com to GKE Ingress IP, pulumi up to have run, and cert-manager to have issued a certificate. Cannot verify without live infrastructure."
  - test: "Temporal worker is connected to in-cluster Temporal Server and appears in Temporal UI"
    expected: "kubectl port-forward on Temporal UI shows the vici-worker registered and processing workflows"
    why_human: "Requires running cluster with all prior phases (2, 3) executed. Cannot verify worker connectivity from static code analysis alone."
---

# Phase 5: Application Deployment and CI/CD Verification Report

**Phase Goal:** FastAPI app serves traffic on environment-specific public hostnames with TLS, auto-scales under load, and deploys automatically via GitHub Actions
**Verified:** 2026-04-05T12:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `GET /health` returns HTTP 200 from the public GKE Ingress hostname with valid TLS certificate in all three environments | ? HUMAN | Infrastructure wired correctly: `/health` liveness probe on `_APP_PORT=8000`, GKE Ingress annotated with cert-manager issuer, TLS secret configured in `infra/components/ingress.py`. DNS and live cert require human confirmation. |
| 2 | Temporal worker is connected to the in-cluster Temporal Server and appears in Temporal UI | ? HUMAN | `src/main.py` lifespan starts `run_worker()` as asyncio task; `temporal-host` envFrom wires `TEMPORAL_HOST` from ExternalSecret. Runtime connectivity requires human confirmation with live cluster. |
| 3 | HPA scales the FastAPI Deployment between 1 and 3 replicas based on CPU | ✓ VERIFIED | `infra/components/app.py` line 219: `k8s.autoscaling.v2.HorizontalPodAutoscaler` with `min_replicas=_APP_MIN_REPLICAS` (1), `max_replicas=_APP_MAX_REPLICAS` (3), `average_utilization=_CPU_TARGET_UTILIZATION` (70). |
| 4 | Pushing to `main` triggers a GitHub Actions job that builds, pushes to Artifact Registry, and runs `pulumi up --stack dev` with no static GCP credentials | ✓ VERIFIED | `cd-dev.yml` triggers on `push: branches: [main]`, calls `cd-base.yml` with `command: up`, `stack: dev`. `cd-base.yml` uses `google-github-actions/auth@v3` with WIF secrets; no static credentials present. |
| 5 | `pulumi up --stack prod` requires manual workflow dispatch with environment approval gate | ✓ VERIFIED | `cd-prod.yml` has only `workflow_dispatch` trigger and passes `environment: prod` to `cd-base.yml` which sets `environment: ${{ inputs.environment }}` on the job, activating GitHub environment approval gate. |

**Score:** 3/5 truths verified (2 require human/runtime confirmation)

### Deferred Items

No items deferred. Phase 5 is the final milestone phase.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `infra/components/app.py` | FastAPI Deployment + Service + HPA | ✓ VERIFIED | 258 lines. Full Deployment with Auth Proxy sidecar, 11 envFrom, readiness/liveness probes, ClusterIP Service, autoscaling/v2 HPA. Python syntax OK. ruff passes. |
| `infra/components/certmanager.py` | cert-manager Helm release | ✓ VERIFIED | 43 lines. Helm release v1.20.0 from charts.jetstack.io, CRDs enabled, cert-manager namespace. Python syntax OK. ruff passes. |
| `infra/components/ingress.py` | Issuers + placeholder TLS + GKE Ingress + WEBHOOK_BASE_URL SecretVersion | ✓ VERIFIED | 164 lines. staging+prod Issuers (namespace-scoped), placeholder TLS Secret, GKE Ingress with annotation-based class, SecretVersion for WEBHOOK_BASE_URL. No ClusterIssuer. No ingressClassName. |
| `infra/components/cd.py` | WIF pool + provider + CI SA IAM bindings | ✓ VERIFIED | 108 lines. WIF pool + OIDC provider scoped to `ahcarpenter` org, IAMBinding for workloadIdentityUser, IAMMember for storage.objectAdmin and container.developer. No static credentials. |
| `infra/Pulumi.dev.yaml` | app_hostname and github_org stack config | ✓ VERIFIED | Contains `vici-infra:app_hostname: dev.usevici.com` and `vici-infra:github_org: ahcarpenter`. |
| `infra/Pulumi.staging.yaml` | app_hostname and github_org stack config | ✓ VERIFIED | Contains `vici-infra:app_hostname: staging.usevici.com` and `vici-infra:github_org: ahcarpenter`. |
| `infra/Pulumi.prod.yaml` | app_hostname and github_org stack config | ✓ VERIFIED | Contains `vici-infra:app_hostname: usevici.com` and `vici-infra:github_org: ahcarpenter`. |
| `infra/config.py` | APP_HOSTNAME and GITHUB_ORG exports | ✓ VERIFIED | Line 11: `APP_HOSTNAME: str = cfg.require("app_hostname")`, line 12: `GITHUB_ORG: str = cfg.require("github_org")`. |
| `.github/workflows/cd-base.yml` | Reusable CD workflow | ✓ VERIFIED | `workflow_call` trigger, `id-token: write` permission, `google-github-actions/auth@v3`, `pulumi/actions@v6`, docker build+push with `if: inputs.command == 'up'` guard. |
| `.github/workflows/cd-dev.yml` | Dev CD trigger | ✓ VERIFIED | `push: branches: [main]` trigger, `command: up`, `stack: dev`. |
| `.github/workflows/cd-staging.yml` | Staging CD trigger | ✓ VERIFIED | `pull_request` and `workflow_dispatch` triggers; preview on PR, up on dispatch. |
| `.github/workflows/cd-prod.yml` | Prod CD trigger | ✓ VERIFIED | `workflow_dispatch` only, `environment: prod` input. |
| `infra/__main__.py` | All Phase 5 component imports wired | ✓ VERIFIED | 16 component imports total. All four Phase 5 components present: `components.app`, `components.certmanager`, `components.ingress` (with `webhook_base_url_version`), `components.cd`. |
| `.github/workflows/ci.yml` | UNCHANGED (pytest, no GCP) | ✓ VERIFIED | Contains `pytest` on line 28, no GCP auth or cloud dependencies. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `infra/components/app.py` | `infra/components/migration.py` | `_AUTH_PROXY_IMAGE` constant reuse | ✓ WIRED | `_AUTH_PROXY_IMAGE = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1"` present at module top; `restart_policy="Always"` native sidecar pattern replicated. |
| `infra/components/app.py` | `infra/components/secrets.py` | `envFrom` secret references | ✓ WIRED | `from components.secrets import external_secrets`; `[external_secrets[slug] for slug in _ENV_FROM_SOURCES]` in depends_on; all 11 slugs verified. |
| `infra/components/ingress.py` | `infra/components/certmanager.py` | `depends_on certmanager_release` for CRDs | ✓ WIRED | `from components.certmanager import certmanager_release`; both Issuers have `depends_on=[certmanager_release, namespaces["vici"]]`. |
| `infra/components/ingress.py` | `infra/components/app.py` | `app_service` in Ingress depends_on | ✓ WIRED | `from components.app import app_service`; `depends_on=[tls_secret_placeholder, staging_issuer, prod_issuer, app_service]` on Ingress. |
| `infra/components/ingress.py` | GCP Secret Manager | `gcp.secretmanager.SecretVersion` for WEBHOOK_BASE_URL | ✓ WIRED | `webhook_base_url_version = gcp.secretmanager.SecretVersion(...)` writing `https://{APP_HOSTNAME}` to `{ENV}-webhook-base-url` secret. |
| `.github/workflows/cd-dev.yml` | `.github/workflows/cd-base.yml` | `uses: ./.github/workflows/cd-base.yml` | ✓ WIRED | All three per-env workflow files use `uses: ./.github/workflows/cd-base.yml` with `secrets: inherit`-equivalent pattern. |
| `infra/components/cd.py` | `infra/components/identity.py` | `ci_push_sa` for WIF binding | ✓ WIRED | `from components.identity import ci_push_sa`; used in `IAMBinding` and both `IAMMember` resources. |
| `infra/__main__.py` | `infra/components/app.py` | import registration | ✓ WIRED | `from components.app import app_deployment, app_hpa, app_service  # noqa: F401` present. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `infra/components/app.py` Deployment | `registry_url`, `ENV`, `app_db_instance.connection_name` | `components.registry.registry_url`, `config.ENV`, `components.database.app_db_instance` | Yes — Pulumi Outputs from actual provisioned resources | ✓ FLOWING |
| `infra/components/ingress.py` Ingress | `APP_HOSTNAME` | `config.APP_HOSTNAME` from `cfg.require("app_hostname")` — stack config value | Yes — populated from Pulumi.dev.yaml / Pulumi.staging.yaml / Pulumi.prod.yaml | ✓ FLOWING |
| `infra/components/ingress.py` SecretVersion | `secret_data` | `pulumi.Output.concat("https://", APP_HOSTNAME)` | Yes — derived from stack config, no hardcoding | ✓ FLOWING |
| `infra/components/cd.py` WIF provider | `GITHUB_ORG`, `PROJECT_ID`, `ENV` | `config.GITHUB_ORG`, `config.PROJECT_ID`, `config.ENV` | Yes — all from stack config | ✓ FLOWING |

### Behavioral Spot-Checks

Step 7b: SKIPPED — Phase 5 produces Pulumi IaC components, not runnable local entry points. Verification requires a live GKE cluster with `pulumi up` executed against it. Runtime behavior is covered by the human verification items.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| APP-01 | 05-01 | FastAPI Deployment in vici namespace with Auth Proxy sidecar and ExternalSecret-injected secrets | ✓ SATISFIED | `infra/components/app.py`: Deployment in `vici` namespace, Cloud SQL Auth Proxy native sidecar (`restart_policy="Always"`), 11 envFrom entries covering all ExternalSecrets. |
| APP-02 | 05-01 | Temporal worker in same pod as FastAPI app (lifespan background task) | ✓ SATISFIED | Single `vici-app` container in Deployment; `src/main.py` lifespan starts `run_worker()` as asyncio task. No separate Temporal worker Deployment created. |
| APP-03 | 05-01 | HPA for FastAPI Deployment (min 1, max 3 replicas, CPU 70%) | ✓ SATISFIED | `infra/components/app.py`: `k8s.autoscaling.v2.HorizontalPodAutoscaler` with `min_replicas=1`, `max_replicas=3`, `average_utilization=70`. |
| APP-04 | 05-02 | GKE Ingress on environment-specific hostname with TLS | ✓ SATISFIED | `infra/components/ingress.py`: GKE Ingress with `kubernetes.io/ingress.class: gce`, TLS using `vici-tls` secret, host=`APP_HOSTNAME`. cert-manager Issuers provisioned. |
| APP-05 | 05-01, 05-02 | GET /health returns HTTP 200 from public GKE Ingress hostname | ? HUMAN | Liveness probe on `/health` defined in Deployment; Ingress routes to vici-app Service. Live DNS and TLS cert issuance required for full validation. |
| APP-06 | 05-02 | WEBHOOK_BASE_URL secret set to GKE Ingress public hostname | ✓ SATISFIED | `infra/components/ingress.py`: `gcp.secretmanager.SecretVersion` writes `https://{APP_HOSTNAME}` to `{ENV}-webhook-base-url` GCP secret. |
| CD-01 | 05-03 | CD job builds Docker image, pushes to Artifact Registry, runs `pulumi up --stack dev` on push to main | ✓ SATISFIED | `cd-dev.yml`: `push: branches: [main]` trigger; `cd-base.yml` docker build+push step with SHA+env tagging; `pulumi/actions@v6` with `command: up`, `stack-name: dev`. |
| CD-02 | 05-03 | `pulumi preview --stack staging` on PRs; `pulumi up --stack staging` on workflow dispatch | ✓ SATISFIED | `cd-staging.yml`: two conditional jobs — `preview` on `pull_request`, `deploy` on `workflow_dispatch`, both calling cd-base.yml with appropriate command. |
| CD-03 | 05-03 | `pulumi up --stack prod` requires manual dispatch with environment approval gate | ✓ SATISFIED | `cd-prod.yml`: `workflow_dispatch` only trigger; `environment: prod` passed to cd-base.yml job. |
| CD-04 | 05-03 | Pulumi state access via Workload Identity (no static GCP credentials) | ✓ SATISFIED | `infra/components/cd.py`: WIF pool + OIDC provider + IAMBinding; `cd-base.yml`: `google-github-actions/auth@v3` with `workload_identity_provider` and `service_account` secrets. No JSON keys in any workflow or component file. |
| CD-05 | 05-03 | CI test job unchanged: pytest with SQLite, no GCP dependency | ✓ SATISFIED | `.github/workflows/ci.yml` unchanged. Contains `pytest tests/` with SQLite `DATABASE_URL`. No GCP auth or cloud provider dependency. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `infra/components/ingress.py` | 81-86 | `tls_secret_placeholder` with empty `tls.crt`/`tls.key` | ℹ️ Info | Intentional architectural pattern. Documented in RESEARCH.md and SUMMARY as the GKE Ingress chicken-and-egg workaround. cert-manager replaces this secret after ACME challenge completes. Not a stub. |

No blocking anti-patterns found.

### Human Verification Required

#### 1. Public HTTPS Health Endpoint (APP-05, Roadmap SC-1)

**Test:** After `pulumi up --stack dev` and DNS configured in Squarespace pointing `dev.usevici.com` to the GKE Ingress IP:
```
curl -v https://dev.usevici.com/health
```
**Expected:** HTTP 200 response with valid TLS certificate issued by Let's Encrypt (check for cert-manager annotation `letsencrypt-staging` → `letsencrypt-prod` switch once staging cert verifies)
**Why human:** Requires live DNS propagation, cert-manager ACME HTTP-01 challenge completion, and running GKE cluster from Phase 5 `pulumi up`. DNS must be configured in Squarespace.

#### 2. Temporal Worker Connectivity (APP-02, Roadmap SC-2)

**Test:** After all phases are deployed:
```
kubectl port-forward -n temporal svc/temporal-web 8088:8088
```
Open `http://localhost:8088` → Workflows tab → verify vici worker is registered.
**Expected:** Temporal UI shows the `vici-worker` task queue with connected workers.
**Why human:** Requires live cluster with Phase 2 (Cloud SQL/secrets), Phase 3 (Temporal Server), and Phase 5 (app Deployment) all successfully applied. Worker connectivity depends on `TEMPORAL_HOST` ExternalSecret resolving to the correct Temporal frontend service address at runtime.

### Gaps Summary

No gaps found. All artifacts exist, are substantive, and are wired correctly. All 11 Phase 5 requirements (APP-01 through APP-06, CD-01 through CD-05) are addressed in code.

The 2 human verification items (APP-05 live TLS health check, APP-02 Temporal worker connectivity) are operational validation concerns that require live infrastructure — the IaC code implementing them is complete and correct.

**Note on commit hash discrepancy:** SUMMARY files for Plan 03 document commit hashes `2964d51`, `071e6b0`, `ab8d141` which do not match the git log. The actual commits are `ea494f2`, `c5f9244`, `d50fd2d` with equivalent content. This discrepancy is informational only — all files exist and match expected content.

---

_Verified: 2026-04-05T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
