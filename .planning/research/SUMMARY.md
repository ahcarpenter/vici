# Project Research Summary — v1.1 De-platform (Docker-Only Base)

**Project:** Vici — milestone v1.1
**Domain:** De-platforming a working SMS/AI/Temporal FastAPI app from GKE/GCP/ESO/OpenSearch to a hosting-agnostic, Docker-only baseline
**Researched:** 2026-05-01
**Confidence:** HIGH — every claim grounded in current source files (verified via repo reads), official Temporal/Docker/Pulumi/OTel docs, and Context7-fetched library references

> **Scope reminder:** Covers only the v1.1 *de-platform* milestone. The v1.0 product surface (Twilio webhook, classify+extract, MatchService, Pinecone embeddings, Temporal workflows, OTel/Prometheus/structlog) is already built and out of scope.

## Executive Summary

Vici today runs on GKE with Pulumi-driven Helm releases, ESO sourcing GCP Secret Manager, an in-cluster Temporal cluster with OpenSearch as the visibility/Jaeger trace backend, and a Render.com Blueprint as the legacy deploy target. The v1.1 milestone re-baselines this entire surface to a single `docker-compose.prod.yml` artifact that runs on any Docker-capable host. **The application code change is small (~30 lines, mostly in `src/temporal/worker.py` + `src/config.py`). The risk is sequencing.** All four research streams independently converged on the same phase ordering and the same set of "do these last" hard gates.

The recommended approach is a **6-phase incremental cutover with the GKE/Pulumi teardown deferred to the final phase**. Image distribution (GHCR + CI publish) lands first because the prod compose needs an `image:` reference. The compose file split (base + dev override + prod override) lands second to give a deploy target that can be exercised against the existing in-cluster Temporal. The OpenSearch removal lands third — structurally simpler than expected because **the application code has zero direct OpenSearch dependencies** (verified by `grep -r "opensearch\|OpenSearch" src/` returning empty); the cascade is purely infra-config. The Temporal Cloud client integration lands fourth, behind a feature flag (empty `temporal_api_key` is the flag itself). Only after Cloud has run a real workflow successfully does Phase 6 delete `infra/`, `helm/`, `k8s/`, ESO manifests, and the `cd-*.yml` workflows. **The in-cluster Temporal stack must remain a fallback during cutover** — a critical convergence across all four research files.

The dominant risks are operational, not technical. Three deserve top billing: (1) **TLS cert lifecycle becomes invisible** the moment ESO is removed — this is the strongest argument for choosing API-key auth over mTLS for Temporal Cloud. (2) **Pulumi state can be deleted before destroy completes**, leaving GKE/Cloud SQL/LB/static-IP resources accruing cost silently — `pulumi destroy` clean exit is a hard gate before any state deletion. (3) **In-flight `ProcessMessageWorkflow` runs on GKE will be abandoned** at cutover unless an explicit drain (`temporal workflow list --query 'ExecutionStatus="Running"'` returns empty) is performed first. Two latent bugs in the *current* dev compose were also surfaced: postgres has no named volume (a `compose down` wipes data) and `grafana_admin_password: str = "admin"` is the literal default in `src/config.py:80` — combined with naive `0.0.0.0` port binding this exposes Grafana with default creds. Both must be fixed in this milestone before any "deploy anywhere" claim is true.

## Key Findings

### Recommended Stack
Zero new Python production deps. One bumped pin: `temporalio>=1.24.0` → `>=1.27.0,<2.0.0`. Infrastructure surface contracts dramatically — `infra/`, `helm/`, `k8s/` deleted in favor of Compose-Spec-v5 layered files. Operator/CI tooling adds `sops` + `age` for git-encrypted secrets at rest; pydantic-settings already supports `secrets_dir="/run/secrets"` natively for runtime injection.

**Core technologies (additions / changes only):**
- `temporalio` SDK `>=1.27.0,<2.0.0` — bumped pin; mTLS / API-key Cloud connect; OTel for standalone activities
- **Temporal Cloud** (replaces in-cluster Helm chart) — `<namespace>.<account>.tmprl.cloud:7233`; auth method is a phase-level decision (see Gaps)
- `temporalio/auto-setup:1.31.0` — bumped from 1.26.2; `DB=postgres12`, `ENABLE_ES=false`, `VISIBILITY_DBNAME=temporal_visibility` for dev compose Postgres-only path
- **Compose Spec v5.x ("Mont Blanc")** — base + override pattern, native `secrets:`, `pull_policy: always`, image digest pinning
- **GHCR** for image distribution — `image: ghcr.io/<org>/vici:sha-<short>`; never `:latest` in prod
- **SOPS + age** for encrypted-at-rest secrets — single binary per side, git-native diffs, no SaaS lock-in
- **Jaeger v2 single-binary** — collapsed from collector+query split; backend swaps from OpenSearch → Badger (simplest) or Postgres (per-row durable)

**Critical version constraints:** Temporal Server `v1.24+` removed standard visibility (Postgres v12+ advanced visibility is the only supported `auto-setup` path); Compose CLI v2 (Go-native plugin) — v1 is EOL; Postgres 16 (existing) supports advanced visibility natively.

### Expected Features
This is an **infrastructure** milestone. Treat each "feature" as a candidate phase or sub-phase.

**Must have (table stakes — block "production" claim):**
- `docker-compose.prod.yml` with `restart: unless-stopped`, healthchecks + `depends_on: service_healthy`, named volumes for **every** stateful service (postgres named volume currently *missing*), pinned image digests, `127.0.0.1:` bindings for non-public services, `logging` rotation
- Temporal Cloud connection: `Client.connect(addr, namespace=..., tls=..., api_key=...)` with bounded-retry on initial connect
- OpenSearch service deleted; Jaeger backend swapped to Badger (dev) or Postgres (prod); `ENABLE_ES=false` on dev `auto-setup`
- Compose-native `secrets:` block sourced from files (mTLS certs/API key, DB password, OpenAI key, Pinecone key, Twilio token, Grafana admin password); pydantic `secrets_dir` reads them
- Image build + push to GHCR via GitHub Actions (multi-arch amd64+arm64 via buildx)
- Postgres backup + tested restore (replaces Cloud SQL automated backups)

**Should have (differentiators):** SOPS + age for git-encrypted secret files; `app-migrate` separate one-shot service; SBOM + provenance attestations; `temporalio/admin-tools` in a `tools` profile.

**Defer (out of scope):** Schedule API migration (cron-on-`start_workflow` works); reverse proxy w/ TLS (operator's choice); OTel Collector intermediary; Loki+Promtail; Cosign signing; horizontal scaling; custom search attributes / `GROUP BY` beyond `ExecutionStatus`.

**Anti-features:** `temporalio/auto-setup` in prod compose (CI-lint for it); `:latest` tags in prod; `0.0.0.0` host port bindings on internal services (Docker bypasses host iptables — UFW does not protect); default `admin/admin` Grafana; `build: .` on the deploy host; bind-mounting `./src` in prod.

### Architecture Approach
Single Docker host running 5 long-running services (`postgres`, `app`, `jaeger`, `prometheus`, `grafana`) on a single Compose network, with the `app` process embedding the Temporal Worker as a lifespan task (unchanged). External deps: Twilio, OpenAI, Pinecone, Temporal Cloud (latter authenticated over TLS-only gRPC). Production observability lives entirely inside the compose stack. File split is **base + dev `override.yml` + explicit `prod.yml`** — *not* a single file with `profiles:` (rejected anti-pattern).

**Major components:**
1. `docker-compose.yml` (base, committed) — service definitions valid for any environment; no `build:`, no `--reload`, no host-port differences
2. `docker-compose.override.yml` (dev, committed, auto-loaded) — adds `temporal` + `temporal-ui`, `build: .`, `--reload`, source bind mount, exposed ports
3. `docker-compose.prod.yml` (prod, explicit `-f`) — `image: ghcr.io/...:${GIT_SHA}`, `restart: unless-stopped`, env points at Temporal Cloud, narrowed published ports, resource limits, `secrets:` block
4. `src/temporal/worker.py:get_temporal_client` — single function rewrite (~15 lines): accept `TemporalSettings` instead of `address: str`; conditionally pass `namespace=`, `api_key=`, `tls=`
5. `src/config.py:TemporalSettings` — add `namespace`, `api_key` (or cert paths), `tls: bool`; gate validation by `env in ("staging", "production")`
6. New `.github/workflows/release.yml` — `docker buildx build --push` on `main`/tag, multi-arch

### Critical Pitfalls
Top 5 from a 21-item catalog (full details with file:line citations in PITFALLS.md):

1. **`Client.connect` will not authenticate to Temporal Cloud as currently written** — current call has no `namespace=` and no TLS material. Cloud requires both. Add `temporal_namespace` + auth fields to `Settings` and require them when `env != "local"`; add startup self-test (`await client.workflow_service.get_system_info()`).
2. **Pulumi state deleted before `pulumi destroy` returns clean exit** — orphaned GKE/Cloud SQL/LB resources keep accruing cost. Make `pulumi destroy` clean-exit a hard phase gate; tag every Pulumi-created GCP resource with `pulumi-stack=<name>`; `pulumi stack export > backup-state.json` before destroy.
3. **In-flight `ProcessMessageWorkflow` runs abandoned at cutover** — workflow state lives in GKE Temporal Postgres. Pre-cutover drain protocol: pause Twilio webhook → wait for `temporal workflow list --query 'ExecutionStatus="Running"'` empty → final Postgres backup → only then point workers at Cloud and tear down GKE.
4. **Three latent dev-compose bugs compose into one critical issue** — postgres has no named volume + Grafana ships with `admin/admin` (`src/config.py:80`) + ports bind `0.0.0.0`. Fix all three: add `postgres_data` named volume to base; remove the `"admin"` default and require it via `_validate_required_credentials`; bind every non-public port to `127.0.0.1:` explicitly in prod compose.
5. **TLS cert lifecycle becomes invisible** — Temporal Cloud client certs default to 1-year validity; on GKE this was handled by ESO+cert-manager. **Prefer API-key auth over mTLS** (rotates without redeploying cert files); if mTLS, expose `temporal_client_cert_expires_seconds` Prometheus gauge with <30d alert.

## Implications for Roadmap

All four research streams independently converged on the same 6-phase ordering. **Image registry first, compose split second, observability backend swap third, Temporal Cloud client fourth, Pulumi/GKE teardown last.** Phases 1–4 are reversible; Phase 6 is the point of no return.

### Phase 1: Image Distribution & CI Publish
**Rationale:** Prod compose needs an `image:` reference; building on the deploy host is rejected. Independent of Temporal Cloud, no production cutover risk — purely additive. Doing it first means Phases 2–6 can write `image: ghcr.io/...:${GIT_SHA}` from day one.
**Delivers:** `.github/workflows/release.yml` building multi-arch images via buildx, pushing to GHCR with SHA tags + SBOM/provenance attestations.

### Phase 2: Compose Split + Production Manifest Skeleton
**Rationale:** Green-field exercise — does not disturb the running system. Establishes file split, conventions (named volumes, `restart: unless-stopped`, `127.0.0.1:` bindings, pinned digests). Fixes two latent dev-compose bugs surfaced by research.
**Delivers:** Three-file overlay model; CI validation `docker compose config --quiet`; `.dockerignore` audit.
**Latent bug fixes:** `postgres_data` named volume; `127.0.0.1:` port bindings in prod overlay.

### Phase 3: OpenSearch Removal & Observability Backend Swap
**Rationale:** Phase 4 imports a new managed visibility store; debugging "is this OpenSearch or Cloud?" simultaneously is needless complexity. Drop OpenSearch first. Structurally simpler than expected — app code has zero OpenSearch deps. Also fixes the `grafana_admin_password = "admin"` default and adds Prometheus retention flags.
**Delivers:** `opensearch:` deleted; Jaeger v2 single-binary with Badger/Postgres backend; `ENABLE_ES=false` + `VISIBILITY_DBNAME=temporal_visibility`; `prometheus_data` named volume + `--storage.tsdb.retention.{time,size}`; Grafana admin password from compose secret with validation.

### Phase 4: Temporal Cloud Client Integration & Cutover
**Rationale:** Phases 1–3 are prerequisites. Code change is small (~30 lines). Initially merged behind feature flag (empty `temporal_api_key`) so dev still works against in-compose Temporal. Then provision Cloud namespace, populate secrets, perform pre-cutover drain, switch.
**Delivers:** Extended `TemporalSettings`; new `get_temporal_client(temporal: TemporalSettings)` signature; bounded-retry on initial connect; `Worker(identity=f"vici-worker@{settings.git_sha}", ...)`; cert-expiry gauge + alert (if mTLS); pre-cutover drain runbook.
**Hard gate:** Cloud has run a real `ProcessMessageWorkflow` end-to-end before Phase 6 starts.

### Phase 5: Production Postgres Operations (parallel with Phase 4)
**Rationale:** Cloud SQL backups disappear with the platform; backup + tested restore must land in the same phase as the database move. Independent of Phase 4.
**Delivers:** Daily `pg_dump -Fc` cron; off-host retention; tested restore demonstrated; documented RPO; baseline measurement of representative Temporal visibility list-query latency.

### Phase 6: GKE/GCP/Pulumi/Render Demolition
**Rationale:** **Last by mandate, not preference.** Once `infra/` is gone, rollback means git revert + Pulumi state restore — operationally expensive and time-pressured. Phase 4 cutover must have demonstrably succeeded.
**Delivers:** `pulumi destroy` clean exit on each stack; GCP console audit (zero recurring charges); deletion of `infra/`, `cd-*.yml` workflows, `helm/`, `k8s/`, `render.yaml`, ESO manifests, `.env.opensearch*`, Pulumi state files (only after destroy clean exit); `rg -i 'gke|gcp|helm|pulumi|cloud_sql|external-secret|render\.yaml'` returns clean.
**Hard gate:** `pulumi destroy` returns clean exit code before any state deletion.

### Phase Ordering Rationale
- **Phase 1 first** — image registry is independent and unblocks the prod compose's `image:` reference.
- **Phase 2 before Phase 4** — green-field exercise; can be exercised against in-cluster Temporal first.
- **Phase 3 before Phase 4** — Cloud arrives onto a clean substrate (no OpenSearch confusion).
- **Phase 4 before Phase 6** — Phase 6 deletes the only fallback. If Cloud has issues, `pulumi up` against the existing GKE cluster is still possible.
- **Phase 5 in parallel with Phase 4** — disjoint files (Postgres backup tooling vs. Temporal client/config code).
- **Phase 6 last by mandate** — once `infra/` is gone, the path back to GKE is operationally expensive and time-pressured.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 4 (Temporal Cloud cutover):** **Auth choice (mTLS vs API key) is the key open question.** STACK.md leans mTLS (production-standard default). ARCHITECTURE.md leans API key (smaller blast radius, no Dockerfile changes — explicitly: *"one of the meaningful wins of API-key over mTLS: no cert volume mount, no PEM-as-env decoding, no Dockerfile changes"*). PITFALLS.md notes API key is materially less painful for cert rotation. **Decision needed early in this phase.** Recommend `/gsd-research-phase` to surface API-key rate-limit caveats, namespace-per-environment cost implications, and Schedule API migration path before code lands.
- **Phase 3 (Jaeger backend swap):** Jaeger v2 single-binary with Postgres backend is MEDIUM confidence. Worth a feasibility spike to confirm `jaeger/config.yaml` v2 single-binary mode shape with `postgresql` storage extension. Badger fallback is HIGH confidence.

**Phases with standard patterns (skip deeper research):**
- Phase 1 (`docker/build-push-action@v5` + GHCR pattern, multi-arch via `platforms:`)
- Phase 2 (Compose Spec v5 features all HIGH confidence)
- Phase 5 (`pg_dump -Fc` cron is standard)
- Phase 6 (mechanical deletion guided by Pitfall 15 grep checklist)

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Verified via Context7 (`/temporalio/documentation`, `/websites/python_temporal_io`, `/docker/docs`, `/docker/compose`) plus current GitHub releases. One MEDIUM area: SOPS+age compose pattern is community-converged but not Docker-official-blessed. |
| Features | HIGH | Official Docker / Temporal / Jaeger / Grafana / Prometheus docs cross-verified. Anti-features grounded in current dev compose source reads (line numbers cited). |
| Architecture | HIGH | Derived from actual built system (Phases 01–02.5 + gks-refactor Phases 1–5.1) plus Context7-verified Cloud connect samples. One MEDIUM area: Jaeger v2 single-binary postgres backend feasibility — recommend a quick spike in Phase 3. |
| Pitfalls | HIGH | All 21 pitfalls grounded in observable current-source code (file:line citations) AND verified against Temporal/Docker/Pulumi/OTel official docs. |

**Overall confidence:** HIGH — strong cross-stream convergence on phase ordering, hard gates, and the latent-bug list.

### Gaps to Address
- **Auth mode for Temporal Cloud (mTLS vs API key)** — Phase 4 sub-decision needed early. Recommend defaulting to API key per the convergent recommendation across ARCHITECTURE.md and PITFALLS.md (smaller blast radius, no Dockerfile changes, easier rotation).
- **Image registry choice (GHCR vs Docker Hub vs no-registry)** — operator preference; record in Phase 1 plan. GHCR is the lowest-friction default.
- **Reverse proxy in prod compose** — out of scope for v1.1 unless explicitly chosen; document as a "deploy-host responsibility" in `DEPLOY.md`.
- **Jaeger trace store (Postgres vs memory)** — Postgres durable; memory simpler. Phase 3 plan needs a decision before authoring `jaeger/config.yaml`.
- **Migrations: app startup vs one-shot service** — currently inline in `command:`; flag for Phase 2; defer the split to a follow-up if scope requires.
- **Per-environment Temporal Cloud namespace strategy** — record namespace count in Phase 4 plan.
