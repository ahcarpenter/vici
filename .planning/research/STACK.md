# Stack Research — v1.1 De-platform (Docker-Only Base)

**Domain:** Hosting-agnostic Docker-only baseline for SMS-based job matching API
**Researched:** 2026-05-01
**Confidence:** HIGH — Temporal SDK + Server, Compose Spec, and auto-setup env vars verified against Context7 (`/temporalio/documentation`, `/websites/python_temporal_io`, `/docker/docs`, `/docker/compose`) and current GitHub releases (Compose v5.1.3, sdk-python 1.27.0, Temporal Server v1.31.0).

> **Scope:** v1.1 *milestone-scoped* additions and removals. The validated v1.0 stack
> (FastAPI/Python 3.12/Postgres 16/Pinecone/OpenAI/Twilio/asyncpg/SQLModel/Alembic/structlog/OTel/Prometheus/Grafana/Jaeger v2/Temporal Python SDK)
> is **NOT re-researched here** — see git history of this file for the v1.0 record. This document
> covers ONLY what changes for the de-platform.

---

## Executive Summary

The v1.1 de-platform requires:

1. **No new Python production dependencies** — `temporalio>=1.27.0` (currently `>=1.24.0`) already supports
   Temporal Cloud mTLS via `Client.connect(..., tls=TLSConfig(...))`. The change is configuration
   and bytes-loading at the `get_temporal_client` call site, not a new library.
2. **One new Compose Spec service for self-host visibility schema migration** —
   `temporalio/admin-tools` running `temporal-sql-tool ... setup-schema/update-schema` against a
   `temporal_visibility` Postgres database (replaces the implicit `auto-setup` Elasticsearch path).
3. **Switch the Temporal image to `temporalio/auto-setup:1.31.0`** (currently `1.26.2`) and set
   `ENABLE_ES=false` + `DB=postgres12` so the bundled auto-setup writes the SQL visibility schema
   instead of expecting Elasticsearch/OpenSearch.
4. **Adopt Compose Spec v5.x top-level `secrets:` blocks** sourced from files for
   production-credential injection (replaces ESO entirely). Local dev keeps `.env.*` files.
5. **Adopt SOPS + age** for git-encrypted production secrets so `docker-compose.prod.yml` stays
   committed and operators decrypt at deploy time.
6. **Delete an entire infrastructure tree** — `infra/` (Pulumi), `helm/`, `k8s/`, `render.yaml`,
   ESO manifests, OpenSearch from the compose stack, Cloud SQL Auth Proxy, and any GCP-flavoured
   Python deps (none currently exist — confirmed via `pyproject.toml` audit).

**Net diff at the dependency level:** zero new Python runtime deps, one bumped pin
(`temporalio>=1.27.0`), one removed compose service (`opensearch`), three new compose services for
the prod profile (`temporal-admin-tools` for schema, `app-migrate` for Alembic, optional
`temporal-worker` if split from `app`), and a `secrets:` block replacing inline credential env vars.

---

## 1. Temporal Cloud Client Integration

### Recommendation

Bump the pin and load mTLS material from files mounted via Compose secrets.

| Item | Value | Source |
|------|-------|--------|
| `temporalio` SDK pin | `>=1.27.0,<2.0.0` (latest 2026-04-30) | [PyPI temporalio 1.27.0](https://pypi.org/project/temporalio/), [GH release](https://github.com/temporalio/sdk-python/releases/tag/1.27.0) |
| Connection API | `Client.connect(target_host, namespace=..., tls=TLSConfig(...))` | Context7 `/websites/python_temporal_io` (HIGH) |
| Address format | `<namespace>.<account-id>.tmprl.cloud:7233` | [Temporal Cloud docs](https://docs.temporal.io/cloud/connect-to-cloud) (HIGH) |
| Namespace format | `<namespace>.<account-id>` | Same (HIGH) |

### Why bump from 1.24.0 → 1.27.0

- The `tls=TLSConfig(...)` API surface is stable across 1.24–1.27 (no breaking changes for client
  connect) — pin floor is conservative future-proofing, not a forced migration.
- 1.27.0 ships **OTel tracing for standalone activities** which we benefit from given the existing
  `TracingInterceptor` integration ([1.27.0 release notes](https://github.com/temporalio/sdk-python/releases/tag/1.27.0)).
- 1.21.0 introduced an implicit-TLS-when-api_key behaviour change — irrelevant for us since we use
  mTLS, but worth noting if we ever swap to Temporal Cloud API keys instead of certs.

### Environment variable contract

Standardize on the Temporal-recommended env var names so the same variables work in CLI, SDK
samples, and our code:

```bash
TEMPORAL_ADDRESS=<ns>.<acct>.tmprl.cloud:7233
TEMPORAL_NAMESPACE=<ns>.<acct>
TEMPORAL_TLS_CLIENT_CERT_PATH=/run/secrets/temporal_client_cert
TEMPORAL_TLS_CLIENT_KEY_PATH=/run/secrets/temporal_client_key
```

(Source: [Temporal docs — Configure Temporal Cloud via env vars](https://docs.temporal.io/develop/python/temporal-clients), HIGH confidence.)

### Integration points (file-by-file)

| File | Change | Notes |
|------|--------|-------|
| `src/temporal/worker.py` :: `get_temporal_client` | Read cert/key bytes from paths in Settings; build `TLSConfig`; pass `tls=...` and `namespace=...` to `Client.connect`. Keep `TracingInterceptor` wiring untouched. | Single-function change — ~15 lines. Today the function takes `address: str` only; widen to take a `TemporalSettings` reference (already exists in `src/config.py`). |
| `src/config.py` :: `TemporalSettings` | Add `namespace: str = ""`, `tls_client_cert_path: str = ""`, `tls_client_key_path: str = ""`. Add three flat env vars (`temporal_namespace`, `temporal_tls_client_cert_path`, `temporal_tls_client_key_path`) and remap in `_build_sub_models`. Add a `tls_enabled: bool` derived field (true when both paths are set). | Mirrors existing pattern for `temporal_address`. |
| `src/main.py` (lifespan) | No change — already calls `get_temporal_client(settings.temporal.address)`. Just pass the full `settings.temporal`. | |
| `src/temporal/constants.py` | No change. | |
| `pyproject.toml` | Bump `temporalio>=1.24.0` → `temporalio>=1.27.0,<2.0.0`. | |

### What we are NOT adding

- No `cryptography` dep — `TLSConfig` accepts `bytes` directly via `Path.read_bytes()`.
- No Temporal SDK plugins (Workflow Streams, etc.) — out of scope for v1.1.
- No `nexus` features — out of scope.
- No Temporal Cloud API key auth path — mTLS chosen because it's the GA, lower-rotation-burden
  default for production self-managed certs.

### Local dev fallback

`get_temporal_client` must remain compatible with the **self-hosted local Temporal** (no TLS). The
toggle: if `tls_client_cert_path` is empty, pass `tls=False` (or omit `tls=`) and skip namespace
override. This keeps `docker-compose.yml` working unchanged for the dev loop.

---

## 2. Temporal with Postgres Visibility (Local Dev)

### Recommendation

Use **`temporalio/auto-setup:1.31.0`** with `DB=postgres12` and `ENABLE_ES=false`. Visibility lands
in a separate Postgres database (`temporal_visibility`) using the same credentials as the main
Temporal database. Schema migrations are bundled into `auto-setup` for dev; for production self-host
(if ever needed) run `temporalio/admin-tools` as a one-shot job.

### Verified support

| Question | Answer | Source |
|----------|--------|--------|
| Does Temporal still support Postgres advanced visibility? | Yes — Postgres v12+ on Temporal Server v1.20+ supports advanced visibility. **Not deprecated** as of v1.31.0. | [docs.temporal.io/self-hosted-guide/visibility](https://docs.temporal.io/self-hosted-guide/visibility) (HIGH) |
| Does `auto-setup` configure Postgres visibility automatically? | Yes when `DB=postgres12`, `ENABLE_ES=false`, and `VISIBILITY_DBNAME` is set. The script creates both `temporal` and `temporal_visibility` databases and runs `temporal-sql-tool setup-schema` + `update-schema` against versioned schema directories. | [auto-setup.sh source](https://github.com/temporalio/docker-builds/blob/main/docker/auto-setup.sh) (HIGH) |
| Is there a separate migration image? | `temporalio/admin-tools:<server-version>` ships `temporal-sql-tool` for production setups that don't want to run `auto-setup` in prod. | [Temporal visibility docs](https://docs.temporal.io/self-hosted-guide/visibility) (HIGH) |
| Latest auto-setup tag? | `temporalio/auto-setup:1.31.0` (matches Temporal Server [v1.31.0](https://github.com/temporalio/temporal/releases/tag/v1.31.0), released 2026-04-29). | [Docker Hub](https://hub.docker.com/r/temporalio/auto-setup) (HIGH) |

### Environment variables for the local-dev `temporal` service

These replace the OpenSearch-dependent variables currently in `.env.temporal`:

```bash
DB=postgres12
DB_PORT=5432
POSTGRES_USER=temporal
POSTGRES_PWD=temporal
POSTGRES_SEEDS=postgres            # service name in compose
DBNAME=temporal                    # main DB
VISIBILITY_DBNAME=temporal_visibility
ENABLE_ES=false                    # critical — disables ES/OS path
TEMPORAL_ADDRESS=temporal:7233
TEMPORAL_CLI_ADDRESS=temporal:7233
DYNAMIC_CONFIG_FILE_PATH=config/dynamicconfig/development-sql.yaml
```

**Critical:** the existing project Postgres user (`vici`, used by Alembic for the app schema) and
the Temporal Postgres user (`temporal`) must be **different roles in the same Postgres instance**,
or — cleaner — Temporal gets its own database within the same `postgres` service. Auto-setup creates
`temporal` and `temporal_visibility` as separate databases. The app continues to use a third
database (`vici`) on the same Postgres 16 image.

### Schema migration tooling

For local dev: `auto-setup` handles it on container boot. No action.

For self-hosted production (out of scope but documented for completeness — Temporal Cloud is the
target so this is a fallback path only):

```yaml
# docker-compose.prod.yml — temporal-admin-tools one-shot
temporal-admin-tools:
  image: temporalio/admin-tools:1.31.0
  command: >
    sh -c "
      temporal-sql-tool --plugin postgres12 --ep $${POSTGRES_HOST} -u $${POSTGRES_USER} -p 5432 --db temporal create &&
      temporal-sql-tool --plugin postgres12 --ep $${POSTGRES_HOST} -u $${POSTGRES_USER} -p 5432 --db temporal setup-schema -v 0.0 &&
      temporal-sql-tool --plugin postgres12 --ep $${POSTGRES_HOST} -u $${POSTGRES_USER} -p 5432 --db temporal update-schema -d /etc/temporal/schema/postgresql/v12/temporal/versioned &&
      temporal-sql-tool --plugin postgres12 --ep $${POSTGRES_HOST} -u $${POSTGRES_USER} -p 5432 --db temporal_visibility create &&
      temporal-sql-tool --plugin postgres12 --ep $${POSTGRES_HOST} -u $${POSTGRES_USER} -p 5432 --db temporal_visibility setup-schema -v 0.0 &&
      temporal-sql-tool --plugin postgres12 --ep $${POSTGRES_HOST} -u $${POSTGRES_USER} -p 5432 --db temporal_visibility update-schema -d /etc/temporal/schema/postgresql/v12/visibility/versioned
    "
  environment:
    SQL_PASSWORD: $${POSTGRES_PWD}
  depends_on:
    postgres: { condition: service_healthy }
  restart: "no"
```

### Why not stay on OpenSearch

- OpenSearch is the single largest dev-loop resource hog in the current stack (~1GB RAM, slow
  startup, yellow-cluster-health gymnastics — see `[Phase 02.3]: opensearch replicas=0 for single-node
  local dev` decision in `STATE.md`).
- Temporal's Postgres advanced-visibility path is fully supported on v1.20+ and tested for our scale
  (single inbound webhook, low workflow throughput). Search attribute queries via SQL are fast
  enough for the volume v1 will see.
- Removing OpenSearch eliminates the `jaeger-collector → opensearch` storage backend dependency.
  Jaeger v2 will be reconfigured for **Badger** (file-based) or **memory** storage in dev — see
  [companion research note in `PITFALLS.md`](./PITFALLS.md) for the Jaeger-storage migration trap.

### Integration points

| File | Change |
|------|--------|
| `docker-compose.yml` (dev) | Replace `opensearch` service with the env-var changes to `temporal`. Update `jaeger-collector` storage backend to `badger` (file) or `memory`. Bump `temporalio/auto-setup` from `1.26.2` → `1.31.0`. |
| `.env.temporal` (dev) | Add `ENABLE_ES=false`, `VISIBILITY_DBNAME=temporal_visibility`, point `POSTGRES_SEEDS` at the existing `postgres` service. Remove any `ES_*` variables. |
| `.env.opensearch` | Delete file. |
| `.env.opensearch.example` | Delete file. |
| `jaeger/collector-config.yaml`, `jaeger/query-config.yaml` | Reconfigure for Badger or memory backend (no longer talk to OpenSearch). |

---

## 3. Production Docker Compose Tooling

### Recommendation

Adopt **Compose Spec v5.x** (Mont Blanc, Dec 2025) features and use a layered file approach:
`docker-compose.yml` (dev) + `docker-compose.prod.yml` (prod overrides) + `docker-compose.override.yml`
(local-only secrets/dev tweaks, gitignored).

| Item | Value | Source |
|------|-------|--------|
| Compose CLI minimum | v5.1.0+ (use latest v5.1.3) | [GH releases](https://github.com/docker/compose/releases) (HIGH) |
| Compose Spec version | 5.0.0 "Mont Blanc" — no `version:` key needed in YAML | [Compose Spec](https://github.com/compose-spec/compose-spec/blob/main/spec.md) (HIGH) |
| Validation in CI | `docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` (exits non-zero on invalid) | Context7 `/docker/docs` `compose_config.md` (HIGH) |

### Required v1.1 features (all native to Compose Spec)

| Feature | Used For | Spec Reference |
|---------|----------|----------------|
| `healthcheck:` | Liveness probes for `app`, `postgres`, `temporal`, `prometheus`, `grafana` (already in use; keep) | [spec.md#healthcheck](https://github.com/compose-spec/compose-spec/blob/main/spec.md#healthcheck) |
| `depends_on:` with `condition: service_healthy` | Boot order: `postgres` → `temporal` → `app-migrate` → `app` | Already in use, keep |
| `restart: unless-stopped` | Production restart policy (NOT `always` — prevents container thrash on bad config) | [spec.md#restart](https://github.com/compose-spec/compose-spec/blob/main/spec.md#restart) |
| `secrets:` (top-level + service-level) | mTLS certs, DB passwords, API keys mounted at `/run/secrets/<name>` | [Docker Docs — Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/) |
| `env_file:` (list, layered) | Per-environment defaults — e.g. `[.env.app, .env.app.production]` | [Compose Spec](https://github.com/compose-spec/compose-spec/blob/main/spec.md#env_file) |
| `deploy.resources.limits` (cpus, memory) | Resource caps. **Note:** in non-Swarm mode these are honoured by Compose v2.x+ via the bridge to Engine resource limits — verified in [docker/compose#7307](https://github.com/docker/compose/issues/7307) (closed: implemented). For belt-and-suspenders compatibility, also set top-level `mem_limit:` and `cpus:` (Compose v2 still respects both). | [Deploy Spec](https://docs.docker.com/reference/compose-file/deploy/) |
| `pull_policy: always` | Force prod to fetch the immutable digest each deploy | [spec.md#pull_policy](https://github.com/compose-spec/compose-spec/blob/main/spec.md#pull_policy) |
| Image digests (`image: foo@sha256:...`) | Reproducible deploys; render via `docker compose config --resolve-image-digests --lock-image-digests` in CI | Context7 `/docker/docs` `compose_config.md` (HIGH) |
| `profiles:` | Enable optional services (`tools`, `migrate`, `worker`) without polluting the default stack | [spec.md#profiles](https://github.com/compose-spec/compose-spec/blob/main/spec.md#profiles) |

### CI validation pattern

```yaml
# .github/workflows/ci.yml — compose-validate job
- name: Validate dev compose
  run: docker compose -f docker-compose.yml config --quiet
- name: Validate prod compose
  run: docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
- name: Lint with hadolint (Dockerfile) + yamllint (compose files)
  run: |
    docker run --rm -i hadolint/hadolint < Dockerfile
    yamllint docker-compose.yml docker-compose.prod.yml
```

The `--quiet` flag is documented in `compose config`'s help: *"Only validate the configuration, don't print anything"* (Source: Context7 `/docker/docs` — `compose_config.md`, HIGH confidence).

### Compose v1 vs v2

Compose v1 (the Python `docker-compose` binary) is **end-of-life** and has been deprecated since
2023; v2 is a Go-native CLI plugin (`docker compose ...`, no hyphen). Vici's CI runners must use v2.
GitHub-hosted runners ship Compose v2 by default ([GitHub changelog 2026-01-30](https://github.blog/changelog/2026-01-30-docker-and-docker-compose-version-upgrades-on-hosted-runners/)). No v1-specific syntax is in our current `docker-compose.yml` (no `version: '3.x'` header, no `links:`, no `extends:` in the legacy form), so the migration is trivial.

### Multi-stage Dockerfile (existing)

`Dockerfile` already follows best practice: distinct `builder` and `runtime` stages, non-root user,
HEALTHCHECK probe, `uv sync --frozen --no-dev`. **No changes required** for v1.1. Optional polish:
add `--mount=type=cache,target=/root/.cache/uv` for builder-stage caching when CI BuildKit is
available. Defer.

---

## 4. Secrets Management (Replacing ESO)

### Recommendation: layered approach

| Layer | Tool | Use Case |
|-------|------|----------|
| **Code-resident** (committed) | none — never commit secrets | — |
| **Local dev** | `.env.<service>` files (gitignored, per `.gitignore` already has `.env*`) | Developer machines and CI test runs use placeholder/test secrets |
| **Production at rest** | **SOPS + age** encrypting `secrets/` directory in repo | Operators decrypt at deploy with `SOPS_AGE_KEY` env var |
| **Production runtime** | Compose Spec `secrets:` block sourcing the decrypted files | Mounts at `/run/secrets/<name>` with file permissions; never visible in `docker inspect`/`ps`/process env |

### Why not just `env_file` in production

Per Docker's own guidance ([Manage secrets securely in Docker Compose](https://docs.docker.com/compose/how-tos/use-secrets/), HIGH confidence):

> "Environment variables are often available to all processes, and it can be difficult to track access. They can also be printed in logs when debugging errors. Using secrets mitigates these risks."

Secrets-as-files (mounted under `/run/secrets/`) are read-only, owned by the container user, and
not visible in `docker inspect`. Twelve-factor purists object, but the security-vs-purity tradeoff
clearly favours files for credentials (mTLS keys, DB passwords, API tokens).

### Why SOPS + age (not Vault, not cloud KMS)

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **SOPS + age** | Single binary, no server, git-native diffs (only values encrypted, keys plaintext), works offline, ~5MB total tooling | Requires age key distribution to operators | **Chosen** — matches "deploy anywhere" goal |
| HashiCorp Vault | Industry standard | Server to run, auth complexity, overkill for v1.1 | Defer until multi-environment / multi-tenant |
| Cloud KMS (AWS/GCP/Azure) | Managed | Re-introduces cloud lock-in we just removed | Anti-goal |
| Doppler / Infisical | Hosted UX | SaaS dependency, network coupling at deploy time | Defer |
| Plain encrypted tarball (`gpg`) | Trivial | No key rotation story, no per-file encryption, painful diffs | No |

**Source confidence:** MEDIUM — pattern is widely adopted (see [Stackademic Mar 2026 article](https://blog.stackademic.com/secrets-management-in-docker-compose-env-sops-bitwarden-and-the-good-enough-threat-model-2bbc6d8e1064?gi=ea947853c9c5), [SOPS official repo](https://github.com/getsops/sops), [phoenixtrap.com Dec 2025](https://phoenixtrap.com/2025/12/22/10-lines-to-better-docker-compose-secrets/)) and validated against three independent recent posts. Caveat: SOPS workflow choice is opinionated; the team can swap to Vault later without rewriting the Compose `secrets:` blocks (only the source-file-generation step changes).

### Recommended additions

| Tool | Version | Purpose | Why |
|------|---------|---------|-----|
| `sops` | v3.9.x+ (latest 2026: ~3.10) | Encrypt `secrets/*.yaml` and `secrets/*.env` files | Mozilla's tool, age-native, git-friendly diffs |
| `age` | v1.2.x | Underlying encryption | Modern, simple, no PGP keyring complexity |
| (No Python deps) | — | — | These are operator/CI tools, not app deps |

Install: `brew install sops age` (Mac), `apt install age && curl -L .../sops_v3.10_amd64.deb` (Linux/CI).

### Compose secrets block (canonical pattern)

```yaml
# docker-compose.prod.yml
services:
  app:
    secrets:
      - source: postgres_password
        target: postgres_password
        mode: 0400
      - source: openai_api_key
      - source: pinecone_api_key
      - source: temporal_client_cert
      - source: temporal_client_key
      - source: twilio_auth_token
      - source: braintrust_api_key
    environment:
      DATABASE_PASSWORD_FILE: /run/secrets/postgres_password
      OPENAI_API_KEY_FILE: /run/secrets/openai_api_key
      # ... mirror for each *_FILE convention

secrets:
  postgres_password:
    file: ./secrets/decrypted/postgres_password
  openai_api_key:
    file: ./secrets/decrypted/openai_api_key
  pinecone_api_key:
    file: ./secrets/decrypted/pinecone_api_key
  temporal_client_cert:
    file: ./secrets/decrypted/temporal_client.pem
  temporal_client_key:
    file: ./secrets/decrypted/temporal_client.key
  twilio_auth_token:
    file: ./secrets/decrypted/twilio_auth_token
  braintrust_api_key:
    file: ./secrets/decrypted/braintrust_api_key
```

### Settings code change (Pydantic Settings)

`pydantic-settings` already supports the `_FILE` suffix convention via the `secrets_dir`
configuration:

```python
# src/config.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        secrets_dir="/run/secrets",  # NEW — pydantic auto-reads files here
        extra="ignore",
    )
```

When `/run/secrets/openai_api_key` exists at boot, pydantic reads the file content as the
`openai_api_key` field value. Falls back to env var if file missing — meaning **dev keeps the
existing `.env` flow unchanged**. Confidence: HIGH ([pydantic-settings secrets docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/#secrets)).

### Deploy workflow

```bash
# Operator workstation — encrypt once
sops --encrypt --age $RECIPIENT_PUBLIC_KEY secrets/raw/openai_api_key > secrets/encrypted/openai_api_key.enc

# Production host — decrypt at deploy
export SOPS_AGE_KEY_FILE=/etc/sops/age.key
mkdir -p secrets/decrypted
for f in secrets/encrypted/*.enc; do
  sops --decrypt "$f" > "secrets/decrypted/$(basename "${f%.enc}")"
done
chmod 0400 secrets/decrypted/*
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

`secrets/encrypted/` is checked in. `secrets/decrypted/` is `.gitignore`d and `chmod 0700`. The age
private key lives outside the repo — typically a single file the deploying operator scp's once and
forgets.

---

## 5. What Can Be Removed

### Python dependencies — confirmed audit

I read every line of `pyproject.toml`. **None of the listed deps are GCP/GKE/Render/ESO-specific.**
The current dep list (`alembic, asyncpg, braintrust, fastapi, greenlet, openai, opentelemetry-*,
pinecone, prometheus-fastapi-instrumentator, pydantic-settings, python-dotenv, python-multipart,
sqlmodel, structlog, temporalio, tenacity, twilio, uvicorn[standard]`) plus dev deps (`aiosqlite,
httpx, psycopg2-binary, pytest, pytest-asyncio, pytest-cov, ruff`) is fully cloud-agnostic.

There is no `google-cloud-*`, `kubernetes`, `pulumi`, or render-flavoured library to remove from
`pyproject.toml`. The cleanup is entirely outside `src/`:

### Files and directories to delete

| Path | Reason |
|------|--------|
| `infra/` (entire directory) | Pulumi IaC for GKE — replaced by docker-compose.prod.yml |
| `infra/Pulumi.{dev,staging,prod}.yaml` | GCP project configs |
| `infra/components/` | Pulumi component classes for GKE/Cloud SQL |
| `infra/pyproject.toml`, `infra/uv.lock`, `infra/requirements.txt` | Separate Pulumi venv |
| `infra/DOMAIN-SETUP.md`, `infra/OPERATIONS.md` | GKE-specific runbooks (port to a generic `OPERATIONS.md` at repo root if any content is salvageable) |
| `helm/` (if present — confirm) | Temporal Helm chart 0.74.0 customizations |
| `k8s/` (if present — confirm) | K8s manifests, ESO ExternalSecrets, ServiceAccounts |
| `render.yaml` (if present — confirm) | Render.com Blueprint |
| `.planning/workstreams/gks-refactor/` | GKE refactor workstream history — keep for reference; do **not** delete (audit trail) |

> Per `STATE.md`, the gks-refactor workstream produced these directories. The Phase 03 decisions
> ("Auth Proxy TCP mode for schema Job", "server.sidecarContainers for Helm release",
> "numHistoryShards=512 permanent") confirm `helm/` and Pulumi-driven K8s manifests existed.
> Confirm with `find . -maxdepth 3 -type d -name 'helm' -o -name 'k8s' -o -name 'render.yaml'`
> before the delete commit.

### Compose services to remove

| Service | Reason | Replaces with |
|---------|--------|---------------|
| `opensearch` | Replaced by Postgres visibility | nothing (deleted) |
| `.env.opensearch`, `.env.opensearch.example` | Service deletion | nothing |
| Cloud SQL Auth Proxy sidecar (k8s only) | GKE-specific, never in compose | n/a |
| ESO `ExternalSecret` / `SecretStore` manifests | GKE-only | Compose `secrets:` + SOPS |

### Compose services to keep, modified

| Service | Modification |
|---------|--------------|
| `postgres` | Add a startup script or init SQL to create three databases: `vici`, `temporal`, `temporal_visibility` (currently only `vici` via `.env.postgres`). Use `/docker-entrypoint-initdb.d/init.sql`. |
| `temporal` | Switch to `auto-setup:1.31.0`; env vars `DB=postgres12`, `ENABLE_ES=false`, `VISIBILITY_DBNAME=temporal_visibility`. |
| `jaeger-collector` / `jaeger-query` | Switch storage backend from OpenSearch to Badger (single binary) or memory. |
| `app` | Add `secrets_dir=/run/secrets` mount; mount mTLS certs for prod profile only. |
| `prometheus`, `grafana`, `temporal-ui` | No change. |

### Compose services to add

| Service | Profile | Purpose |
|---------|---------|---------|
| `app-migrate` | `default` (prod) | One-shot Alembic upgrade. Currently the dev `app` runs `uv run alembic upgrade head && uvicorn ...` inline — split for prod clarity. |
| `temporal-admin-tools` | `tools` (opt-in) | Manual schema setup/upgrade for self-host fallback (won't run by default). |

---

## Recommended Stack (v1.1 additions only)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| temporalio Python SDK | `>=1.27.0,<2.0.0` | Bumped pin (was `>=1.24.0`) | mTLS support stable; OTel for standalone activities; future-proofs Cloud connect API |
| Temporal Server (auto-setup image) | `temporalio/auto-setup:1.31.0` | Local dev visibility migration | Bumped from 1.26.2; native Postgres advanced visibility |
| Temporal admin-tools (image) | `temporalio/admin-tools:1.31.0` | One-shot schema migration (`tools` profile) | Production fallback path |
| Docker Compose | CLI v5.1.3+ | Production orchestration | Compose Spec v5.0 "Mont Blanc" features |
| SOPS | v3.9+ | Git-encrypted secrets | Replaces ESO; cloud-agnostic |
| age | v1.2+ | SOPS encryption backend | Modern, simple, no GPG keyring |

### Operator/CI tooling (not Python deps)

| Tool | Version | Purpose |
|------|---------|---------|
| sops | 3.9+ | secret encrypt/decrypt at deploy |
| age | 1.2+ | encryption keys |
| docker | 26.x+ | container runtime |
| docker compose | v5.1.3+ | orchestration |
| yamllint | 1.35+ | compose file linting in CI |
| hadolint | 2.x | Dockerfile linting in CI |

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Temporal hosting (prod) | **Temporal Cloud** (mTLS) | Self-host with `auto-setup` in prod | Auto-setup is documented as **dev/test only**. Self-hosted prod requires running Frontend/History/Matching/Worker as separate services with cluster config — out of scope for v1.1 "deploy anywhere" goal. Defer to v1.2+ if Cloud cost becomes a concern. |
| Temporal visibility (dev) | **Postgres advanced visibility** | OpenSearch / Elasticsearch | Already established as a goal; Postgres is supported on v1.20+ and our scale fits well within SQL visibility's performance envelope. |
| Secrets at rest | **SOPS + age** | HashiCorp Vault | Vault requires a server, auth strategy, sealing/unsealing — too much for one-app, one-environment v1.1. Migrate later if multi-tenant needs emerge. |
| Secrets at rest | **SOPS + age** | Doppler / Infisical | SaaS lock-in re-introduces a network dependency at deploy time, conflicting with "deploy anywhere" goal. |
| Compose features | **Compose Spec v5 native** | Docker Swarm | Swarm adds an orchestrator we don't need (FastAPI scales fine with a single container per host for v1; reverse-proxy/LB sits outside compose). |
| Compose secrets | **`secrets:` file source** | `env_file:` only | Files mounted at `/run/secrets/` aren't visible to `docker inspect`/process env — significantly better posture. |
| Migration job | **Separate `app-migrate` service** | Run migrations in `app` startup CMD | Inline migrations couple deploy + schema, prevent rolling deploys, make rollback ambiguous. Separate one-shot service makes the schema state explicit. |
| Jaeger storage (dev) | **Badger (file)** | Memory | Memory loses traces on restart; Badger is single-file, persists across `down`/`up`. |

---

## Installation / Setup Diff

```bash
# pyproject.toml — single-line change
- "temporalio>=1.24.0",
+ "temporalio>=1.27.0,<2.0.0",

# CI dependencies (.github/workflows/ci.yml)
+ - run: |
+     curl -L https://github.com/getsops/sops/releases/download/v3.10.0/sops-v3.10.0.linux.amd64 -o /usr/local/bin/sops
+     chmod +x /usr/local/bin/sops
+ - run: docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet

# Operator local install (one-time)
$ brew install sops age   # macOS
$ apt install age && curl -L .../sops.deb && sudo dpkg -i sops.deb   # Debian/Ubuntu
```

---

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Temporal Python SDK Cloud connect API | HIGH | Verified via Context7 `/websites/python_temporal_io` (TLSConfig, Client.connect signature); cross-checked against [docs.temporal.io samples](https://github.com/temporalio/documentation) |
| Temporal SDK version (1.27.0) | HIGH | Verified via PyPI + GH releases (current as of 2026-04-30) |
| Postgres advanced visibility support | HIGH | [docs.temporal.io/self-hosted-guide/visibility](https://docs.temporal.io/self-hosted-guide/visibility); auto-setup.sh source code; not deprecated as of v1.31.0 |
| auto-setup env vars | HIGH | Read directly from [auto-setup.sh](https://github.com/temporalio/docker-builds/blob/main/docker/auto-setup.sh) |
| Compose Spec v5 features | HIGH | Context7 `/docker/docs` + GH releases (v5.1.3 latest 2026-04-15) |
| Compose `secrets:` semantics | HIGH | Context7 `/docker/docs` `use-secrets.md`; multiple official examples |
| Compose `deploy.resources.limits` honoured outside Swarm | MEDIUM | Verified resolved in [docker/compose#7307](https://github.com/docker/compose/issues/7307); behaviour is current but historically had ambiguity — recommend belt-and-suspenders top-level `mem_limit`/`cpus` for safety |
| SOPS + age idiom for compose | MEDIUM | Multiple recent (2025–2026) blog posts converge on the pattern; not Docker-official-blessed but widely adopted |
| Pydantic Settings `secrets_dir` reads `/run/secrets` | HIGH | [pydantic-settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/#secrets) |
| Removable files audit | HIGH for `infra/`, `.env.opensearch*`; MEDIUM for `helm/` / `k8s/` / `render.yaml` (need filesystem confirmation in implementation phase) |

---

## Sources

### Primary (Context7 — HIGH confidence)
- `/websites/python_temporal_io` — `temporalio.client.Client.connect`, `TLSConfig` API surface
- `/temporalio/documentation` — Cloud connect samples, visibility configuration, env var contract
- `/docker/docs` — `compose_config.md`, `use-secrets.md`, `compose secrets` patterns
- `/docker/compose` — release notes, v5 spec features

### Secondary (verified releases — HIGH confidence)
- [temporalio/sdk-python releases](https://github.com/temporalio/sdk-python/releases) — 1.27.0 (2026-04-30)
- [temporalio/temporal releases](https://github.com/temporalio/temporal/releases) — v1.31.0 (2026-04-29)
- [docker/compose releases](https://github.com/docker/compose/releases) — v5.1.3 (2026-04-15), v5.0.0 "Mont Blanc" (2025-12-02)
- [temporalio/auto-setup Docker Hub](https://hub.docker.com/r/temporalio/auto-setup) — 1.28.4 listed; 1.31.0 confirmed via temporal/server tag
- [temporalio/docker-builds auto-setup.sh](https://github.com/temporalio/docker-builds/blob/main/docker/auto-setup.sh) — env var enumeration

### Tertiary (community / best-practice — MEDIUM confidence)
- [Self-hosted Visibility setup](https://docs.temporal.io/self-hosted-guide/visibility) — Postgres v12+ schema commands
- [Compose Deploy Specification](https://docs.docker.com/reference/compose-file/deploy/) — resources.limits semantics
- [SOPS official repo](https://github.com/getsops/sops) — encryption tool
- [10 Lines to Better Docker Compose Secrets (Dec 2025)](https://phoenixtrap.com/2025/12/22/10-lines-to-better-docker-compose-secrets/) — env-from-secrets pattern
- [Secrets management in Docker Compose (Stackademic Mar 2026)](https://blog.stackademic.com/secrets-management-in-docker-compose-env-sops-bitwarden-and-the-good-enough-threat-model-2bbc6d8e1064) — threat-model framing
- [docker/compose#7307](https://github.com/docker/compose/issues/7307) — resource limits non-Swarm support history
- [GitHub changelog 2026-01-30](https://github.blog/changelog/2026-01-30-docker-and-docker-compose-version-upgrades-on-hosted-runners/) — runner Compose v2 default
