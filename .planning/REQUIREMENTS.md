# Vici — Requirements

**Current milestone:** v1.1 De-platform — Docker-Only Base
**Generated:** 2026-03-05 (v1.0); 2026-05-01 (v1.1)
**Status:** v1.0 validated (Phases 01–03 complete, Phase 04 deferred); v1.1 active

---

## v1.1 Requirements

### Infrastructure Cleanup (INFRA)

- [ ] **INFRA-01**: All GCP/GKE artifacts are removed from the repository: `infra/` (Pulumi), `helm/`, `k8s/`, External Secrets Operator manifests, `render.yaml`, `Pulumi.*.yaml`, `cd-*.yml` GitHub Actions workflows, `.env.opensearch*`
- [ ] **INFRA-02**: A repo-wide search for GCP/GKE/Pulumi/Helm/Cloud SQL/ESO/Render references (`rg -i 'gke|gcp|helm|pulumi|cloud_sql|external-secret|render\.yaml'`) returns clean — no orphan references in code, compose files, env templates, scripts, or docs
- [ ] **INFRA-03**: A documented runbook exists for the GCP teardown sequence: `pulumi stack export > backup-state.json` → `pulumi destroy` returns clean exit on every stack → GCP console audit confirms zero recurring charges → only then delete Pulumi state files. Runbook lives in `docs/RUNBOOK-gcp-teardown.md` (or equivalent)
- [ ] **INFRA-04**: The `gks-refactor` workstream artifacts are removed (`.planning/workstreams/gks-refactor/` archived to `.planning/milestones/v1.0-gks-refactor/` and the active workstream pointer cleared)

### Compose Stack (COMPOSE)

- [ ] **COMPOSE-01**: Compose stack uses a 3-file overlay model — `docker-compose.yml` (base, environment-neutral) + `docker-compose.override.yml` (dev, auto-loaded by `docker compose up`) + `docker-compose.prod.yml` (prod, used via explicit `-f` flag). No `profiles:` is used for the environment split.
- [ ] **COMPOSE-02**: Production overlay sets, for every long-running service: `restart: unless-stopped`, a healthcheck plus `depends_on: { <upstream>: { condition: service_healthy } }`, a named volume for every stateful path, a pinned image digest (or SHA-tagged GHCR image — see CI-02), and resource limits (`deploy.resources.limits` plus `mem_limit`/`cpus` belt-and-suspenders for non-Swarm)
- [ ] **COMPOSE-03**: Production overlay binds all non-public service ports to `127.0.0.1:` (not `0.0.0.0`); the only public-bound ports are the app's HTTP listener (and optionally Temporal UI, behind a documented warning + opt-in env flag)
- [ ] **COMPOSE-04**: The `postgres` service in the base compose file has a named volume (`postgres_data`) so `docker compose down` does not wipe data
- [ ] **COMPOSE-05**: A separate one-shot `app-migrate` service runs `alembic upgrade head` and exits; the long-running `app` service depends on it via `service_completed_successfully`. Migration is no longer inline in the app's `command:`.
- [ ] **COMPOSE-06**: Production overlay configures the JSON-file logging driver with rotation (`max-size`, `max-file`) for every service

### Temporal (TEMPORAL)

- [ ] **TEMPORAL-01**: Self-hosted Temporal server remains the deployment target for both dev and prod (Temporal Cloud is explicitly out of scope for this milestone)
- [ ] **TEMPORAL-02**: Temporal `auto-setup` image is bumped to `temporalio/auto-setup:1.31.0`; Temporal Server v1.31+ runs against Postgres-only visibility
- [ ] **TEMPORAL-03**: OpenSearch is removed from the compose stack entirely; Temporal uses Postgres advanced visibility (`ENABLE_ES=false`, `VISIBILITY_DBNAME=temporal_visibility`, `DB=postgres12`)
- [ ] **TEMPORAL-04**: Temporal's three logical databases (`temporal`, `temporal_visibility`, plus app's `vici`) are provisioned in the single shared `postgres` service via init scripts; no second Postgres instance is added

### Observability (OBS)

- [ ] **OBS-05**: Prometheus, Grafana, and Jaeger services are removed from `docker-compose.yml`. The repo no longer ships any observability container.
- [ ] **OBS-06**: App OTel exporter defaults to a console (stdout) span exporter when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, allowing `docker compose logs app` to surface trace data without a wired backend. When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, the OTLP exporter is used and the console exporter is bypassed.
- [ ] **OBS-07**: structlog continues to emit JSON logs to stdout for every inbound message and outbound reply; no separate file driver beyond Docker's default
- [ ] **OBS-08**: The `/metrics` Prometheus endpoint stays exposed on the app for any external scraper an operator wires up; the app does not require Prometheus to be present
- [ ] **OBS-09**: v1.0 OBS-02 (Prometheus + Grafana auto-provisioning in compose) and OBS-03 (Jaeger v2 backend) are explicitly superseded by OBS-05/06/07/08; obsolete config files (Grafana provisioning, Prometheus rules, jaeger collector configs) are deleted alongside the services

### Secrets (SECRETS)

- [ ] **SECRETS-01**: Production overlay uses Compose-native `secrets:` (file source) for all sensitive credentials: DB password, OpenAI API key, Pinecone API key, Twilio account SID + auth token, Twilio request validation token, Braintrust API key
- [ ] **SECRETS-02**: Pydantic Settings reads secret values from `/run/secrets/` via `secrets_dir=` configuration; existing flat-env paths still work for local-dev convenience
- [ ] **SECRETS-03**: Secret files are stored encrypted at rest in the repo via SOPS + age; `.sops.yaml` defines encryption rules; documented operator command (e.g. `make decrypt-secrets`) decrypts to `secrets/` directory at deploy time
- [ ] **SECRETS-04**: Obsolete `grafana_admin_password = "admin"` literal default is removed from `src/config.py`; any other secret defaults that are unsafe to ship are removed

### CI / Image Distribution (CI)

- [ ] **CI-01**: A GitHub Actions workflow (`release.yml`) builds multi-arch Docker images (linux/amd64 + linux/arm64) via `docker/build-push-action@v5` with QEMU + buildx, and pushes to GHCR (`ghcr.io/<org>/vici`) on `main` push and on tag
- [ ] **CI-02**: Published images are tagged with the short commit SHA (`sha-<short>`); `:latest` is not used; production overlay references `image: ghcr.io/<org>/vici:sha-${GIT_SHA}`
- [ ] **CI-03**: A GitHub Actions step validates compose files on every push: `docker compose -f docker-compose.yml config --quiet` AND `docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` — non-zero exit fails the build
- [ ] **CI-04**: Existing GKE-targeted CI workflows (`cd-*.yml`) are deleted as part of INFRA-01

---

## Future Requirements (deferred from v1.1)

- **SBOM + provenance attestations** for GHCR images (`--sbom=true`, `--provenance=mode=max`) — captured as `.planning/todos/pending/260501-sbom-provenance-attestations.md`
- **Reverse proxy** (Caddy or Traefik) in front of the compose stack with automatic Let's Encrypt — operator concern for now
- **Loki + Promtail** for centralized log aggregation
- **OTel Collector** intermediary in compose for routing/sampling
- **Cosign image signing** for supply-chain hardening beyond SBOM
- **Schedule API migration** in Temporal (current cron-on-`start_workflow` works; not blocking)
- **v1.0 Phase 04**: outbound SMS confirmation for job posters (STR-03), ranked SMS reply for workers (MATCH-02 / MATCH-03), STOP/START pass-through (SEC-05), full pipeline ASYNC-02 — deferred to a future product milestone

---

## Out of Scope (v1.1 and beyond — project-level)

- **Kubernetes / Helm / any orchestrator beyond plain Docker** — Docker is the deployment ceiling for the foreseeable future
- **Cloud-provider-specific IaC** (Pulumi/Terraform tied to a single cloud) — repo stays provider-neutral
- **Temporal Cloud** — self-hosted Temporal in compose is the canonical path; revisit only if operational burden becomes acute
- **Bundled observability UIs** (Prometheus, Grafana, Jaeger dashboards) — operators wire their own backend (Grafana Cloud, Honeycomb, Datadog, etc.) using the OTel exporter and `/metrics` endpoint
- **Render.com Blueprint** — superseded by the Docker-only base
- **External Secrets Operator** — replaced by compose `secrets:` + SOPS+age

---

## Inherited from v1.0 (validated, see PROJECT.md)

The v1.0 product surface is shipped and validated: SEC-01..04, IDN-01..02, EXT-01..04, STR-01..02, VEC-01, MATCH-01, OBS-01, OBS-04, ASYNC-01, ASYNC-03, DEP-01, DEP-02, PROD-01..08, DOC-README. v1.0 OBS-02/03 are explicitly superseded by v1.1 OBS-05..09 (observability containers removed). v1.0 DEP-01 (8-service compose) is superseded by v1.1 COMPOSE-01..06 (3-file overlay, ~5 services). v1.0 DEP-03 / PROD-04 (render.yaml) are superseded by v1.1 INFRA-01.

---

## Requirement Traceability

Every v1.1 requirement is mapped to exactly one phase. Coverage: 27/27 (100%) — no orphans.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 9 | Pending |
| INFRA-02 | Phase 9 | Pending |
| INFRA-03 | Phase 9 | Pending |
| INFRA-04 | Phase 9 | Pending |
| COMPOSE-01 | Phase 6 | Pending |
| COMPOSE-02 | Phase 6 | Pending |
| COMPOSE-03 | Phase 6 | Pending |
| COMPOSE-04 | Phase 6 | Pending |
| COMPOSE-05 | Phase 6 | Pending |
| COMPOSE-06 | Phase 6 | Pending |
| TEMPORAL-01 | Phase 8 | Pending |
| TEMPORAL-02 | Phase 8 | Pending |
| TEMPORAL-03 | Phase 8 | Pending |
| TEMPORAL-04 | Phase 8 | Pending |
| OBS-05 | Phase 8 | Pending |
| OBS-06 | Phase 8 | Pending |
| OBS-07 | Phase 8 | Pending |
| OBS-08 | Phase 8 | Pending |
| OBS-09 | Phase 8 | Pending |
| SECRETS-01 | Phase 7 | Pending |
| SECRETS-02 | Phase 7 | Pending |
| SECRETS-03 | Phase 7 | Pending |
| SECRETS-04 | Phase 7 | Pending |
| CI-01 | Phase 5 | Pending |
| CI-02 | Phase 5 | Pending |
| CI-03 | Phase 5 | Pending |
| CI-04 | Phase 5 | Pending |

### Coverage by Phase

| Phase | Requirements | Count |
|-------|--------------|-------|
| Phase 5 — GHCR Image Distribution & CI Validation | CI-01, CI-02, CI-03, CI-04 | 4 |
| Phase 6 — 3-File Compose Overlay & Production Hardening | COMPOSE-01, COMPOSE-02, COMPOSE-03, COMPOSE-04, COMPOSE-05, COMPOSE-06 | 6 |
| Phase 7 — Compose-Native Secrets via SOPS + age | SECRETS-01, SECRETS-02, SECRETS-03, SECRETS-04 | 4 |
| Phase 8 — Temporal Postgres Visibility + Observability Container Removal | TEMPORAL-01, TEMPORAL-02, TEMPORAL-03, TEMPORAL-04, OBS-05, OBS-06, OBS-07, OBS-08, OBS-09 | 9 |
| Phase 9 — GKE/GCP/Pulumi/Helm/ESO/Render Cleanup | INFRA-01, INFRA-02, INFRA-03, INFRA-04 | 4 |
| **Total** | | **27** |

**Notes:**
- Phase 8 intentionally couples Temporal (TEMPORAL-01..04) and observability removal (OBS-05..09) because removing OpenSearch + bumping Temporal `auto-setup` + dropping the bundled observability containers + reconfiguring the OTel exporter all touch the same compose services in the same edit pass; splitting them would create cross-cutting partial states.
- Phase 9 is the cleanup phase and runs **last by mandate** (per user instruction and PITFALL-14 — `pulumi destroy` clean-exit is a hard gate before any Pulumi state file deletion).
- Phase 5 (CI/Image distribution) is sequenced first because it is independent and produces the SHA-tagged GHCR images that Phase 6's prod overlay references via `image:`.
- Temporal Cloud was rejected by the user; no phase exists for it. Self-hosted Temporal in compose stays.
- Bundled observability UIs (Prometheus/Grafana/Jaeger) were rejected by the user for prod; OBS-05..09 cover their removal and the OTel console-exporter fallback.
- SBOM + provenance attestations were deferred (see `.planning/todos/pending/260501-sbom-provenance-attestations.md`); no phase covers them in v1.1.
