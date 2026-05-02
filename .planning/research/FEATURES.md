# Feature Landscape — v1.1 De-platform (Docker-Only Base)

**Milestone:** v1.1 — De-platform from GKE/GCP to a hosting-agnostic Docker-only baseline
**Researched:** 2026-05-01
**Confidence:** HIGH — official Docker, Temporal, Jaeger, Grafana, and Prometheus documentation cross-verified

## Scope Disclaimer

This document supersedes the prior product-feature research for v1.1 only. It catalogs **infrastructure/deploy features**, not application features. The v1.0 product surface (Twilio webhook, classify+extract, MatchService, Pinecone embeddings, Temporal workflows, OTel/Prometheus/structlog) is **already built and out of scope** — see `.planning/PROJECT.md` Validated Requirements.

The roadmap consumer should treat each feature below as a candidate phase or sub-phase scoped to the de-platform.

---

## Section 1 — `docker-compose.prod.yml` as Canonical Production Manifest

### Table-Stakes

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **Compose override file pattern** (`docker-compose.yml` base + `docker-compose.prod.yml` overlay) | Small | `docker-compose.yml` | Run with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`. Dev mounts `./src` and runs `--reload`; prod must NOT. The current dev compose mounts `./src:/app/src` and runs uvicorn `--reload` on line 70 — **prod overlay must remove the volume mount and the `--reload` flag** |
| **`restart: unless-stopped` on every long-running service** | Small | All services | Current dev compose has no restart policies. `unless-stopped` is the canonical prod choice — survives daemon restart but respects manual `docker compose stop` |
| **Healthchecks on every service** + **`depends_on: condition: service_healthy`** | Small | Already partial in dev | Dev compose already has healthchecks on postgres/opensearch/jaeger-collector/temporal/prometheus/grafana. Prod needs healthchecks on `app` (already in Dockerfile line 35) and on the worker process. Use `condition: service_healthy` to gate startup ordering deterministically |
| **Named volumes for all stateful services** (postgres, prometheus, jaeger-badger, grafana_data) | Small | All stateful services | Dev compose only declares `grafana_data` (line 126). Prod needs `postgres_data`, `prometheus_data`, `jaeger_data` (or whichever Jaeger backend is chosen). **No bind mounts for state** — they break portability across hosts |
| **`env_file:` per service** (already established pattern) | None | Existing | Dev compose already uses `.env.postgres`, `.env.app`, `.env.temporal`, etc. Continue this pattern — no changes needed beyond a `.env.app.production` variant |
| **Logging driver with rotation** (`json-file` with `max-size`/`max-file` or `local` driver) | Small | All services | Default `json-file` driver grows unbounded — fills disk on long-running prod hosts. Per-service `logging:` block with `driver: json-file` + `options: {max-size: "10m", max-file: "3"}` is the standard fix |
| **Pinned image tags** (no `:latest`) | Small | All services | Dev compose already pins most (`postgres:16`, `temporalio/auto-setup:1.26.2`, etc.) but uses `temporalio/ui:latest` (line 88) — this becomes irrelevant since temporal-ui is removed in v1.1 (Temporal Cloud hosts the UI) |
| **Non-root user in all custom images** (already done in app) | None | Existing Dockerfile | Dockerfile line 23 already adds `appuser` and switches with `USER appuser` |

### Differentiator

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **Compose `secrets:` for sensitive credentials** (Twilio token, OpenAI key, Pinecone key, Temporal Cloud cert/key, DATABASE_URL password) | Medium | `src/config.py` Settings class | Docker Compose secrets are mounted as files at `/run/secrets/<name>` and never appear in `docker inspect` or process env. Pattern: support `*_FILE` env vars in `Settings` that read the file content if present, else fall back to the env var. Affects every credential field in `src/config.py:9-89` (sms.auth_token, extraction.openai_api_key, pinecone.api_key, etc.) |
| **Separate worker service** (split FastAPI process from Temporal Worker process) | Medium | `src/main.py` lifespan, `src/temporal/worker.py` | Currently the FastAPI lifespan starts the Temporal worker as a background task in the same process. Splitting them into two compose services with the **same image, different commands** (one runs uvicorn, one runs `python -m src.temporal.worker`) is the canonical "scale workers independently" pattern. Required if `deploy.replicas` is later used |
| **`deploy.resources.limits` and `reservations`** (CPU + memory) | Small | All services | **CRITICAL**: per the Docker docs, `deploy.resources` limits **are honored by `docker compose up`** in modern Docker Engine (24+). Earlier guidance that "they're swarm-only" is outdated. Apply per service: `app` ~512M / 0.5 CPU, `postgres` ~1G, `prometheus` ~512M, `grafana` ~256M |
| **Read-only root filesystem** (`read_only: true`) for stateless services | Medium | App, prometheus, grafana | Containers like `app` write nothing to root FS — they can run `read_only: true` with `tmpfs:` for `/tmp`. Hardening that buys little day-1 value but pays off in supply-chain incident scenarios |
| **`init: true`** for processes that don't reap zombies | Small | App, worker | Python doesn't reap zombie subprocesses cleanly under PID 1. `init: true` injects tini |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|---------------------|
| **DO NOT use `docker compose up --scale app=N` to load-balance** | Compose's built-in scaling has no load balancer — you'd need Traefik/Caddy/nginx in front, which contradicts the "single-host, hosting-agnostic" baseline. If horizontal scaling is needed, that's a different milestone (Swarm/k8s/Nomad) | Single replica per service in v1.1. Document that horizontal scaling is a future milestone |
| **DO NOT bind-mount source code in prod** (`./src:/app/src`) | Mounts dev code into the prod image, defeats image immutability, and breaks if the deploy host doesn't have the repo checked out | Build the image with `COPY src/ ./src/` (Dockerfile line 28 already does this) and ship the immutable image |
| **DO NOT use `restart: always`** | Restarts even after manual `docker compose stop`, which masks operator intent during incident response | Use `restart: unless-stopped` |
| **DO NOT expose Postgres / Prometheus / Jaeger collector / Temporal-UI ports to the public internet** | Postgres has no IP-allowlist, Prometheus has no auth, Jaeger collector has no auth on 4317/4318, Temporal-UI has no auth. The existing dev compose exposes 5432, 9090, 4317, 4318, 16686 on `0.0.0.0` — **prod must bind these to `127.0.0.1` or omit `ports:` entirely** and access via `docker compose exec` / a bastion / SSH tunnel |
| **DO NOT use `:latest` tags** | Non-reproducible deploys; the same `docker compose pull` produces different images on different days. Dev compose currently has `temporalio/ui:latest` on line 88 — irrelevant for v1.1 because Temporal-UI is removed |
| **DO NOT commit `.env*` files with real secrets** | Even committing once leaks them via git history. `.env.example` patterns only |

---

## Section 2 — Temporal Cloud Connection

**Big picture:** Temporal Cloud removes the in-cluster `temporalio/auto-setup:1.26.2` service from the compose file (currently line 73-85) and the `temporal-ui` service (line 87-93). The app's Temporal client connects out to `<namespace>.<account>.tmprl.cloud:7233`. The Temporal-Cloud-hosted UI replaces the local `temporal-ui` service.

### Table-Stakes

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **mTLS authentication via TLSConfig** (cert + key files) | Medium | `src/temporal/worker.py:get_temporal_client` | Temporal Python SDK supports two auth modes for Cloud: **mTLS** (cert/key pair pinned to namespace) and **API key**. mTLS is the production-standard mode; API keys are easier but newer and have rate-limit caveats. With mTLS: `Client.connect(address, namespace=..., tls=TLSConfig(client_cert=cert_bytes, client_private_key=key_bytes))`. Can also use envconfig: `TEMPORAL_TLS_CLIENT_CERT_PATH` / `TEMPORAL_TLS_CLIENT_KEY_PATH`. Current `get_temporal_client(address)` signature must accept namespace and TLS material — see `src/temporal/worker.py:17-25` |
| **Namespace argument to `Client.connect`** | Small | `src/temporal/worker.py:get_temporal_client` | Self-hosted Temporal lets `namespace` default to `"default"`. Cloud requires the **fully-qualified** `<namespace_id>.<account_id>` form passed both as the namespace arg AND as part of the address. Settings must add `temporal.namespace` field |
| **Address format change** | Small | `src/config.py:TemporalSettings.address`, `.env.app` | Self-hosted: `temporal:7233` (current dev) or in-cluster DNS. Cloud: `<namespace>.<account>.tmprl.cloud:7233` (mTLS) or `<region>.<provider>.api.temporal.io:7233` (API key with HTTP routing). Just an env var change, no code change |
| **`tls=True` flag at minimum** | Trivial | `src/temporal/worker.py` | Even with API-key auth (no certs), `tls=True` is required for Cloud — it's a TLS-only endpoint |
| **Worker identity unchanged** | None | Existing | The Worker class (`src/temporal/worker.py:34-44`) is identical — it just inherits the new TLS-equipped Client. `TracingInterceptor` continues to work end-to-end with Cloud. **Critical: `Worker.run()` does not need any changes** |
| **Cron registration unchanged** | None | Existing | `start_cron_if_needed` (`src/temporal/worker.py:47-63`) works identically against Cloud. The `RPCStatusCode.ALREADY_EXISTS` idempotency guard already accommodates Cloud's behavior on restart |
| **Remove in-cluster Temporal services from compose** | Small | `docker-compose.yml` lines 72-93 | Delete `temporal:` and `temporal-ui:` service blocks. Delete `.env.temporal` and `.env.temporal-ui` files. Delete the schema-migration job artifacts referenced in STATE.md blockers ("Temporal schema migration job fails on re-run"). Delete the `gks-refactor` workstream's Temporal Helm chart |

### Differentiator

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **Use `temporalio.envconfig.ClientConfig.load_client_connect_config()`** to drive client construction from env vars instead of explicit `TLSConfig(...)` | Small | `src/temporal/worker.py` | The SDK ships an envconfig loader that consumes `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TLS_CLIENT_CERT_PATH`, `TEMPORAL_TLS_CLIENT_KEY_PATH`, `TEMPORAL_API_KEY` etc. directly. Lets you swap mTLS↔API-key↔self-hosted without touching the worker code |
| **Cert rotation via Compose secrets** | Small | Compose secrets feature above | Mount `temporal_client_cert` and `temporal_client_key` as Docker secrets at `/run/secrets/temporal_client_cert` etc. so cert rotation is a `docker compose up -d` after dropping new files in place |
| **Per-environment namespace** (`vici-prod.<account>`, `vici-staging.<account>`) | Small | Settings | Cloud namespaces are cheap; one per env is the standard pattern. No code change beyond env vars |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|---------------------|
| **DO NOT bake cert/key files into the Docker image** | Image leakage = cred leakage, and cert rotation requires a rebuild | Mount via Compose secrets or bind-mount from `/etc/vici/temporal-certs/` on the host (read-only, root-owned) |
| **DO NOT keep the in-cluster `temporal:` service "just in case"** for local dev | Two code paths for client construction (cloud-mTLS vs in-cluster-plaintext) means two test surfaces. Local dev should also use a Temporal Cloud "dev" namespace OR keep it for local-only via the dev compose, NOT the prod compose | Keep `temporal:` in `docker-compose.yml` (dev), drop it from `docker-compose.prod.yml`. Or run `temporal server start-dev` (the official local dev binary) instead of `auto-setup` if a leaner local dev is desired |
| **DO NOT pass cert/key as base64-encoded env vars** | Env vars leak via `docker inspect`, child processes, error logs. The SDK accepts `*_PATH` exactly to avoid this | Use `_PATH` variants always. `_DATA` only acceptable when reading from a Compose secret file path |

---

## Section 3 — Temporal Postgres Visibility (drop OpenSearch)

**Big picture:** Temporal Cloud already runs its own visibility store; the app doesn't manage visibility itself in v1.1. The only OpenSearch usage in the current stack is **Jaeger's** trace backend (line 13-22 of compose), NOT Temporal's. Temporal v1.20+ supports Postgres for advanced visibility *if self-hosting*, but since v1.1 moves to Cloud, this section is mostly **NOT APPLICABLE** for the Temporal half — the question conflates two OpenSearch users.

### Clarifying the OpenSearch Footprint

The current `docker-compose.yml` runs **one** OpenSearch instance (line 13). It is consumed by **`jaeger-collector`** and **`jaeger-query`** as the Jaeger storage backend (lines 32-34, 49-51). It is **NOT** wired to Temporal — the in-cluster `temporal:` service uses Postgres for both persistence and visibility (the default for `temporalio/auto-setup`). This means:

- "Drop OpenSearch entirely" is really "**replace Jaeger's OpenSearch backend with something compose-native**." See Section 4.
- Temporal Cloud handles its own visibility store invisibly — no app-side change.

### Table-Stakes

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **No app-level change** for Temporal visibility | None | Temporal Cloud | Cloud's visibility is opaque to the client. Workflow IDs, statuses, search attributes all queryable through the same `client.list_workflows(query=...)` API |
| **Confirm no custom search attributes are in use** | Trivial | `src/temporal/workflows.py`, `src/temporal/activities.py` | Grep for `upsert_search_attributes` and `set_search_attributes`. If none, the Cloud move is invisible. (Quick check: the current code in worker.py and activities.py shows none — confirm during phase) |

### Differentiator

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **Temporal Cloud Web UI** (replaces local `temporal-ui` on port 8080) | None | Temporal Cloud account | Cloud ships a hosted UI at `cloud.temporal.io` with the same workflow visibility, history viewer, query editor. Includes the `Count` API and `GROUP BY ExecutionStatus` aggregations |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|---------------------|
| **DO NOT add custom Temporal search attributes during the de-platform** | Postgres-backed (and Cloud-backed) custom attributes are scoped per-namespace and require coordinated migration; introducing them now adds cross-cutting risk to a deploy-only milestone | Defer to a future "search/observability" milestone if business needs them |
| **DO NOT self-host Temporal "to save the Cloud cost" mid-de-platform** | Re-introduces the operational burden the milestone is removing (schema migration job, persistence sizing, visibility store choice, certs, upgrades) | If cost is a real constraint, that's a separate decision later. The milestone goal is hosting-agnostic Docker, not cheapest |
| **DO NOT use `GROUP BY` outside `ExecutionStatus`** in app code | Per Temporal docs, only `ExecutionStatus` grouping is supported in the Count API today; assuming richer grouping will silently fail | If aggregations are needed, do them downstream in Postgres or push them through OTel metrics |

### Postgres-Visibility Limitations (informational, in case self-hosted is reconsidered)

Documented from Temporal docs cross-checked 2026-05-01:

- Custom search attributes are **per-namespace** in Postgres mode (vs global in Elasticsearch/OpenSearch mode)
- Single attribute value max **2 KB**, total payload max **40 KB**, max **255 chars per value**
- Search attribute values stored **unencrypted** in the visibility store — payload codec does not apply
- Recommended only for "low to moderate" workflow throughput; ES/OS recommended for high volume
- `GROUP BY` only supported by `ExecutionStatus` in the Count API regardless of backend

---

## Section 4 — Self-Contained Observability Stack in Compose for Production

**Big picture:** Replace OpenSearch with a Jaeger-native single-binary backend so the prod stack is Jaeger + Prometheus + Grafana + (optional) Loki for logs — all in compose, all persisted via named volumes, all bound to localhost.

### Table-Stakes

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **Jaeger v2 with Badger storage backend** (replaces OpenSearch) | Medium | `docker-compose.yml` lines 13-53, `jaeger/collector-config.yaml`, `jaeger/query-config.yaml` | Jaeger v2 (the current `jaegertracing/jaeger:2.16.0` image already in the compose file) supports Badger as a storage backend — single-binary embedded LMDB-style key-value store, no external dependencies. Configure via the YAML config (NOT CLI flags — Jaeger 2.x removed CLI flags). Set `SPAN_STORAGE_TYPE=badger`, `BADGER_DIRECTORY=/badger`, `BADGER_EPHEMERAL=false`, mount a named volume to `/badger`. Result: drop the OpenSearch service entirely. **Caveat:** Badger is single-instance only (cannot be shared across collector replicas), which matches the "single host, single replica" baseline |
| **Single Jaeger all-in-one container** OR **collector+query split** | Small | Above | The current dev compose uses the **split** pattern (collector + query as separate services). For a single-host prod, the all-in-one image is simpler and supported. Either is fine — preserve the split if it's already working with the existing config files |
| **Persist Prometheus TSDB** | Small | `docker-compose.yml` line 95-107 | Current dev compose has NO volume on Prometheus (line 95-107 shows only the config bind mount). Add `prometheus_data:/prometheus` named volume. Lose all metrics history on every container restart otherwise |
| **Configure Prometheus retention** | Trivial | `prometheus.yml` or command flags | Default is 15d. Set explicitly via `--storage.tsdb.retention.time=15d` (or 30d) and `--storage.tsdb.wal-compression`. Pass via `command:` in compose, not config file |
| **Bind monitoring ports to `127.0.0.1`** | Trivial | Compose ports stanzas | Change `"9090:9090"` → `"127.0.0.1:9090:9090"`, same for Jaeger 4317/4318/16686. Access via SSH tunnel. **The prod overlay is the right place for this — dev keeps `0.0.0.0`** |
| **Grafana provisioning via mounted YAML files** (already done in dev) | None | `grafana/provisioning/` directory | Dev compose line 113 already mounts `./grafana/provisioning:/etc/grafana/provisioning` — preserves the dashboards and datasources across restarts since `grafana_data` (line 126) is a named volume. Just continue this pattern |
| **Grafana admin password from a real secret** (not "admin/admin") | Small | `src/config.py:79-80`, `.env.grafana` | Current `Settings` defaults `grafana_admin_password = "admin"` (config.py line 80). Prod must source this from a Compose secret or a non-default env var. Use `${GRAFANA_ADMIN_PASSWORD__FILE:-/run/secrets/grafana_admin_password}` pattern in `.env.grafana` |
| **Persist Grafana data** (already done) | None | `grafana_data` volume | Already declared on line 126 of compose. Confirmed working |

### Differentiator

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **Loki + Promtail for centralized logs** (replaces "structlog→stdout, scrape via `docker logs`") | Medium | New compose services | Currently logs are JSON to stdout, retrieved via `docker logs` or `docker compose logs`. Loki gives structured search, retention, and Grafana integration without bringing back the OpenSearch footprint. Optional — Docker `json-file` log driver with rotation is also acceptable for v1.1 baseline |
| **Reverse proxy (Caddy or Traefik)** in front of Grafana with HTTPS | Medium | New service | Lets ops view dashboards over the public internet via `grafana.example.com` with TLS termination. Without this, dashboards require SSH tunnel. **Anti-feature unless explicitly desired** — adds attack surface |
| **Grafana datasource for Postgres** (so SQL-based dashboards work against the app DB directly) | Small | Existing | Existing pattern, already supported by Grafana provisioning |
| **OTel Collector intermediary** (app → otel-collector → jaeger + prometheus) | Medium | Refactor span/metric exporters | Decouples the app from the trace/metric backends. Allows dual-shipping to Jaeger AND a SaaS like Honeycomb/Datadog later. **Probably overkill for v1.1** unless multi-backend export is on the roadmap |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|---------------------|
| **DO NOT expose Prometheus to the public internet** | Prometheus has no built-in auth and exposes all scraped metrics, including app internals (token counts, error rates, infra labels), and supports remote query/admin endpoints (`--web.enable-admin-api`) that allow data deletion | Bind to `127.0.0.1`, access via SSH tunnel or behind authenticated reverse proxy |
| **DO NOT expose Jaeger collector OTLP ports (4317/4318) to the public internet** | They accept anonymous trace ingestion — anyone can flood your traces or push poisoned spans | Bind to `127.0.0.1`. App and worker are on the same compose network and use the in-network DNS name (`jaeger-collector:4317`) |
| **DO NOT expose Jaeger query UI (16686) without auth** | Trace data contains PII (phone numbers, message bodies in span attributes if not filtered). Anonymous read = data leak | Same as above — bind to `127.0.0.1` or put behind authenticated reverse proxy |
| **DO NOT bring back OpenSearch "for log aggregation"** | OpenSearch is exactly what v1.1 is removing. Brings back JVM tuning, replicas=0 single-node yellow health hack, 1+ GB memory floor, license complexity | Use Loki (lightweight, single-binary) or `json-file` driver with rotation if log search is needed |
| **DO NOT default-keep `admin/admin` for Grafana in prod** | Default creds are the #1 vector for misconfigured prod observability stacks. The current `Settings.grafana_admin_password = "admin"` (config.py:80) is **only safe in dev** | Settings must require a non-default password when `env=production`; add a model_validator that fails fast |
| **DO NOT persist Jaeger Badger to a bind mount on macOS hosts in dev** | Badger uses memory-mapped files; macOS Docker Desktop's bind mounts have known mmap performance/correctness issues | Named volume only. Bind mount is fine on Linux hosts |

---

## Section 5 — Image Distribution

**Big picture:** Define a canonical image source so deploy hosts pull, not build. The "any host can run this" goal is well-served by a registry + tag immutability.

### Table-Stakes

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **GHCR image build + push via GitHub Actions on `main` and on tag** | Medium | `.github/workflows/ci.yml` (existing per STATE.md), `Dockerfile` | The repo already has GitHub Actions CI per Phase 02.5 ("GitHub Actions CI"). Add a publish job that runs `docker/build-push-action@v5` with `tags: ghcr.io/${{ github.repository }}:sha-${{ github.sha }}, ghcr.io/${{ github.repository }}:latest` (or version tag). Auth via `GITHUB_TOKEN`. No external secrets needed |
| **`docker-compose.prod.yml` references `image: ghcr.io/...`, NOT `build: .`** | Trivial | Compose file | Dev compose line 56 has `build: .`. Prod must use `image: ghcr.io/<org>/vici:<tag>` so deploy hosts only need `docker compose pull && docker compose up -d` — they never need the source repo |
| **Tag images by commit SHA** (immutable) AND optionally `latest` | Small | Above | `sha-<short>` is the canonical immutable tag. `latest` is a moving alias. Use SHA tags in `docker-compose.prod.yml` to make rollbacks deterministic. Set `GIT_SHA` env var for the `service_version` field that already wires to OTel (config.py:32, line 66 `git_sha`) |
| **Multi-arch build (amd64 + arm64)** | Small | `docker/build-push-action` matrix | One-line addition (`platforms: linux/amd64,linux/arm64`). Free with buildx. Lets the same image run on Apple Silicon dev hosts and standard Linux servers |
| **Image scan in CI** (e.g. `trivy`, `docker scout`) | Small | New CI job | `docker/scout-action@v1` or `aquasecurity/trivy-action@master`. Fails the build on HIGH/CRITICAL CVEs. Becomes a hard gate before push |

### Differentiator

| Feature | Complexity | Depends On | Notes |
|---------|------------|------------|-------|
| **Image signing with cosign** (Sigstore) | Medium | New CI job, key management | `cosign sign --keyless` using GitHub OIDC. Lets deploy hosts verify provenance with `cosign verify`. Production-grade supply-chain hardening. Probably overkill for v1.1 unless compliance requires it |
| **SBOM generation** (`syft` or build-push-action's built-in `provenance: true, sbom: true`) | Small | CI | Built-in flag on the official Docker action. No extra service. Worth doing |
| **Build provenance attestations** | Small | CI | Same one-liner as SBOM. Lets you trace any image back to the exact GitHub Actions run that built it |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|---------------------|
| **DO NOT do `docker compose build` on the deploy host** | Requires the source repo on every prod host (loses "any host" portability), requires build toolchain (compilers, network access for `apt update`, `uv sync` from PyPI), creates a different image hash per host (no rollback, no verification), and the build-time secrets surface multiplies | Build once in CI, push to GHCR, pull on hosts. **This is the entire point of having a registry** |
| **DO NOT build locally and `docker save | scp | docker load`** | Same problems as above plus the social problem ("which dev's laptop built the prod image?") | GHCR + CI |
| **DO NOT use Docker Hub for a hosting-agnostic baseline** | Requires a separate account, has rate limits on anonymous pulls (100/6h), and its trust story is messier than GHCR for repos that already live on GitHub | GHCR is free, scoped to the GitHub org/user, auth-coupled to the repo |
| **DO NOT keep `:latest` as the only prod tag** | Non-reproducible. "What's running in prod?" becomes unanswerable | SHA tags in `docker-compose.prod.yml`; promote via `docker compose pull && docker compose up -d` referencing a new SHA |
| **DO NOT install build tools (uv, gcc, etc.) in the runtime stage** | Already correctly avoided — the existing multi-stage Dockerfile (Dockerfile lines 2-9 builder, 12-38 runtime) only copies `.venv` from the builder stage | Confirmed clean — no action needed |

---

## Feature Dependencies (Phase Ordering Hints)

```
[Image Distribution: GHCR + CI publish]
    ↓ (so prod compose can `image:` instead of `build:`)
[docker-compose.prod.yml skeleton]
    ↓ (so we have a deploy target to test against)
[Temporal Cloud connection rewrite] ── parallel ──> [Jaeger Badger backend swap]
    ↓                                                ↓
[Remove in-cluster temporal + temporal-ui]          [Remove OpenSearch service]
                                ↓
                        [End-to-end smoke test on a fresh Docker host]
                                ↓
                        [Delete pulumi/, helm/, k8s/, ESO, render.yaml, gks-refactor artifacts]
```

The GKE/GCP cleanup happens **last** — only after the new baseline is verified end-to-end on a clean host, so there's no regression-rescue path back to the old infra.

---

## Sources

- [Compose Deploy Specification | Docker Docs](https://docs.docker.com/reference/compose/compose-file/deploy/)
- [Manage secrets securely in Docker Compose | Docker Docs](https://docs.docker.com/compose/how-tos/use-secrets/)
- [Control startup and shutdown order in Compose | Docker Docs](https://docs.docker.com/compose/how-tos/startup-order/)
- [Docker Compose Production Setup Guide (2026) | ZTABS](https://ztabs.co/blog/docker-compose-production-setup)
- [Temporal Client - Python SDK | Temporal Platform Documentation](https://docs.temporal.io/develop/python/temporal-client)
- [Authenticate with mTLS certificates - Temporal Cloud](https://docs.temporal.io/cloud/certificates)
- [Environment configuration | Temporal Platform Documentation](https://docs.temporal.io/develop/environment-configuration)
- [Self-hosted Visibility feature setup | Temporal Platform Documentation](https://docs.temporal.io/self-hosted-guide/visibility)
- [Temporal Visibility | Temporal Platform Documentation](https://docs.temporal.io/visibility)
- [Search Attributes | Temporal Platform Documentation](https://docs.temporal.io/search-attribute)
- [Persisting Data in Jaeger with Badger Storage · jaegertracing · Discussion #7487](https://github.com/orgs/jaegertracing/discussions/7487)
- [jaegertracing/jaeger Docker image](https://hub.docker.com/r/jaegertracing/jaeger)
- [Deployment | Jaeger](https://www.jaegertracing.io/docs/1.76/deployment/)
- [Provision Grafana | Grafana documentation](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Configure a Grafana Docker image | Grafana documentation](https://grafana.com/docs/grafana/latest/setup-grafana/configure-docker/)
- [Docker - How to Persist Prometheus Data for Reliable Monitoring | SigNoz](https://signoz.io/guides/how-to-persist-data-in-prometheus-running-in-a-docker-container/)
- [Working with the Container registry - GitHub Docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Publishing Docker images - GitHub Docs](https://docs.github.com/actions/guides/publishing-docker-images)
- Context7: `/temporalio/sdk-python` — `Client.connect`, `TLSConfig`, namespace argument forms (verified 2026-05-01)
