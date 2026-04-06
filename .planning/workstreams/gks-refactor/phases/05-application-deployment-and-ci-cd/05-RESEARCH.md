# Phase 5: Application Deployment and CI/CD - Research

**Researched:** 2026-04-05
**Domain:** GKE application deployment (FastAPI + HPA + Ingress + cert-manager) and GitHub Actions CD pipeline with GCP Workload Identity Federation
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Hostname & DNS Convention**
- D-01: Use GKE auto-assigned IPs for v1 (no custom domain purchase required)
- D-02: Stub out a `getvici.ai` subdomain scheme in Pulumi stack configs (`dev.getvici.ai`, `staging.getvici.ai`, `getvici.ai`) so switching to custom domains later is a config change only
- D-03: Only the FastAPI app gets public Ingress in Phase 5. Temporal UI, Grafana, and Jaeger UI remain ClusterIP-only — operators use `kubectl port-forward`
- D-04: Internal UIs must NOT be exposed via Ingress until authentication is in place for each service

**CI/CD Pipeline Design**
- D-05: Per-environment workflow files (`cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`) calling a shared reusable workflow (`.github/workflows/cd-base.yml`). CI stays separate in `ci.yml`
- D-06: Image tagging: short git SHA (e.g., `abc1234`) + environment tag (e.g., `dev`, `staging`, `prod`)
- D-07: GitHub Actions authenticates to GCP via Workload Identity Federation (GitHub OIDC -> GCP WIF pool + provider). No static GCP service account keys
- D-08: `cd-dev.yml` triggers on push to `main` — builds, pushes to Artifact Registry, runs `pulumi up --stack dev`
- D-09: `cd-staging.yml` runs `pulumi preview --stack staging` on PRs; `pulumi up --stack staging` on explicit workflow dispatch
- D-10: `cd-prod.yml` requires manual workflow dispatch with GitHub environment approval gate
- D-11: CI test job (`ci.yml`) unchanged — pytest with SQLite, no GCP dependency

**cert-manager Deployment**
- D-12: Deploy cert-manager via Helm in the `cert-manager` namespace as `infra/components/certmanager.py`
- D-13: Use namespace-scoped `Issuer` (not `ClusterIssuer`) — consistent with namespace-scoped SecretStore pattern
- D-14: Deploy with Let's Encrypt staging issuer first; switch to production issuer once Ingress is verified. Both issuers can coexist.

**App Deployment Shape**
- D-15: Three Pulumi component files: `infra/components/app.py` (Deployment + Service + HPA + ServiceMonitor reference), `infra/components/ingress.py` (Ingress + cert-manager Issuer + Certificate), `infra/components/cd.py` (WIF pool + provider + CI service account bindings)
- D-16: Environment variables injected via `envFrom` per ExternalSecret-generated K8s Secret — 11 `envFrom` entries matching `migration.py` pattern
- D-17: FastAPI Deployment in `vici` namespace with Cloud SQL Auth Proxy native sidecar, referencing `vici-app` KSA
- D-18: Temporal worker runs as a lifespan background task in the same pod — no separate Deployment
- D-19: HPA configured for FastAPI Deployment: min 1, max 3 replicas, CPU target 70%

### Claude's Discretion
- cert-manager Helm chart version to pin (verify latest stable at deploy time)
- Readiness/liveness probe configuration (path, intervals, thresholds)
- Resource requests/limits for FastAPI pods on GKE Autopilot
- GCP WIF pool and provider naming convention
- Exact reusable workflow input parameters and secret passing
- Whether to include Temporal dashboards in Grafana provisioning (already have FastAPI dashboard from Phase 4)

### Deferred Ideas (OUT OF SCOPE)
- Expose Temporal UI, Grafana, and Jaeger UI via public Ingress (requires authentication first)
- Semver image tagging from git tags
- Auto port-forward for in-cluster MCP servers on dev
- Custom domain activation (getvici.ai) — stubbed in config, activate when DNS is ready
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| APP-01 | FastAPI app Deployment in `vici` namespace with Cloud SQL Auth Proxy native sidecar and all secrets from ExternalSecret-generated K8s Secrets | `infra/components/app.py` — extends `migration.py` sidecar pattern; 11 `envFrom` entries from `secrets.py` |
| APP-02 | Temporal worker runs in same pod as FastAPI (lifespan background task), connects to in-cluster Temporal | `src/main.py` already implements this — no code change needed; Deployment spec uses same container |
| APP-03 | HPA for FastAPI Deployment: min 1, max 3 replicas, CPU target 70% | `k8s.autoscaling.v2.HorizontalPodAutoscaler` with `average_utilization: 70` |
| APP-04 | GKE Ingress exposes FastAPI on env-specific public hostname with TLS via cert-manager + Let's Encrypt | `infra/components/ingress.py` — Issuer + Certificate + Ingress; see chicken-and-egg pitfall |
| APP-05 | `GET /health` returns HTTP 200 from GKE Ingress public hostname in all three envs | `/health` endpoint already exists in `src/main.py`; validated via GKE Ingress after cert provision |
| APP-06 | `WEBHOOK_BASE_URL` secret set to GKE Ingress public hostname | Already defined as ExternalSecret in `secrets.py`; value populated in GCP Secret Manager per env |
| CD-01 | GitHub Actions CD builds image, pushes to Artifact Registry, runs `pulumi up --stack dev` on push to `main` | `cd-dev.yml` triggers on push to `main`; calls `cd-base.yml` |
| CD-02 | GitHub Actions runs `pulumi preview --stack staging` on PR; `pulumi up --stack staging` on workflow dispatch | `cd-staging.yml` with dual-trigger pattern |
| CD-03 | `pulumi up --stack prod` requires manual workflow dispatch with environment approval gate | `cd-prod.yml` with GitHub environment `prod` requiring required reviewers |
| CD-04 | Pulumi state access uses Workload Identity (GitHub Actions OIDC -> GCP) — no static keys | `infra/components/cd.py` provisions WIF pool + provider; `google-github-actions/auth@v3` in workflows |
| CD-05 | CI test job unchanged: pytest with SQLite, no GCP dependency | `.github/workflows/ci.yml` — do not modify |
</phase_requirements>

---

## Summary

Phase 5 completes the GKE migration by deploying the FastAPI application as a Kubernetes Deployment with Cloud SQL Auth Proxy native sidecar (reusing the `migration.py` pattern verbatim), exposing it via GKE Ingress with TLS from cert-manager and Let's Encrypt, and automating deployments through a GitHub Actions CD pipeline using GCP Workload Identity Federation.

The application code requires zero changes — `src/main.py` already runs the Temporal worker as a lifespan background task, exposes `/health` and `/readyz` endpoints, and emits Prometheus metrics. The Dockerfile is production-ready. The primary work is three new Pulumi components (`app.py`, `ingress.py`, `cd.py`) and four new GitHub Actions workflow files (`cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`).

The critical technical risk is the GKE Ingress + cert-manager chicken-and-egg problem: the `ingress-gce` controller requires the TLS Secret to exist before it will create forwarding rules, but Let's Encrypt won't issue the certificate until it can reach the ACME challenge URL. The workaround is creating an empty placeholder `kubernetes.io/tls` Secret in the Pulumi Ingress component before applying the Ingress resource. Both Let's Encrypt staging and production issuers should be provisioned; use staging first to avoid rate limits, then flip the `cert-manager.io/issuer` annotation once verified.

**Primary recommendation:** Deploy in order: `certmanager.py` → `app.py` → `ingress.py` → `cd.py`. The WIF pool/provider provisioning in `cd.py` is independent and can be provisioned earlier, but CI workflows cannot be tested until it exists.

---

## Standard Stack

### Core

| Library / Tool | Version | Purpose | Why Standard |
|----------------|---------|---------|--------------|
| cert-manager | 1.20.0 | Automated TLS certificate provisioning via ACME | Official CNCF project; GKE-native; well-documented GCE integration |
| `k8s.autoscaling.v2.HorizontalPodAutoscaler` | Pulumi k8s v4 | CPU-based HPA | autoscaling/v2 is stable API; v1 is deprecated |
| `google-github-actions/auth@v3` | v3 | GitHub Actions -> GCP OIDC authentication | Official Google action; supports direct WIF and SA impersonation |
| `pulumi/actions@v6` | v6 | Run Pulumi CLI in GitHub Actions | Official Pulumi action; handles stack selection and output capture |

**cert-manager version verification:** [VERIFIED: cert-manager releases page] — v1.20.0 released 2026-03-09, latest stable as of research date.

### Supporting

| Library / Tool | Version | Purpose | When to Use |
|----------------|---------|---------|-------------|
| cert-manager Helm repo | `https://charts.jetstack.io` | Legacy HTTP repo for Helm install | Use for `k8s.helm.v3.Release` in Pulumi — OCI charts not yet idiomatic in Pulumi Python |
| `actions/checkout@v4` | v4 | Checkout code in GitHub Actions | Standard; matches existing `ci.yml` |
| `docker/setup-buildx-action@v3` | v3 | Multi-platform Docker builds | Standard for GitHub Actions Docker builds |
| `docker/login-action@v3` | v3 | Authenticate Docker to Artifact Registry | Standard; use with GOOGLE_APPLICATION_CREDENTIALS from WIF |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| cert-manager + Let's Encrypt | Google-managed certificates | GCP managed certs require static IP reservation and have longer provisioning time; cert-manager is portable and aligns with `Issuer`-per-namespace pattern already established |
| GKE Ingress (`ingress-gce`) | GKE Gateway API | Gateway API is more capable but adds Gateway/HTTPRoute CRD complexity; GKE Ingress matches what ARCHITECTURE.md locked; CONTEXT.md locked this decision |
| `workflow_call` reusable workflow | Composite actions or separate full workflows | `workflow_call` allows environment-level protection rules and is the idiomatic GitHub pattern for per-environment CD |

**Installation (cert-manager Helm):**
```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm install cert-manager jetstack/cert-manager --namespace cert-manager --version v1.20.0 --set crds.enabled=true
```

In Pulumi (`certmanager.py`), this becomes `k8s.helm.v3.Release` with `values={"crds": {"enabled": True}}`.

---

## Architecture Patterns

### Recommended Project Structure (new files only)

```
infra/components/
├── app.py           # FastAPI Deployment + Service + HPA (Phase 5)
├── ingress.py       # GKE Ingress + cert-manager Issuer + Certificate (Phase 5)
├── certmanager.py   # cert-manager Helm release (Phase 5)
└── cd.py            # WIF pool + provider + CI SA IAM bindings (Phase 5)

.github/workflows/
├── ci.yml           # UNCHANGED (CD-05)
├── cd-base.yml      # Reusable workflow: build + push + pulumi up
├── cd-dev.yml       # Calls cd-base.yml; triggers on push to main
├── cd-staging.yml   # Calls cd-base.yml; triggers on PR (preview) + dispatch (up)
└── cd-prod.yml      # Calls cd-base.yml; requires manual dispatch + environment approval

infra/Pulumi.dev.yaml     # Add: app_hostname, wif_pool_id, wif_provider_id
infra/Pulumi.staging.yaml # Add: app_hostname, wif_pool_id, wif_provider_id
infra/Pulumi.prod.yaml    # Add: app_hostname, wif_pool_id, wif_provider_id
```

### Pattern 1: FastAPI Deployment with Auth Proxy Native Sidecar

**What:** Replicate `migration.py` sidecar pattern for the long-running Deployment. Same volumes, socket mount, `restart_policy: Always` on init container.

**When to use:** Any pod that needs Cloud SQL connectivity via IAM-authenticated Unix socket.

**Key differences from `migration.py`:**
- `restart_policy` on the Pod spec is absent (Deployment default is `Always`)
- Add `readiness_probe` and `liveness_probe` targeting `/readyz` and `/health`
- Add all 11 `env_from` entries (not just `database-url`)
- Service with `app: vici` label to match existing `fastapi_service_monitor`

```python
# Source: infra/components/migration.py (extended pattern)
# [VERIFIED: codebase grep — migration.py lines 26-102]

_AUTH_PROXY_IMAGE = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1"
_APP_PORT = 8000
_APP_MIN_REPLICAS = 1
_APP_MAX_REPLICAS = 3
_CPU_TARGET_UTILIZATION = 70

# In the Deployment spec (PodSpec):
init_containers=[
    k8s.core.v1.ContainerArgs(
        name="cloud-sql-proxy",
        image=_AUTH_PROXY_IMAGE,
        restart_policy="Always",  # K8s 1.28+ native sidecar
        args=["--structured-logs", "--private-ip",
              pulumi.Output.concat("--unix-socket=", _SOCKET_MOUNT_PATH),
              app_db_instance.connection_name],
        security_context=k8s.core.v1.SecurityContextArgs(
            run_as_non_root=True,
            run_as_user=_AUTH_PROXY_RUN_AS_USER,
        ),
        volume_mounts=[k8s.core.v1.VolumeMountArgs(
            name=_VOLUME_NAME, mount_path=_SOCKET_MOUNT_PATH)],
    ),
],
containers=[
    k8s.core.v1.ContainerArgs(
        name="vici-app",
        image=pulumi.Output.concat(registry_url, "/vici:", ENV),
        ports=[k8s.core.v1.ContainerPortArgs(
            name="http", container_port=_APP_PORT)],
        env_from=[
            # 11 entries — one per ExternalSecret slug
            k8s.core.v1.EnvFromSourceArgs(
                secret_ref=k8s.core.v1.SecretEnvSourceArgs(name="database-url")),
            k8s.core.v1.EnvFromSourceArgs(
                secret_ref=k8s.core.v1.SecretEnvSourceArgs(name="temporal-host")),
            # ... remaining 9 secrets
        ],
        readiness_probe=k8s.core.v1.ProbeArgs(
            http_get=k8s.core.v1.HTTPGetActionArgs(path="/readyz", port=_APP_PORT),
            initial_delay_seconds=15,
            period_seconds=10,
            failure_threshold=3,
        ),
        liveness_probe=k8s.core.v1.ProbeArgs(
            http_get=k8s.core.v1.HTTPGetActionArgs(path="/health", port=_APP_PORT),
            initial_delay_seconds=30,
            period_seconds=30,
            failure_threshold=3,
        ),
        resources=k8s.core.v1.ResourceRequirementsArgs(
            requests={"cpu": "250m", "memory": "512Mi"},
            limits={"cpu": "500m", "memory": "1Gi"},
        ),
        volume_mounts=[k8s.core.v1.VolumeMountArgs(
            name=_VOLUME_NAME, mount_path=_SOCKET_MOUNT_PATH)],
    ),
],
```

### Pattern 2: HPA with autoscaling/v2

**What:** CPU-target HPA targeting the Deployment (APP-03).

```python
# Source: https://www.pulumi.com/registry/packages/kubernetes/api-docs/autoscaling/v2/horizontalpodautoscaler/
# [CITED: pulumi.com/registry]

hpa = k8s.autoscaling.v2.HorizontalPodAutoscaler(
    "vici-app-hpa",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="vici-app", namespace="vici"),
    spec=k8s.autoscaling.v2.HorizontalPodAutoscalerSpecArgs(
        scale_target_ref=k8s.autoscaling.v2.CrossVersionObjectReferenceArgs(
            api_version="apps/v1",
            kind="Deployment",
            name="vici-app",
        ),
        min_replicas=_APP_MIN_REPLICAS,
        max_replicas=_APP_MAX_REPLICAS,
        metrics=[k8s.autoscaling.v2.MetricSpecArgs(
            type="Resource",
            resource=k8s.autoscaling.v2.ResourceMetricSourceArgs(
                name="cpu",
                target=k8s.autoscaling.v2.MetricTargetArgs(
                    type="Utilization",
                    average_utilization=_CPU_TARGET_UTILIZATION,
                ),
            ),
        )],
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[app_deployment]),
)
```

### Pattern 3: cert-manager Issuer + GKE Ingress TLS

**What:** Namespace-scoped `Issuer` (per D-13) with HTTP-01 ACME solver pointing at the `gce` ingress class. Ingress annotated for cert-manager ingress-shim.

**Critical detail:** The `ingress-gce` controller requires the TLS Secret to exist before it creates forwarding rules. Create an empty placeholder Secret first (see Pitfall 1).

```python
# Source: https://cert-manager.io/docs/tutorials/getting-started-with-cert-manager-on-google-kubernetes-engine-using-lets-encrypt-for-ingress-ssl/
# [CITED: cert-manager.io official docs]

# Staging Issuer (for initial testing — D-14)
staging_issuer = k8s.apiextensions.CustomResource(
    "letsencrypt-staging",
    api_version="cert-manager.io/v1",
    kind="Issuer",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="letsencrypt-staging",
        namespace="vici",
    ),
    spec={
        "acme": {
            "server": "https://acme-staging-v02.api.letsencrypt.org/directory",
            "email": "ops@getvici.ai",
            "privateKeySecretRef": {"name": "letsencrypt-staging-key"},
            "solvers": [{
                "http01": {
                    "ingress": {"class": "gce"}
                }
            }]
        }
    },
    opts=ResourceOptions(provider=k8s_provider, depends_on=[certmanager_release]),
)

# Production Issuer (coexists with staging — D-14)
prod_issuer = k8s.apiextensions.CustomResource(
    "letsencrypt-prod",
    api_version="cert-manager.io/v1",
    kind="Issuer",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="letsencrypt-prod",
        namespace="vici",
    ),
    spec={
        "acme": {
            "server": "https://acme-v02.api.letsencrypt.org/directory",
            "email": "ops@getvici.ai",
            "privateKeySecretRef": {"name": "letsencrypt-prod-key"},
            "solvers": [{
                "http01": {
                    "ingress": {"class": "gce"}
                }
            }]
        }
    },
    opts=ResourceOptions(provider=k8s_provider, depends_on=[certmanager_release]),
)

# Empty placeholder TLS Secret — breaks chicken-and-egg (see Pitfall 1)
tls_secret_placeholder = k8s.core.v1.Secret(
    "vici-tls-placeholder",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="vici-tls", namespace="vici"),
    type="kubernetes.io/tls",
    string_data={"tls.crt": "", "tls.key": ""},
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["vici"]]),
)

# GKE Ingress
ingress = k8s.networking.v1.Ingress(
    "vici-ingress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="vici-ingress",
        namespace="vici",
        annotations={
            "kubernetes.io/ingress.class": "gce",
            "kubernetes.io/ingress.allow-http": "true",
            "cert-manager.io/issuer": "letsencrypt-staging",  # Switch to letsencrypt-prod post-verify
        },
    ),
    spec=k8s.networking.v1.IngressSpecArgs(
        tls=[k8s.networking.v1.IngressTLSArgs(
            secret_name="vici-tls",
            hosts=[app_hostname],
        )],
        rules=[k8s.networking.v1.IngressRuleArgs(
            host=app_hostname,
            http=k8s.networking.v1.HTTPIngressRuleValueArgs(
                paths=[k8s.networking.v1.HTTPIngressPathArgs(
                    path="/",
                    path_type="Prefix",
                    backend=k8s.networking.v1.IngressBackendArgs(
                        service=k8s.networking.v1.IngressServiceBackendArgs(
                            name="vici-app",
                            port=k8s.networking.v1.ServiceBackendPortArgs(name="http"),
                        )
                    ),
                )]
            ),
        )],
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[tls_secret_placeholder, staging_issuer, prod_issuer, app_service],
    ),
)
```

### Pattern 4: GitHub Actions Reusable Workflow

**What:** `cd-base.yml` defines the build-push-deploy job. Per-env callers pass stack name, trigger conditions, and environment name.

```yaml
# Source: https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows
# [CITED: GitHub Docs]

# .github/workflows/cd-base.yml
on:
  workflow_call:
    inputs:
      stack:
        required: true
        type: string        # "dev" | "staging" | "prod"
      command:
        required: true
        type: string        # "up" | "preview"
      environment:
        required: false
        type: string        # GitHub environment name for approval gate
    secrets:
      WIF_PROVIDER:
        required: true      # projects/NUMBER/locations/global/workloadIdentityPools/POOL/providers/PROVIDER
      WIF_SERVICE_ACCOUNT:
        required: true      # ci-deploy@vici-app-ENV.iam.gserviceaccount.com
      PULUMI_ACCESS_TOKEN:
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}  # Enables approval gate for prod
    permissions:
      contents: read
      id-token: write     # Required for OIDC token exchange

    steps:
      - uses: actions/checkout@v4

      - uses: google-github-actions/auth@v3
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.WIF_SERVICE_ACCOUNT }}

      - name: Configure Docker for Artifact Registry
        run: gcloud auth configure-docker us-central1-docker.pkg.dev

      - name: Build and push image
        run: |
          IMAGE="us-central1-docker.pkg.dev/${{ env.PROJECT_ID }}/vici-images/vici"
          SHA=$(git rev-parse --short HEAD)
          docker build -t "${IMAGE}:${SHA}" -t "${IMAGE}:${{ inputs.stack }}" .
          docker push "${IMAGE}:${SHA}"
          docker push "${IMAGE}:${{ inputs.stack }}"

      - uses: pulumi/actions@v6
        with:
          command: ${{ inputs.command }}
          stack-name: ${{ inputs.stack }}
          work-dir: infra
        env:
          PULUMI_ACCESS_TOKEN: ${{ secrets.PULUMI_ACCESS_TOKEN }}

# .github/workflows/cd-dev.yml
on:
  push:
    branches: [main]

jobs:
  deploy-dev:
    uses: ./.github/workflows/cd-base.yml
    with:
      stack: dev
      command: up
    secrets:
      WIF_PROVIDER: ${{ secrets.GCP_WIF_PROVIDER_DEV }}
      WIF_SERVICE_ACCOUNT: ${{ secrets.GCP_CI_SA_DEV }}
      PULUMI_ACCESS_TOKEN: ${{ secrets.PULUMI_ACCESS_TOKEN }}

# .github/workflows/cd-prod.yml
on:
  workflow_dispatch:

jobs:
  deploy-prod:
    uses: ./.github/workflows/cd-base.yml
    with:
      stack: prod
      command: up
      environment: prod     # GitHub environment with required reviewers
    secrets:
      WIF_PROVIDER: ${{ secrets.GCP_WIF_PROVIDER_PROD }}
      WIF_SERVICE_ACCOUNT: ${{ secrets.GCP_CI_SA_PROD }}
      PULUMI_ACCESS_TOKEN: ${{ secrets.PULUMI_ACCESS_TOKEN }}
```

### Pattern 5: GCP WIF Pool + Provider via Pulumi (`cd.py`)

**What:** Provision the WIF pool, OIDC provider, and IAM binding in `cd.py`. CI service account (`vici-ci-push`) already exists in `identity.py` — add Pulumi state access role and Artifact Registry push bindings here.

```python
# Source: https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
# [CITED: Google Cloud IAM docs]

_WIF_POOL_ID = f"github-actions-{ENV}"
_WIF_PROVIDER_ID = "github"
_GITHUB_ORG = "YOUR_GITHUB_ORG"   # From config — add to Pulumi.<env>.yaml

wif_pool = gcp.iam.WorkloadIdentityPool(
    "github-wif-pool",
    project=PROJECT_ID,
    workload_identity_pool_id=_WIF_POOL_ID,
    display_name=f"GitHub Actions ({ENV})",
)

wif_provider = gcp.iam.WorkloadIdentityPoolProvider(
    "github-wif-provider",
    project=PROJECT_ID,
    workload_identity_pool_id=wif_pool.workload_identity_pool_id,
    workload_identity_pool_provider_id=_WIF_PROVIDER_ID,
    oidc=gcp.iam.WorkloadIdentityPoolProviderOidcArgs(
        issuer_uri="https://token.actions.githubusercontent.com",
    ),
    attribute_mapping={
        "google.subject": "assertion.sub",
        "attribute.actor": "assertion.actor",
        "attribute.repository": "assertion.repository",
        "attribute.repository_owner": "assertion.repository_owner",
    },
    attribute_condition=f"assertion.repository_owner == '{_GITHUB_ORG}'",
    opts=ResourceOptions(depends_on=[wif_pool]),
)

# Grant CI SA impersonation to the WIF pool (scoped to specific repo)
ci_wif_binding = gcp.serviceaccount.IAMBinding(
    "ci-wif-iam-binding",
    service_account_id=ci_push_sa.name,  # from identity.py
    role="roles/iam.workloadIdentityUser",
    members=[
        pulumi.Output.concat(
            "principalSet://iam.googleapis.com/",
            wif_pool.name,
            "/attribute.repository/",
            _GITHUB_ORG,
            "/vici",
        )
    ],
    opts=ResourceOptions(depends_on=[wif_pool]),
)
```

### Anti-Patterns to Avoid

- **Static GCP service account JSON keys in GitHub Secrets:** Violates CD-04 and SECRETS-05. Always use WIF OIDC.
- **`ClusterIssuer` instead of `Issuer`:** D-13 locks namespace-scoped `Issuer`. Consistent with `SecretStore` pattern.
- **Skipping Let's Encrypt staging:** Production issuer rate limits (50 certs/domain/week) are hit quickly during testing. Always stage first.
- **Applying Ingress before placeholder TLS Secret:** Will cause `ingress-gce` to stall; cert-manager ACME challenge will never reach Let's Encrypt.
- **Using `autoscaling/v1` for HPA:** v1 only supports CPU; v2 is the stable API for all metric types.
- **Omitting `kubernetes.io/ingress.allow-http: "true"`:** GKE Ingress must allow HTTP for HTTP-01 ACME challenge on port 80.
- **Using `ingressClassName` field instead of `kubernetes.io/ingress.class` annotation for GKE:** The `ingressClassName` field is not reliably supported by `ingress-gce`; use annotation. [CITED: cert-manager.io GKE tutorial]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TLS certificate provisioning | Custom cert rotation scripts | cert-manager + Let's Encrypt | Auto-renewal, Kubernetes-native, battle-tested |
| GCP IAM authentication from CI | Static SA key JSON in GitHub secrets | `google-github-actions/auth@v3` + WIF | Keys expire, leak, require rotation; OIDC is keyless |
| Docker image push to Artifact Registry | Raw `docker push` + `gcloud auth` scripting | `google-github-actions/auth@v3` sets ADC; `gcloud auth configure-docker` for registry | One `docker push` command once ADC is configured |
| CPU-based pod scaling | Custom controller or fixed replicas | `autoscaling/v2.HorizontalPodAutoscaler` | Kubernetes-native, battle-tested, GKE Autopilot compatible |
| GitHub environment approval gates | Custom approval Slack bots | GitHub Environments with required reviewers | Native GitHub feature, zero infrastructure |

**Key insight:** The CD pipeline's complexity lies in IAM plumbing (WIF), not in the build/deploy logic itself. Get the IAM chain right (WIF pool → provider → attribute condition → SA binding → Pulumi state access) and everything else is straightforward.

---

## Common Pitfalls

### Pitfall 1: GKE Ingress + cert-manager Chicken-and-Egg
**What goes wrong:** Apply Ingress with TLS spec → `ingress-gce` looks for TLS Secret → Secret doesn't exist yet → GCE forwarding rules never created → ACME challenge path unreachable → cert-manager never gets certificate issued → perpetual `NotReady` state.
**Why it happens:** `ingress-gce` requires the referenced TLS Secret to exist before it finalizes the load balancer configuration. cert-manager only creates the Secret after ACME challenge succeeds. Both are waiting on the other.
**How to avoid:** Create an empty placeholder `kubernetes.io/tls` Secret with `string_data={"tls.crt": "", "tls.key": ""}` in Pulumi before applying the Ingress. Make the Ingress `depends_on` this placeholder Secret.
**Warning signs:** `kubectl describe ingress vici-ingress` shows `sync error: error running load balancer syncer`, `certificate` resource stays in `Pending`, GKE Load Balancer shows no backend services. [CITED: cert-manager.io GKE tutorial]

### Pitfall 2: WIF Pool Propagation Delay
**What goes wrong:** `pulumi up` creates WIF pool and provider, then immediately tries to use them in a CI run → "Identity Pool does not exist" or "workload identity pool provider not found".
**Why it happens:** GCP IAM propagation takes 60-120 seconds. New WIF pools are not immediately globally consistent.
**How to avoid:** Add WIF pool/provider creation to `cd.py` as a separate `pulumi up` pass (or pre-provision it manually) before enabling CI workflows. Do not assume first CI run will succeed immediately after infrastructure deploy. [CITED: google-github-actions/auth README]

### Pitfall 3: GKE Autopilot Resource Requests — Minimum Enforcement
**What goes wrong:** Deployment pod stays `Pending` indefinitely. No error on the Deployment itself.
**Why it happens:** GKE Autopilot enforces minimum resource requests (250m CPU / 512Mi memory per container on non-bursting clusters). Pods requesting less are mutated up; pods with no requests at all may be rejected.
**How to avoid:** Always set explicit `resources.requests` and `resources.limits` on every container. Recommended minimum: `cpu: "250m", memory: "512Mi"` requests; `cpu: "500m", memory: "1Gi"` limits. Apply to both the app container AND the Cloud SQL Auth Proxy init container. [CITED: cloud.google.com/kubernetes-engine/docs/concepts/autopilot-resource-requests]

### Pitfall 4: `ci.yml` Triggers on `main` — Double Deploy
**What goes wrong:** Both `ci.yml` and `cd-dev.yml` trigger on push to `main`. CI runs fine but creates confusion; more importantly, if CI fails, the CD job has already fired.
**Why it happens:** `ci.yml` currently has `on: push: branches: [main]`. With `cd-dev.yml` also on `main` push, both fire in parallel.
**How to avoid:** This is acceptable by design — CI and CD are intentionally parallel (CD-05 keeps CI unchanged). But verify both use the same `ubuntu-latest` runner and that CI failure does NOT cancel the CD run (they are independent jobs). Monitor for race conditions where Pulumi sees a new image tag before tests pass. If desired, add a `needs: [test]` dependency in `cd-dev.yml` referencing the CI job — but this requires the CI and CD to be in the same workflow file, which contradicts D-05. [ASSUMED]

### Pitfall 5: `envFrom` Secret Names Must Match ExternalSecret Target Names
**What goes wrong:** Deployment starts but FastAPI crashes on startup with `KeyError` or missing env var.
**Why it happens:** `envFrom.secretRef.name` must exactly match the `spec.target.name` in the `ExternalSecret`. From `secrets.py`, the target name IS the slug (e.g., `database-url`, `temporal-host`). The env var key injected is the `secretKey` field (e.g., `DATABASE_URL`, `TEMPORAL_HOST`).
**How to avoid:** Copy `envFrom` names directly from `secrets.py` `_SECRET_DEFINITIONS` list. All 11 vici-namespace secrets are: `twilio-auth-token`, `twilio-account-sid`, `twilio-from-number`, `openai-api-key`, `pinecone-api-key`, `pinecone-index-host`, `braintrust-api-key`, `database-url`, `temporal-host`, `otel-exporter-otlp-endpoint`, `webhook-base-url`. [VERIFIED: codebase grep — secrets.py `_SECRET_DEFINITIONS`]

### Pitfall 6: `app_hostname` with Auto-Assigned IP — ACME Challenge DNS
**What goes wrong:** Using a raw IP address as the Ingress hostname for TLS. Let's Encrypt does NOT issue certificates for IP addresses — only domain names.
**Why it happens:** D-01 says "use GKE auto-assigned IPs for v1" which creates ambiguity about how TLS works without a real domain.
**How to avoid:** For v1 with auto-assigned IP only, TLS cannot use Let's Encrypt. Options: (a) Use a `nip.io` hostname (`<ip>.nip.io` — free wildcard DNS for IPs, Let's Encrypt will issue a cert) or (b) skip TLS for dev and use Let's Encrypt staging cert only on staging/prod with real domains stubbed in. D-02 stubs `getvici.ai` subdomains in config — if DNS for `dev.getvici.ai` is pointed at the GKE IP, Let's Encrypt will work immediately. **The planner must clarify this with the user before implementing ingress.py** — the `app_hostname` value in each stack config determines whether TLS is possible. [ASSUMED — needs user confirmation]

---

## Code Examples

### Complete `envFrom` block for all 11 secrets

```python
# Source: infra/components/secrets.py _SECRET_DEFINITIONS
# [VERIFIED: codebase grep]

_ENV_FROM_SOURCES = [
    "twilio-auth-token",
    "twilio-account-sid",
    "twilio-from-number",
    "openai-api-key",
    "pinecone-api-key",
    "pinecone-index-host",
    "braintrust-api-key",
    "database-url",
    "temporal-host",
    "otel-exporter-otlp-endpoint",
    "webhook-base-url",
]

env_from = [
    k8s.core.v1.EnvFromSourceArgs(
        secret_ref=k8s.core.v1.SecretEnvSourceArgs(name=slug)
    )
    for slug in _ENV_FROM_SOURCES
]
```

### cert-manager Helm Release in Pulumi

```python
# Source: https://cert-manager.io/docs/installation/helm/
# [CITED: cert-manager.io official docs]

_CERTMANAGER_CHART_VERSION = "v1.20.0"
_CERTMANAGER_REPO = "https://charts.jetstack.io"

certmanager_release = k8s.helm.v3.Release(
    "cert-manager",
    k8s.helm.v3.ReleaseArgs(
        chart="cert-manager",
        version=_CERTMANAGER_CHART_VERSION,
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(repo=_CERTMANAGER_REPO),
        namespace="cert-manager",
        create_namespace=False,
        values={
            "crds": {"enabled": True},  # Install CRDs as part of chart
        },
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[namespaces["cert-manager"]],
    ),
)
```

### `__main__.py` additions

```python
# Add after existing imports in infra/__main__.py:
from components.certmanager import certmanager_release          # noqa: F401
from components.app import app_deployment, app_service, app_hpa  # noqa: F401
from components.ingress import vici_ingress                     # noqa: F401
from components.cd import wif_pool, wif_provider                # noqa: F401
```

### Pulumi stack config additions

```yaml
# Add to Pulumi.dev.yaml, Pulumi.staging.yaml, Pulumi.prod.yaml:
config:
  vici-infra:app_hostname: dev.getvici.ai      # Or <ip>.nip.io for v1
  vici-infra:github_org: your-org-name
  vici-infra:wif_pool_id: github-actions-dev  # Matches cd.py constant
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `autoscaling/v1` HPA (CPU only) | `autoscaling/v2` HPA (multi-metric) | K8s 1.23 (v2 GA) | Use `k8s.autoscaling.v2` in Pulumi; v1 is deprecated |
| Static GCP SA key JSON in CI | WIF OIDC + `google-github-actions/auth` | ~2021 (Google recommendation) | No secrets to rotate; short-lived tokens |
| cert-manager `ClusterIssuer` | `Issuer` per namespace (where needed) | Best practice; no version boundary | Stricter RBAC; matches project SecretStore pattern |
| `kubernetes.io/ingress.class` annotation (deprecated in upstream K8s) | `ingressClassName` field | K8s 1.18+ | GKE `ingress-gce` still uses annotation reliably; do NOT switch to `ingressClassName` until GKE docs confirm support |

**Deprecated/outdated:**
- `autoscaling/v1` HPA: Use `autoscaling/v2` — v1 is deprecated in K8s 1.25+
- `GOOGLE_CREDENTIALS` env var in GitHub Actions: Use WIF instead per CD-04
- cert-manager v1.12 and earlier: Issuer `spec.acme.profile` field is new in 1.17+ — don't add it for compatibility unless needed

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Double-firing of `ci.yml` and `cd-dev.yml` on push to `main` is acceptable with no race condition risk | Pitfall 4 | If race condition exists, build deploys untested code; mitigate by adding `needs` dependency |
| A2 | `nip.io` is a viable v1 hostname for Let's Encrypt TLS with auto-assigned GKE IP | Pitfall 6 | If nip.io rate-limits or is blocked by Let's Encrypt, TLS won't work with auto-assigned IPs until real DNS is configured |
| A3 | `vici-ci-push` SA (from `identity.py`) is the correct SA to bind to WIF for CI pushes and Pulumi deploys | Architecture Patterns (cd.py) | If a separate deploy SA is needed vs push SA, `cd.py` must create a second SA with Pulumi state bucket access |
| A4 | GKE Autopilot on the dev cluster currently supports bursting (250m CPU minimum per container) | Common Pitfalls (Pitfall 3) | If non-bursting, minimum is still 250m CPU / 512Mi memory — same recommendation applies |

---

## Open Questions

1. **`app_hostname` value for v1 TLS**
   - What we know: D-01 uses auto-assigned IPs; D-02 stubs `getvici.ai` in config; Let's Encrypt requires a domain name
   - What's unclear: Will DNS for `dev.getvici.ai` be pointed at the GKE IP immediately, or will `nip.io` be used as an interim?
   - Recommendation: Planner should default to `<ip>.nip.io` pattern for dev/staging in v1, with `getvici.ai` subdomains in config as commented-out values. Operator replaces with real IP after first `pulumi up` and re-runs. Alternatively, planner can ask user before generating tasks.

2. **`vici-ci-push` SA scope for Pulumi**
   - What we know: `vici-ci-push` SA has Artifact Registry write access (from `registry.py`). CD-01 requires `pulumi up --stack dev`
   - What's unclear: Does this SA also need `roles/storage.objectAdmin` on the GCS Pulumi state bucket, and `roles/container.developer` on the GKE cluster for kubectl access?
   - Recommendation: `cd.py` should grant `ci_push_sa` the following additional roles: `roles/storage.objectAdmin` (state bucket), `roles/container.developer` (cluster access for Pulumi K8s provider). Add these as explicit `IAMMember` resources in `cd.py`.

3. **GitHub environment name for approval gate**
   - What we know: D-10 requires GitHub environment approval gate for prod
   - What's unclear: Does the GitHub repository have an environment named `prod` with required reviewers already configured, or must the planner include instructions to set it up?
   - Recommendation: Include a Wave 0 manual step: create GitHub environment `prod` with required reviewer. This cannot be automated via Pulumi (GitHub env settings are repository settings, not IaC).

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Pulumi CLI | `pulumi up` / `pulumi preview` | Yes | v3.229.0 | — |
| kubectl | K8s resource inspection | Yes | v1.25.9 | — |
| gcloud CLI | Artifact Registry auth, GKE access | Yes | SDK 563.0.0 (2026-03-27) | — |
| Docker | Local image builds | Not verified | — | Build in CI only |
| cert-manager CRDs | Issuer + Certificate resources | Not yet (Phase 5 installs them) | — | Installed via `certmanager.py` Helm release |

**Missing dependencies with no fallback:** None that block planning.

**Notes:**
- cert-manager CRDs do not exist on the cluster yet — `ingress.py` must `depends_on=[certmanager_release]` to avoid CRD not found errors during `pulumi up`
- Docker local build is CI-only for this phase; no local build required for plan execution

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pyproject.toml` or `pytest.ini` (existing) |
| Quick run command | `uv run pytest tests/ -x --tb=short -q` |
| Full suite command | `uv run pytest tests/ --tb=short -q` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | Notes |
|--------|----------|-----------|-------------------|-------|
| APP-01 | Deployment accepts all 11 envFrom secrets | smoke | `kubectl get deployment vici-app -n vici` | Post-deploy cluster check |
| APP-02 | Temporal worker appears in Temporal UI after pod start | manual | `kubectl logs -n vici deploy/vici-app -c vici-app \| grep temporal` | Log grep is automated; UI check is manual |
| APP-03 | HPA exists and targets vici-app Deployment | smoke | `kubectl get hpa vici-app -n vici` | Post-deploy cluster check |
| APP-04 | GKE Ingress has external IP and TLS cert is Ready | smoke | `kubectl describe certificate vici-tls -n vici` | Post-deploy; cert may take minutes |
| APP-05 | `GET /health` returns HTTP 200 from public hostname | integration | `curl -s -o /dev/null -w "%{http_code}" https://<hostname>/health` | Manual after cert provisioned |
| APP-06 | `WEBHOOK_BASE_URL` env var = Ingress hostname | manual | Verify in GCP Secret Manager console | Config verification |
| CD-01 | Push to main triggers build+push+deploy to dev | integration | Push a trivial commit; check GitHub Actions run | Manual trigger test |
| CD-02 | PR triggers preview; dispatch triggers staging up | integration | Open a PR; check `pulumi preview` output | Manual trigger test |
| CD-03 | Prod deploy requires approval | integration | Trigger `cd-prod.yml`; verify approval request sent | Manual |
| CD-04 | No static GCP keys in GitHub secrets | manual | Inspect GitHub Actions secrets; verify WIF only | Audit |
| CD-05 | CI test job unchanged | unit | `uv run pytest tests/ -x --tb=short -q` | Existing test suite |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/ -x --tb=short -q` (existing CI suite — CD-05)
- **Per wave merge:** Full pytest + cluster health checks
- **Phase gate:** `GET /health` returns 200 from public GKE Ingress hostname with valid TLS

### Wave 0 Gaps
- No new test files required — Phase 5 is infrastructure and CI/CD only; application code is unchanged
- Manual cluster validation steps (APP-01 through APP-05) documented above cannot be automated before the cluster exists

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No — no user-facing auth added | — |
| V3 Session Management | No | — |
| V4 Access Control | Yes — CI pipeline access to GCP | WIF OIDC; no static keys (CD-04, SECRETS-05) |
| V5 Input Validation | No — no new API endpoints | — |
| V6 Cryptography | Yes — TLS certificates | cert-manager + Let's Encrypt (auto-renewal) |

### Known Threat Patterns for GKE + GitHub Actions CI/CD

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Static GCP SA key in GitHub secrets leaks via log or fork | Information Disclosure | WIF OIDC (no long-lived credentials) — CD-04 |
| Over-privileged CI SA deploys any project resource | Elevation of Privilege | Scope WIF attribute condition to specific repo; SA has minimum roles only (SECRETS-05) |
| Unauthenticated push to Artifact Registry | Tampering | Artifact Registry requires IAM; `roles/artifactregistry.writer` only for CI SA |
| Prod deployment without approval | Elevation of Privilege | GitHub Environment required reviewers (D-10, CD-03) |
| Internal UIs exposed without auth | Information Disclosure | D-03/D-04 locks internal UIs to ClusterIP only in Phase 5 |

---

## Sources

### Primary (HIGH confidence)
- [cert-manager GKE + Let's Encrypt tutorial](https://cert-manager.io/docs/tutorials/getting-started-with-cert-manager-on-google-kubernetes-engine-using-lets-encrypt-for-ingress-ssl/) — Issuer spec, Ingress annotations, chicken-and-egg workaround
- [cert-manager releases](https://github.com/cert-manager/cert-manager/releases) — v1.20.0 latest stable confirmed
- [Pulumi HPA v2 API docs](https://www.pulumi.com/registry/packages/kubernetes/api-docs/autoscaling/v2/horizontalpodautoscaler/) — HPA Python example
- [google-github-actions/auth README](https://github.com/google-github-actions/auth) — WIF workflow YAML, required permissions, attribute conditions
- [GKE Autopilot resource requests](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/autopilot-resource-requests) — Minimum CPU/memory per container
- [GitHub reusable workflows docs](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows) — `workflow_call` inputs/secrets pattern
- `infra/components/migration.py` — Auth Proxy native sidecar pattern (verbatim reuse confirmed)
- `infra/components/secrets.py` — All 11 ExternalSecret definitions confirmed
- `infra/components/prometheus.py` — `fastapi_service_monitor` selector labels confirmed (`app: vici`)
- `src/main.py` — `/health`, `/readyz` endpoints confirmed; Temporal worker lifespan pattern confirmed

### Secondary (MEDIUM confidence)
- [GCP IAM WIF with deployment pipelines](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines) — WIF pool/provider setup
- [cert-manager GitHub issue #1343](https://github.com/cert-manager/cert-manager/issues/1343) — chicken-and-egg issue confirmed active in ingress-gce

### Tertiary (LOW confidence)
- `nip.io` as interim hostname for Let's Encrypt with auto-assigned IPs — based on common community practice, not officially documented by cert-manager or GKE

---

## Project Constraints (from CLAUDE.md)

All constraints from `AGENTS.md` (referenced by `CLAUDE.md`) apply to new Pulumi component files:

| Directive | Impact on Phase 5 |
|-----------|------------------|
| Domain-organized code structure | `app.py`, `ingress.py`, `cd.py`, `certmanager.py` are separate files per domain — compliant |
| SOLID principles, DRY | `envFrom` list built programmatically from `_ENV_FROM_SOURCES` constant; sidecar pattern reused from `migration.py` without duplication |
| No magic numbers — all constants at module top | All ports, versions, replica counts, CPU targets must be `_CONST_NAME` constants |
| 3NF database schema | No new schema in this phase |
| `ruff check --fix` / `ruff format` | Apply to all new `.py` files in `infra/` before commit |
| Prefer canonical domain language | "Issuer" not "issuer resource"; "HPA" not "autoscaler"; match K8s/GKE terminology throughout |

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — cert-manager v1.20.0 verified from releases page; Pulumi HPA API verified from registry; WIF pattern verified from official Google action
- Architecture: HIGH — patterns derived directly from existing codebase (`migration.py`, `secrets.py`) with minimal inference
- Pitfalls: HIGH — chicken-and-egg issue verified from cert-manager official docs and GitHub issues; Autopilot minimums from official GKE docs; WIF propagation delay from official google-github-actions README
- CD pipeline structure: HIGH — `workflow_call` pattern from official GitHub docs

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (cert-manager stable releases; WIF API stable)
