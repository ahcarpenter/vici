# Architecture Research — Milestone v1.1 (De-platform → Docker-Only Base)

**Domain:** SMS webhook + AI extraction + job matching API, re-baselined as a hosting-agnostic Docker-only deploy
**Researched:** 2026-05-01
**Confidence:** HIGH — derived from the actual built system (Phases 01–02.5 + gks-refactor Phases 1–5.1) plus current Temporal Cloud / Compose references via Context7 and the official Temporal docs and docker-compose repo

---

## 1. Target Architecture (post-v1.1)

```
┌──────────────────────────────────────────────────────────────────────┐
│                            EXTERNAL                                  │
│  ┌──────────────┐    ┌──────────────────┐    ┌─────────────────┐     │
│  │ Twilio SMS   │    │ OpenAI GPT API   │    │ Pinecone        │     │
│  └──────────────┘    └──────────────────┘    └─────────────────┘     │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ Temporal Cloud  ◄── gRPC + TLS + API key ───┐                │    │
│  │  vici.<account>.tmprl.cloud:7233            │                │    │
│  └──────────────────────────────────────────────┼───────────────┘    │
└──────────────────────────────────────────────────┼───────────────────┘
                                                   │
┌──────────────────────────────────────────────────┼───────────────────┐
│   docker-compose.prod.yml — single host / single network            │
│   ┌──────────┐  ┌────────────────────────────┐  │  ┌──────────────┐ │
│   │ postgres │  │ app (FastAPI + worker)     │──┘  │ jaeger       │ │
│   │   :5432  │◄─┤ uvicorn  +  Temporal Worker│────►│   (postgres │ │
│   └─────▲────┘  │ embedded in app process    │     │    storage)  │ │
│         │       └─────┬──────────────────────┘     └──────────────┘ │
│         │             │                                              │
│         │             ▼                                              │
│         │       ┌─────────────────┐    ┌────────────────┐            │
│         │       │ prometheus      │───►│ grafana        │            │
│         │       │  scrapes app    │    │  dashboards    │            │
│         │       │  :8000/metrics  │    │  :3000         │            │
│         │       └─────────────────┘    └────────────────┘            │
│         │                                                            │
│         └──── Temporal visibility queries: SAME postgres,            │
│               but visibility lives in Temporal Cloud, not here.      │
│                                                                      │
│   Removed from prod compose: opensearch, temporal, temporal-ui       │
└──────────────────────────────────────────────────────────────────────┘
```

### Key shifts (vs. current built state)

1. **Temporal moves out of compose into Temporal Cloud.** No `temporal` or `temporal-ui` service in `docker-compose.prod.yml`. Local dev keeps an in-compose Temporal for offline iteration.
2. **OpenSearch deleted entirely from production.** Visibility for app workflows is owned by Temporal Cloud (managed service). Jaeger trace storage migrates to a backend that does not require OpenSearch — the canonical compose-friendly choice is Jaeger v2's built-in **PostgreSQL** trace store (or a dedicated trace `postgres` container; details in §6).
3. **The app process embeds the worker.** `src/main.py` already starts `run_worker(...)` as a `lifespan` task; that does not change. The only change is what `Client.connect(...)` points at and how it authenticates.
4. **All deploy IaC (`infra/`) is deleted** along with the GitHub Actions CD pipeline (`cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`). The repo retains a generic Dockerfile and a compose file as the deployment unit. `render.yaml` is already gone.

---

## 2. Compose Topology — base + override pattern

**Decision: three-file overlay model.**

| File | Loaded when | Purpose |
|------|-------------|---------|
| `docker-compose.yml` | Always (base) | Service definitions valid for any environment: `postgres`, `app`, `jaeger`, `prometheus`, `grafana`. Image references, networks, healthchecks, volume names. **No host port publishes that differ between dev and prod, no `build:` directive, no `command: --reload`.** |
| `docker-compose.override.yml` | Auto-loaded in dev (`docker compose up`) | Dev-only services (`temporal`, `temporal-ui`), `build: .` on the app service, `--reload` flag, `volumes: ./src:/app/src` bind mount, exposed host ports. Git-tracked (the project standardizes the dev experience). |
| `docker-compose.prod.yml` | Explicit: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` | Production overrides: `image: ghcr.io/...:${GIT_SHA}` (or `build: .` — see §5), `restart: unless-stopped`, environment pointing at Temporal Cloud, no source bind mounts, narrowed published ports (only `app:8000`), resource limits. |

**Rationale (HIGH confidence, sourced from official Docker docs and current 2026 community guidance):**
- This is the canonical pattern documented at [docs.docker.com/compose/how-tos/multiple-compose-files/merge](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/): the override file is auto-loaded in dev; prod requires explicit `-f` flags.
- Single base + two overlays beats three independent files because environment drift is contained in the diff. The 2026 community guidance specifically warns against "maintaining separate docker-compose files for each environment ... they start identical but gradually drift apart."
- Compose merge semantics: scalar values are replaced, lists (ports, volumes) are appended, maps (environment, labels) are merged by key. This means the prod overlay can *add* env vars and *replace* the image tag without restating service-level basics.

**Anti-pattern explicitly rejected:** a single `docker-compose.yml` with `profiles:` for dev/prod. Profiles are good for optional services within one environment, not for a hard dev/prod split where you want the prod artifact to be small and audited.

### Concrete file split

**`docker-compose.yml` (base — committed)**
- `postgres` (16, healthcheck, named volume)
- `app` (no `build:`, no `command:` override, healthcheck, depends on postgres)
- `jaeger` (single Jaeger v2 binary, postgres backend — see §6)
- `prometheus` (volumes: `./prometheus/prometheus.yml`)
- `grafana` (volumes: `./grafana/provisioning`, named volume `grafana_data`)

**`docker-compose.override.yml` (dev — committed)**
- Adds `temporal` + `temporal-ui` (auto-setup with Postgres backend, no Elasticsearch — set `ENABLE_ES=false`)
- `app`: `build: .`, `command: uv run uvicorn ... --reload`, `volumes: ./src:/app/src`, host port `8000:8000`
- All host port publishes for direct browser access (`5432:5432`, `7233:7233`, `8080:8080` UI, `9090:9090`, `3000:3000`, `16686:16686`)

**`docker-compose.prod.yml` (prod — committed)**
- `app`: `image: ghcr.io/<org>/vici:${GIT_SHA}` (or `build: .` — see §5), `restart: unless-stopped`, env file `.env.prod`, only `8000:8000` published (or behind a reverse proxy)
- `postgres`: `restart: unless-stopped`, named-volume only, no host port publish (only the app needs it on the compose network)
- Observability services: `restart: unless-stopped`, no host port publish for prometheus/grafana unless an admin reverse proxy is in front
- `temporal` and `temporal-ui` services explicitly **not present** — production points at Temporal Cloud

---

## 3. Temporal Cloud Integration — exact code paths

### File: `src/config.py` — MODIFIED

Replace single flat `temporal_address` with a `TemporalSettings` sub-model that captures the Cloud auth surface. Keep flat env vars for back-compat with existing tests / dev compose where the value is just `temporal:7233`.

```python
class TemporalSettings(BaseModel):
    address: str = ""               # "vici.<account>.tmprl.cloud:7233" in prod, "temporal:7233" in dev
    namespace: str = "default"      # "vici.<account>" in prod, "default" in dev
    api_key: str = ""               # populated only in prod; empty in dev
    tls: bool = False               # True in prod, False in dev
    task_queue: str = "vici-queue"
    cron_schedule_pinecone_sync: str = "*/5 * * * *"
```

Add three new flat env vars on the top-level `Settings`:
- `temporal_namespace: str = "default"` (line ~46 area)
- `temporal_api_key: str = ""` (line ~46 area, marked sensitive — never logged)
- `temporal_tls: bool = False` (line ~46 area)

Update `_build_sub_models` (line ~138) to wire them into `self.temporal`.

Update `_validate_required_credentials` (line ~91): require `temporal_api_key` and `temporal_namespace` only when `env in ("staging", "production")`. Dev / local compose with the in-cluster temporal must continue to work without those values.

### File: `src/temporal/worker.py` — MODIFIED

The current `get_temporal_client(address: str)` (line 17) takes only an address. Change the signature to accept a `TemporalSettings` and conditionally pass `api_key=`, `tls=`, and `namespace=`:

```python
async def get_temporal_client(temporal: TemporalSettings) -> Client:
    connect_kwargs: dict[str, Any] = {
        "interceptors": [TracingInterceptor(always_create_workflow_spans=True)],
    }
    if temporal.namespace:
        connect_kwargs["namespace"] = temporal.namespace
    if temporal.api_key:
        connect_kwargs["api_key"] = temporal.api_key
    if temporal.tls:
        connect_kwargs["tls"] = True
    return await Client.connect(temporal.address, **connect_kwargs)
```

This matches the canonical Temporal Cloud connection pattern (verified via Context7 `/temporalio/sdk-python`):
```python
await Client.connect(
    "my-namespace.abc123.tmprl.cloud:7233",
    namespace="my-namespace.abc123",
    api_key="your-api-key",
    tls=True,
)
```

API key is preferred over mTLS per official Temporal Cloud guidance ("we recommend using API keys because they're easier to manage and rotate"). mTLS only matters if the org already has PKI — Vici doesn't, so **default to API key**.

### File: `src/main.py` — MODIFIED (line 188)

Change:
```python
temporal_client = await get_temporal_client(settings.temporal_address)
```
to:
```python
temporal_client = await get_temporal_client(settings.temporal)
```

### File: `Dockerfile` — UNCHANGED

API key auth means **no cert files in the image**. The runtime stage stays exactly as it is. This is one of the meaningful wins of API-key over mTLS: no cert volume mount, no PEM-as-env decoding, no Dockerfile changes.

(If the project ever switches to mTLS for compliance reasons, the cert PEM bytes would be passed via env vars decoded with `base64`, never baked into the image. But that's out of scope for v1.1.)

### Files: `.env.app.example`, `.env.app` — MODIFIED

Add three keys:
```
TEMPORAL_ADDRESS=temporal:7233           # prod: vici.<account>.tmprl.cloud:7233
TEMPORAL_NAMESPACE=default               # prod: vici.<account>
TEMPORAL_API_KEY=                        # prod only — populate from Temporal Cloud UI
TEMPORAL_TLS=false                       # prod: true
```

### File: `docker-compose.override.yml` (dev) — `temporal:` service KEPT, env wires to dev defaults

Dev compose keeps the local `temporalio/auto-setup:1.26.2` container with `ENABLE_ES=false`, `DB=postgres12`, `POSTGRES_SEEDS=postgres` so the **same Postgres** that holds app data also holds Temporal's history + visibility. This eliminates OpenSearch from local dev too.

### File: `docker-compose.prod.yml` — no `temporal:` service

`app` reads `TEMPORAL_ADDRESS=vici.<account>.tmprl.cloud:7233`, `TEMPORAL_TLS=true`, `TEMPORAL_API_KEY=...` from `.env.prod`. The compose file itself contains no Temporal service.

---

## 4. OpenSearch Removal — cascade

OpenSearch is **only used by Jaeger** for trace storage and **by Temporal** as its visibility store (advanced visibility). Vici application code does not import or query OpenSearch directly — confirmed by `grep -r "opensearch\|OpenSearch" src/` returning zero hits.

### Cascade of deletions

| Touchpoint | Change |
|------------|--------|
| `docker-compose.yml` (current) lines 13–22 | DELETE `opensearch:` service block |
| `jaeger/collector-config.yaml` | REPLACE entire `extensions.jaeger_storage.backends.main_storage.opensearch` block with `postgresql` (or `memory` for dev — see §6) |
| `jaeger/query-config.yaml` | Same replacement as collector |
| `infra/components/opensearch.py` | DELETE file |
| `infra/components/temporal.py` lines 10, 32, 33, 195–200, 282 | DELETE (entire file deleted with `infra/`) |
| `infra/__main__.py` lines 22–34 (selected) | DELETE (entire file deleted with `infra/`) |
| `.env.opensearch`, `.env.opensearch.example` | DELETE |
| `src/` | NO CHANGES — application code never touched OpenSearch |
| Temporal visibility | Switches from in-cluster ES7 (via OpenSearch compat API) → Temporal Cloud (managed) in prod, and to **Postgres advanced visibility** in dev compose |

### Postgres-as-Temporal-visibility (dev compose only)

For local dev where the app uses `temporalio/auto-setup`, set:
- `DB=postgres12` (already set)
- `ENABLE_ES=false` (NEW — currently presumably `true` in `.env.temporal`)
- `POSTGRES_SEEDS=postgres` (already set)
- `VISIBILITY_DBNAME=temporal_visibility` (auto-setup default)

Postgres 12+ supports Temporal advanced visibility (custom search attributes, modern filtering) since Temporal Server v1.20. Standard visibility was removed in v1.24, so this is the only supported path for v1.26 (the version pinned in compose). Sources: [Self-hosted Visibility setup](https://docs.temporal.io/self-hosted-guide/visibility), [auto-setup Docker image](https://hub.docker.com/r/temporalio/auto-setup).

---

## 5. Image Build Strategy — `build: .` vs registry pull

**Decision: prod compose `image: ghcr.io/<org>/vici:${GIT_SHA}` with `build: .` as the documented dev fallback.**

**Trade-offs analyzed:**

| Approach | Build time on deploy | Reproducibility | Multi-host scalability | Storage cost | Auditability |
|----------|---------------------|------------------|------------------------|--------------|--------------|
| `build: .` (prod) | Slow (full rebuild on each `compose up`) | Fragile — host's git checkout, host's Docker version | None — image isn't shared | Zero (no registry) | Poor — no immutable artifact |
| Registry pull (prod) | Fast (cached layer pull) | Strong — SHA-pinned digest | Trivial — same image on N hosts | Modest (GHCR is free for public, ~$0/mo private) | Strong — the SHA in compose === the SHA tested in CI |

For a "deploy anywhere" baseline, **registry pull** is correct because it preserves the milestone goal (provider-neutral) without re-introducing a build step into the deploy host. GHCR is the lowest-friction registry for a GitHub-hosted project. The image tag should be the 7-char git SHA (matches the existing CD workflow's `steps.sha.outputs.sha` pattern).

**However:** `build: .` should remain as a one-line override in `docker-compose.override.yml` for dev. New contributors should not need a registry login to run the app locally. The `build:` directive in the dev override and the `image:` directive in the prod override can coexist because `image:` in `docker-compose.yml` (the base) is what dev would use as a fallback if `build:` is absent — but Compose v2 prefers `build:` when both are set.

**CI plumbing required:**
- A new minimal `.github/workflows/release.yml` that on tag push runs `docker buildx build --push -t ghcr.io/<org>/vici:${SHA}` and `:latest`.
- The existing `cd-*.yml` workflows are deleted entirely (they orchestrate Pulumi and `gke-gcloud-auth-plugin`, neither of which exists post-milestone).

If the project decides "no registry, period" (truly the most provider-neutral baseline), the prod compose ships with `build: .` and the deploy story becomes "git pull && docker compose -f ... up -d --build". This is acceptable but slower; it is **not** the recommended path because it makes rollback expensive (you have to git revert + rebuild rather than redeploy a known-good tag).

---

## 6. Observability in Prod Compose

### Service-to-service networking

Compose creates a default user-defined bridge network where services resolve each other by service name. This is already how the dev compose works:
- `app` exports OTLP at `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317` (currently `jaeger-collector:4317` — collapsing to a single `jaeger` service per §6.2)
- `prometheus` scrapes `http://app:8000/metrics` per `prometheus/prometheus.yml`
- `grafana` queries `http://prometheus:9090` via its provisioning datasource

**No change needed to the app code.** The OTel endpoint is already env-driven (`src/main.py:87` reads `settings.observability.otel_endpoint`).

### Jaeger v2 single-binary collapse

Current dev compose runs `jaeger-collector` and `jaeger-query` as two services — a holdover from the v1 split-binary model. Jaeger v2 (the existing `jaegertracing/jaeger:2.16.0` image) supports running both via a single config file with both `jaeger_storage` and `jaeger_query` extensions enabled. **For prod compose**, collapse to a single `jaeger` service with one config that exposes:
- `:4317` (OTLP gRPC ingest)
- `:4318` (OTLP HTTP ingest, optional)
- `:16686` (UI)

Storage backend choices (HIGH confidence Jaeger v2 supports all three):
1. **Memory** — fine for hobby / staging; trace data lost on restart
2. **PostgreSQL** — trace data lives alongside app data; one less moving part. Recommended for the `docker-compose.prod.yml` baseline.
3. **Cassandra / Elasticsearch / OpenSearch** — heavyweight, defeats the milestone goal

**Recommendation: Postgres for traces.** Use the same `postgres` service (separate database `jaeger_traces`) or a separate `jaeger-postgres` service if the operator wants to age traces independently. Update `jaeger/collector-config.yaml` and `jaeger/query-config.yaml` (or merge them into one `jaeger/config.yaml` for the v2 single-binary mode) to use the `postgresql` storage backend with connection details pulled from env.

### Volume mounts

| Service | Mount | Purpose |
|---------|-------|---------|
| `prometheus` | `./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro` | Scrape config (already in dev) |
| `prometheus` | `prometheus_data:/prometheus` (NEW named volume) | Persist time-series across restarts |
| `grafana` | `./grafana/provisioning:/etc/grafana/provisioning:ro` | Dashboards + datasource (already in dev) |
| `grafana` | `grafana_data:/var/lib/grafana` | Already in dev, keep |
| `jaeger` | `./jaeger/config.yaml:/etc/jaeger/config.yaml:ro` | Single config for v2 |
| `postgres` | `postgres_data:/var/lib/postgresql/data` | NEW named volume — currently absent! Dev compose has no persistence. |

**Anti-pattern in current compose (must fix in v1.1):** `docker-compose.yml` line 1–11 defines `postgres` with no volume. A `docker compose down` wipes data. Production absolutely needs a named volume.

### Healthchecks

Already wired in dev compose for postgres, opensearch, jaeger-collector, temporal, prometheus, grafana. Carry over verbatim with these tweaks:
- `app` healthcheck: keep the existing Dockerfile `HEALTHCHECK` (curl `:8000/health`)
- `jaeger` (collapsed): `wget -qO- http://localhost:13133/status` (existing `healthcheckv2` extension URL)
- Drop `temporal` healthcheck from prod (not present); keep in dev

### `depends_on` with `condition: service_healthy`

The dev compose already uses `depends_on: { postgres: { condition: service_healthy } }` for the app service. Prod compose retains this pattern — the app should not start until postgres is healthy. With Temporal removed from compose, the `temporal: condition: service_healthy` line on `app` is deleted (the worker will retry the Cloud connection on its own).

---

## 7. Build Order — Phased Roadmap with Dependency Graph

```
                ┌────────────────────────────────────────────────────┐
                │  Phase 1: Temporal Cloud client (in-app)           │
                │  • config.py: TemporalSettings (api_key, tls,      │
                │    namespace)                                       │
                │  • worker.py: get_temporal_client(temporal_settings)│
                │  • main.py: pass settings.temporal                  │
                │  • .env.app.example: 3 new keys                     │
                │  Blocks: nothing.                                    │
                │  Validates: dev still works against in-compose      │
                │    temporal:7233; prod can target Cloud.            │
                └─────────────────────┬──────────────────────────────┘
                                      │
                ┌─────────────────────▼──────────────────────────────┐
                │  Phase 2: docker-compose.prod.yml + base/override  │
                │    split                                            │
                │  • Split current docker-compose.yml into base +     │
                │    override (no behavior change for dev)            │
                │  • Author docker-compose.prod.yml: postgres, app,   │
                │    jaeger, prometheus, grafana (no temporal)        │
                │  • Add postgres named volume to base                │
                │  • Document `compose -f docker-compose.yml -f       │
                │    docker-compose.prod.yml up -d` command           │
                │  Blocks: Phase 4 (Cloud cutover needs prod compose) │
                │  Depends on: Phase 1 only conceptually — the prod   │
                │    compose CAN ship before Cloud is wired, with     │
                │    `TEMPORAL_ADDRESS` pointed at a placeholder.     │
                └─────────────────────┬──────────────────────────────┘
                                      │
                ┌─────────────────────▼──────────────────────────────┐
                │  Phase 3: Drop OpenSearch (dev + prod)             │
                │  • dev compose: ENABLE_ES=false on temporal,       │
                │    DB=postgres12 already set, drop opensearch       │
                │    service, drop .env.opensearch                    │
                │  • Jaeger: collapse 2 services → 1; switch storage  │
                │    backend to memory (dev) / postgres (prod)        │
                │  • Update jaeger/*.yaml configs                     │
                │  Depends on: Phase 2 (compose split must exist)     │
                │  Validates: full local stack runs without           │
                │    opensearch; traces still visible at :16686       │
                └─────────────────────┬──────────────────────────────┘
                                      │
                ┌─────────────────────▼──────────────────────────────┐
                │  Phase 4: Temporal Cloud cutover (prod only)       │
                │  • Provision Temporal Cloud namespace + API key    │
                │  • Populate TEMPORAL_API_KEY, _NAMESPACE, _TLS=true │
                │    in production secrets                            │
                │  • Verify worker connects + cron registers          │
                │    (start_cron_if_needed handles ALREADY_EXISTS)    │
                │  Depends on: Phase 1 (client code) + Phase 2 (prod  │
                │    compose) + Phase 3 (no OpenSearch leftover)      │
                │  Critical: do NOT delete in-cluster Temporal until  │
                │    Cloud has run a real workflow successfully.      │
                └─────────────────────┬──────────────────────────────┘
                                      │
                ┌─────────────────────▼──────────────────────────────┐
                │  Phase 5: Image build / publish pipeline           │
                │  • New release.yml: buildx push to ghcr.io          │
                │  • prod compose `image: ghcr.io/.../vici:${GIT_SHA}`│
                │  Depends on: Phase 2 (prod compose exists)          │
                │  Independent of Phase 4 (image works against either │
                │    Cloud or in-cluster temporal).                   │
                └─────────────────────┬──────────────────────────────┘
                                      │
                ┌─────────────────────▼──────────────────────────────┐
                │  Phase 6: Demolish GCP/K8s/Pulumi/Render artifacts │
                │  • DELETE infra/ (Pulumi project + components)      │
                │  • DELETE .github/workflows/cd-base.yml,            │
                │    cd-dev.yml, cd-staging.yml, cd-prod.yml          │
                │  • DELETE ci.yml ruff target on infra/ (`uv run     │
                │    ruff check src/ tests/ infra/` → drop infra/)    │
                │  • DELETE infra-related root files (Pulumi.*.yaml,  │
                │    DOMAIN-SETUP.md, OPERATIONS.md)                  │
                │  • UPDATE README, AGENTS.md, CONTRIBUTING.md to     │
                │    reflect compose-only deploy story                │
                │  Depends on: Phase 4 (Cloud cutover MUST be live    │
                │    before tearing out the in-cluster fallback) +    │
                │    Phase 5 (image publish must work)                │
                │  This is the point of no return — once infra/ is    │
                │    gone, rolling back to GKE means restoring it     │
                │    from git history.                                │
                └────────────────────────────────────────────────────┘
```

### Why this order

- **Phase 1 first** because the client code change is small, reversible, and lets you point at Cloud in a feature branch without disturbing prod. It can be merged behind a feature flag (the `temporal_api_key` env var being empty is itself the flag).
- **Phase 2 before Phase 4** because writing a prod compose file is a green-field exercise — no risk to the running system. It can be exercised against the in-cluster Temporal first.
- **Phase 3 before Phase 4** because Phase 4 imports a new visibility store (Cloud's) and you do not want to debug "is this OpenSearch or is this Cloud?" at the same time. Drop OpenSearch first; Cloud arrives onto a clean substrate.
- **Phase 4 before Phase 6** because Phase 6 deletes the only fallback. If Cloud has issues during cutover, you still want the option to `pulumi up` against the existing GKE cluster.
- **Phase 5 in parallel with Phase 4** is acceptable because they touch disjoint files (CI workflow vs. infra/runtime). They could even be the same merge.

---

## 8. New / Modified / Deleted — explicit inventory

### NEW files

| File | Purpose |
|------|---------|
| `docker-compose.override.yml` | Dev-only services (`temporal`, `temporal-ui`), `build: .`, `--reload` |
| `docker-compose.prod.yml` | Prod overlay — `image:`, `restart: unless-stopped`, no temporal |
| `jaeger/config.yaml` | Single Jaeger v2 config (replaces collector + query split) |
| `.env.prod.example` | Template for production env (Cloud creds, GIT_SHA pin) |
| `.github/workflows/release.yml` | Build+push to ghcr.io on tag |
| Possibly `prometheus_data` named volume declaration | Persist metrics |

### MODIFIED files

| File | Lines | Change |
|------|-------|--------|
| `src/config.py` | 35–39 (TemporalSettings), 46 (flat), 91–113 (validator), 115–143 (build sub-models) | Add `namespace`, `api_key`, `tls`; conditional validation |
| `src/temporal/worker.py` | 17–25 (get_temporal_client) | Accept `TemporalSettings` instead of `address: str` |
| `src/main.py` | 188 | `settings.temporal` instead of `settings.temporal_address` |
| `docker-compose.yml` | Entire file | Strip dev-only bits to override; add postgres named volume |
| `.env.app.example`, `.env.app` | append | `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY`, `TEMPORAL_TLS` |
| `.env.temporal.example`, `.env.temporal` | append | `ENABLE_ES=false` |
| `.github/workflows/ci.yml` | 24, 27 | Drop `infra/` from `ruff check` targets after Phase 6 |
| `Dockerfile` | comment line 38 | Remove "GKE runs migrations as a separate K8s Job" comment; replace with `migrations run via compose-up of a one-shot service or the app's startup` note |
| `README.md`, `CONTRIBUTING.md`, `AGENTS.md` | "Deployment" sections | Replace Render/GKE references with compose-only |

### DELETED files / directories

| Path | Reason |
|------|--------|
| `infra/` (entire directory) | Pulumi project — no longer needed |
| `infra/components/*.py` (16 files) | Pulumi component modules including `temporal.py`, `opensearch.py`, `jaeger.py`, `prometheus.py`, `app.py`, `cluster.py`, `secrets.py`, etc. |
| `infra/Pulumi.yaml`, `Pulumi.dev.yaml`, `Pulumi.staging.yaml`, `Pulumi.prod.yaml` | Stack configs |
| `infra/__main__.py` | Pulumi entry point |
| `infra/DOMAIN-SETUP.md`, `OPERATIONS.md` | GKE-specific runbooks |
| `.github/workflows/cd-base.yml` | GKE deploy core |
| `.github/workflows/cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml` | Per-stack callers |
| `.env.opensearch`, `.env.opensearch.example` | OpenSearch removed entirely |
| `helm/`, `k8s/` | These directories don't currently exist in the repo (verified via `find`); confirm none accidentally created during transition |
| `render.yaml` | Already removed from repo; confirm `grep -r render.yaml` returns zero |

### UNCHANGED files (intentional callout)

| File | Why unchanged |
|------|---------------|
| `Dockerfile` (image stages) | Multi-stage build is sound; runtime image is hosting-agnostic |
| `src/main.py` lifespan structure | Worker-in-app process model survives the re-platform |
| `src/temporal/workflows.py`, `activities.py` | Workflow code is platform-agnostic by design |
| `migrations/`, `alembic.ini` | DB schema unaffected |
| `.github/workflows/ci.yml` test job | Tests still run against SQLite+aiosqlite |

---

## 9. Data Flow Changes

### Secrets

| Concern | Before (gks-refactor) | After (v1.1) |
|---------|----------------------|--------------|
| Source of truth | GCP Secret Manager | Operator-managed `.env.prod` file (or a host-level secret store the operator chooses — Doppler, 1Password CLI, plain env vars from systemd) |
| Sync mechanism | External Secrets Operator → K8s Secret → env var | Compose `env_file: .env.prod` → process env |
| Rotation | `kubectl rollout restart` after Secret Manager update | `docker compose up -d` after `.env.prod` edit |
| Audit trail | GCP audit logs | Git history of an encrypted-secrets file (recommend `sops` + `age` if the operator wants version-controlled secrets), or external secrets manager out-of-band |

### Trace storage

| Concern | Before | After |
|---------|--------|-------|
| Backend | OpenSearch (in-cluster ES7-compat) | Postgres (Jaeger v2 native driver) — same `postgres` container, separate database |
| Retention | Index rollover (`rollover_frequency: day`) configured in `jaeger/collector-config.yaml` | Application-level retention via `jaeger-spanstore-postgres` config or a cron `DELETE FROM` |
| Search performance | Sub-second on rich queries | Adequate for single-host volume; a high-volume deploy would need to revisit |

### Workflow visibility (Temporal UI search)

| Concern | Before | After |
|---------|--------|-------|
| Backend | OpenSearch in-cluster | Temporal Cloud (managed) for prod; Postgres advanced visibility for dev compose |
| Custom search attributes | Defined per namespace via `tctl` | Defined per namespace via Temporal Cloud UI / `temporal operator search-attribute create` |
| Workflow history | Temporal's own Cassandra/Postgres datastore | Temporal Cloud manages history end-to-end |

---

## 10. Integration Points — File:Line Reference Table

| Concern | File:Line | Current state | Required change |
|---------|-----------|----------------|------------------|
| Temporal client connect | `src/temporal/worker.py:17–25` | `Client.connect(address, interceptors=[...])` | Accept settings object; conditionally pass `namespace`, `api_key`, `tls` |
| Temporal client invocation | `src/main.py:188` | `await get_temporal_client(settings.temporal_address)` | `await get_temporal_client(settings.temporal)` |
| Temporal settings | `src/config.py:35–39` (`TemporalSettings`), `46` (flat `temporal_address`), `103–104` (validator), `138–142` (build) | Single `address` field | Add `namespace`, `api_key`, `tls`; gate validation by env |
| OTel endpoint env | `src/main.py:87` (`OTLPSpanExporter(endpoint=...)`) | Reads `settings.observability.otel_endpoint` | NO CHANGE — endpoint string just changes from `jaeger-collector:4317` → `jaeger:4317` (single-binary collapse) via `.env.app` |
| Prometheus scrape target | `prometheus/prometheus.yml` (not read in this research, but referenced) | Scrapes `app:8000` | NO CHANGE |
| App-side OpenSearch use | `src/` (any file) | None — confirmed by `grep` returning empty | NO CHANGE — no app code references OpenSearch |
| Compose temporal service | `docker-compose.yml:72–85` | `temporalio/auto-setup:1.26.2`, env_file `.env.temporal` | MOVE to override; ADD `ENABLE_ES=false` |
| Compose opensearch service | `docker-compose.yml:13–22` | `opensearchproject/opensearch:2.19.4` | DELETE entirely |
| Compose jaeger split | `docker-compose.yml:24–53` | Two services with separate configs | COLLAPSE to one `jaeger` service in v2 single-binary mode |
| Migrations on startup | `docker-compose.yml:69–70` (app `command:`) | `uv run alembic upgrade head && uvicorn ... --reload` | Move `--reload` to dev override; keep migration in prod (or split into one-shot service) |
| Postgres persistence | `docker-compose.yml:1–11` | NO volume — data is ephemeral | ADD named volume `postgres_data` (BUG: dev compose loses data on `down`) |
| Pulumi entry | `infra/__main__.py:1–46` | All component imports | DELETE entire file in Phase 6 |
| Pulumi temporal release | `infra/components/temporal.py:170–288` | Helm chart 0.74.0 with sidecar Auth Proxy | DELETE entire file in Phase 6 |
| GitHub Actions CD | `.github/workflows/cd-base.yml:121–129` (Pulumi action) | Builds + Pulumi up | DELETE entire file in Phase 6 |
| GitHub Actions CI lint | `.github/workflows/ci.yml:24, 27` (`ruff check ... infra/`) | Lints infra/ | DROP `infra/` arg in Phase 6 |

---

## 11. Anti-patterns to avoid

### Anti-pattern: profiles for prod/dev split
Compose `profiles:` is for *optional services within one environment* (e.g. `--profile observability`). A hard prod/dev split must use multiple compose files. Mixing the two leads to a compose file where reading "what runs in prod?" requires mental gymnastics over half a dozen `profiles: [prod]` annotations.

### Anti-pattern: putting `build: .` in prod compose
Forces every deploy host to have the source tree. Defeats reproducibility and slows deploys. Use a registry or a tarball of the built image, not source.

### Anti-pattern: leaving OpenSearch in dev because "it's already configured"
The milestone goal is hosting-agnostic. OpenSearch is 4GB+ resident memory minimum and turns a `docker compose up` into a several-minute startup on a developer's laptop. Removing it is a net win for dev velocity. Postgres advanced visibility for Temporal is the supported, tested-in-CI alternative.

### Anti-pattern: keeping the Cloud SQL Auth Proxy sidecar pattern
That entire sidecar (`infra/components/temporal.py:92–123`) is GCP-specific. In a Docker-only baseline, postgres is reachable on the compose network at `postgres:5432`. No proxy, no IAM, no `.connection_name`.

### Anti-pattern: deleting `infra/` before Cloud cutover validates
The git revert is not free. Pulumi state for the staging stack (`gs://vici-app-pulumi-state-staging`) is still live; deleting `infra/` does not delete state. Until Phase 4 has demonstrably worked end-to-end against Temporal Cloud, the in-cluster fallback is the only thing standing between an outage and a real product. Sequence Phase 6 last for a reason.

### Anti-pattern: a single `jaeger` service for prod with memory backend
Memory backend = traces lost on restart. For prod, postgres backend (or any persistent backend). Memory is fine for dev only.

---

## 12. Confidence Assessment

| Area | Confidence | Source |
|------|-----------|--------|
| Compose base/override pattern | HIGH | Official Docker docs ([merge how-to](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/)) |
| Temporal Cloud Python connection (API key + TLS) | HIGH | Context7 `/temporalio/sdk-python` + [official sample app](https://github.com/temporalio/documentation/blob/main/sample-apps/python/your_app/connect_cloud_dacx.py) |
| Postgres-as-Temporal-visibility (advanced visibility 12+) | HIGH | [Self-hosted Visibility setup](https://docs.temporal.io/self-hosted-guide/visibility) — advanced visibility on Postgres v12+ since Temporal Server v1.20; standard removed in v1.24 |
| `temporalio/auto-setup` env vars (`DB`, `ENABLE_ES`, `POSTGRES_SEEDS`) | HIGH | [Official docker-compose-postgres.yml](https://github.com/temporalio/docker-compose) |
| Jaeger v2 single-binary postgres backend | MEDIUM | Jaeger v2 supports postgres natively; current `jaeger/collector-config.yaml` shows the YAML structure — swapping the backend is a config-only change. Worth a feasibility spike in the Jaeger phase. |
| Vici app code has no OpenSearch dependency | HIGH | `grep -r opensearch src/` returned empty |
| API key vs mTLS choice | HIGH | Official Temporal Cloud guidance recommends API key for non-PKI orgs |
| Build order (Cloud cutover before infra deletion) | HIGH | Logical: deletion is irreversible without git history; cutover is reversible until deletion |
| GHCR for image hosting | MEDIUM | Common 2026 default for GitHub-hosted projects; the project may prefer Docker Hub or no registry — this is an operator preference, not a technical constraint |

---

## 13. Open Questions for the Roadmap Phase

1. **Jaeger trace store: Postgres or memory in prod?** Postgres is more durable; memory is simpler. If the operator wants traces > 1 hour, Postgres is the answer. Worth a quick "what does ops want here" call before authoring `jaeger/config.yaml`.
2. **Migrations: app startup or one-shot service?** Currently `command: alembic upgrade head && uvicorn` runs on every container start. Acceptable for single-replica deploys but races on multi-replica. Consider splitting into a `migrations` service with `restart: "no"`.
3. **Reverse proxy in prod compose?** Compose alone has no TLS. The "deploy anywhere" baseline likely assumes a reverse proxy (Caddy, Traefik, Nginx) handles TLS. Out of scope for v1.1 unless explicitly chosen — but the prod compose should reserve port 8000 internally only and let the reverse proxy be the operator's choice.
4. **Image registry: GHCR, Docker Hub, or none?** The "deploy anywhere" goal could argue for "no registry" (`build: .` in prod). Operator preference call.
5. **Secrets at rest: `.env.prod` plain or `sops`-encrypted?** Plain is simplest; `sops`+`age` is git-versioned. Either is compatible with compose's `env_file:` directive (sops needs decryption pre-`up`).

---

## Sources

- [docs.docker.com — Merge Compose files](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/) — base + override semantics
- [temporalio/sdk-python (Context7 `/temporalio/sdk-python`)](https://python.temporal.io/) — `Client.connect`, `TLSConfig`
- [temporalio/documentation — connect_cloud_dacx.py](https://github.com/temporalio/documentation/blob/main/sample-apps/python/your_app/connect_cloud_dacx.py) — canonical Python Cloud connect
- [docs.temporal.io — Temporal Cloud get-started](https://docs.temporal.io/cloud/get-started) — API key vs mTLS guidance
- [docs.temporal.io — Manage API keys](https://docs.temporal.io/cloud/api-keys) — API key lifecycle
- [docs.temporal.io — Self-hosted Visibility](https://docs.temporal.io/self-hosted-guide/visibility) — Postgres advanced visibility, ES removal in v1.24
- [Hub: temporalio/auto-setup](https://hub.docker.com/r/temporalio/auto-setup) — supported `DB`, `ENABLE_ES`, `POSTGRES_SEEDS` env vars
- [github.com/temporalio/docker-compose](https://github.com/temporalio/docker-compose) — `docker-compose-postgres.yml` reference
- [docs.temporal.io — Temporal Client (Python)](https://docs.temporal.io/develop/python/temporal-client) — `Client.connect` parameter list
- Internal: `.planning/PROJECT.md`, `.planning/STATE.md`, `.planning/workstreams/gks-refactor/ROADMAP.md`, `infra/components/temporal.py`, `src/config.py`, `src/temporal/worker.py`, `src/main.py`, `docker-compose.yml`, `Dockerfile`
