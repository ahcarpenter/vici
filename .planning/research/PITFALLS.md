# Pitfalls Research

**Domain:** De-platforming a working FastAPI/Temporal app from GKE/GCP to a Docker-only baseline (milestone v1.1)
**Researched:** 2026-05-01
**Confidence:** HIGH (verified against Temporal Cloud docs, Docker docs, Pulumi docs, OTel spec)

This document is scoped to the *deletion + cutover* nature of v1.1. Generic Docker advice is omitted — every pitfall below is specific to either (a) tearing GKE/GCP infra out of a running production system without breaking it, (b) the Temporal Cloud / Postgres-visibility migration, or (c) the new Docker-only production posture taking responsibility for things GKE used to handle (TLS termination, secret distribution, ordering, identity rotation, etc.).

Existing system reference points (validated by reading source):
- `src/temporal/worker.py` — `Client.connect(address, interceptors=[...])` is the only connection call. No `TLSConfig`, no `namespace=` argument. **Will break the moment `address` becomes `*.tmprl.cloud:7233`.**
- `src/temporal/worker.py:start_cron_if_needed` — registers a cron via `client.start_workflow(... cron_schedule=...)` with a fixed workflow ID `sync-pinecone-queue-cron`. Idempotent on `WorkflowAlreadyStartedError` / `ALREADY_EXISTS` *within the same namespace* — does **not** dedupe across the old (GKE) namespace and the new (Cloud) namespace.
- `src/config.py` — `temporal_address` is the only Temporal env var. There is no `temporal_namespace`, no `temporal_tls_cert_path`, no `temporal_tls_key_path`, and no API-key field. `Settings._validate_required_credentials` does not require any TLS material. The current shape is incompatible with Temporal Cloud as written.
- `src/config.py` — `grafana_admin_password: str = "admin"` is the literal default. There is no production override path enforced at startup.
- `docker-compose.yml` — every service exposes ports as `"X:Y"` (binds to `0.0.0.0`). Postgres on `5432`, Temporal gRPC on `7233`, Temporal UI on `8080`, Prometheus on `9090`, Grafana on `3000`, Jaeger Query on `16686`, OpenSearch on `9200`. **All of these will be reachable from the public internet on the deploy host without further intervention.**
- `docker-compose.yml` — uses `image: temporalio/ui:latest` and `image: temporalio/auto-setup:1.26.2` (auto-setup is a dev-only image; documented as not for production by Temporal). `:latest` tag breaks reproducibility.
- `Dockerfile` — `COPY src/ ./src/` happens *after* the venv copy. There is no build-time secret handling today (which is good — keep it that way), and no multi-arch awareness.

---

## Critical Pitfalls

### Pitfall 1: `Client.connect` will not authenticate to Temporal Cloud as currently written

**What goes wrong:**
The first deploy after pointing `TEMPORAL_ADDRESS` at `<namespace>.<account-id>.tmprl.cloud:7233` fails with a TLS handshake error or `UNAUTHENTICATED`. The worker enters a crash loop, no workflows are processed, and the SMS pipeline silently stops. Because `process_message_activity` is invoked by Temporal, the FastAPI process keeps responding 200 to Twilio while no work happens — failures are not user-visible until SLA monitoring fires.

**Why it happens:**
`src/temporal/worker.py:get_temporal_client` currently calls:
```python
return await Client.connect(address, interceptors=[TracingInterceptor(...)])
```
Temporal Cloud requires both:
1. A `namespace="<name>.<account-id>"` argument (Cloud namespace IDs are *always* `<name>.<5+char-account-suffix>`; the suffix is non-optional).
2. `tls=TLSConfig(client_cert=..., client_private_key=...)` for mTLS, **or** `api_key=...` plus `tls=True` for API-key auth (newer auth path).

`src/config.py` has neither `temporal_namespace` nor any TLS material field. The migration is not just a URL swap — it is a connection-shape change.

**How to avoid:**
- Add `temporal_namespace`, `temporal_tls_client_cert_path`, `temporal_tls_client_key_path` (or `temporal_api_key`) to `Settings` and require them in `_validate_required_credentials` when `env != "local"`.
- Update `get_temporal_client` to read cert files at connect time and pass `TLSConfig(client_cert=..., client_private_key=...)` plus `namespace=`.
- Verify connection in a startup self-test: `await client.workflow_service.get_system_info()` — fails fast if creds are wrong.

**Warning signs:**
- Worker logs show `failed to connect to all addresses; last error: UNKNOWN: ipv4:.../...: handshake failed` or `rpc error: code = Unauthenticated`.
- `temporal-ui` (Cloud) shows zero pollers on `vici-queue`.
- Twilio webhook returns 200 but `temporal_workflow_started_total` Prometheus counter stops incrementing.

**Phase to address:** Phase that introduces Temporal Cloud connection (likely first or second phase of v1.1). Must precede any phase that removes the in-cluster Temporal compose service.

---

### Pitfall 2: TLS cert lifecycle is invisible until the cert expires

**What goes wrong:**
Temporal Cloud client certs issued via tcld have a **default 1-year validity** but can be configured shorter. When the cert expires, every worker poll fails simultaneously across all instances. The system was healthy yesterday and is dead today. There is no rolling restart to recover — the cert files on disk are stale.

**Why it happens:**
On GKE this was handled by ESO + cert-manager — automatic rotation, no human intervention. On a Docker-only host, certs are static files mounted into the container (typically via `docker compose secrets:` or a bind mount). Nobody owns rotation. There is no Prometheus alert on cert expiry because no one wired one up.

**How to avoid:**
- Treat the cert as a managed artifact: store its expiry date in a Prometheus gauge exposed by the app (`temporal_client_cert_expires_seconds`) and alert at <30 days.
- Document a rotation runbook *before* the first deploy: `tcld ca generate ... --validity 365`, copy to host secret store, `docker compose up -d --no-deps app` to reload.
- Prefer the API-key auth path if available — Temporal Cloud API keys can be rotated without redeploying cert files.
- Use Docker secrets (file-mounted at `/run/secrets/temporal_cert`) rather than env vars so the file mtime is observable.

**Warning signs:**
- Cert expiry gauge approaching threshold.
- Sudden cluster-wide `tls: certificate has expired or is not yet valid` from all worker replicas at once.

**Phase to address:** Phase that introduces Temporal Cloud connection. The cert-expiry metric and runbook must land in the same phase as the connection change — not a follow-up.

---

### Pitfall 3: Cron registration creates a duplicate cron in the new Cloud namespace

**What goes wrong:**
After cutover, both the old GKE Temporal cluster and the new Temporal Cloud namespace have a registered `sync-pinecone-queue-cron` workflow. If the GKE Temporal cluster is not torn down first, both crons fire every 5 minutes against the same Postgres `pinecone_sync_queue` table. The activity is idempotent per-row, but workers in *both* clusters compete for the same rows: one Cloud worker, one GKE worker (until torn down). Result is double-work on every tick and noisy logs that look like contention bugs.

**Why it happens:**
`start_cron_if_needed` catches `WorkflowAlreadyStartedError` and `ALREADY_EXISTS`, but those checks are namespace-local. A workflow with the same ID in a *different* namespace is a different workflow. There is no global registry.

**How to avoid:**
- **Strict ordering:** Fully drain and stop the old GKE Temporal cluster before pointing workers at Cloud. Do not run both in parallel except during an explicit dual-run migration window.
- If a dual-run is needed, change the new cron's workflow ID (`sync-pinecone-queue-cron-cloud`) so logs distinguish them, and plan to clean up the legacy ID after cutover.
- After cutover, run `temporal workflow list --query "WorkflowId='sync-pinecone-queue-cron'"` in Cloud and verify exactly one running workflow.

**Warning signs:**
- `pinecone_sync_attempt_total` counter rate doubles after cutover.
- Two distinct worker identities show up in pollers list for the same task queue.
- Logs show two simultaneous activity attempts for the same `pinecone_sync_queue.id` row separated by milliseconds.

**Phase to address:** Phase that performs the GKE Temporal teardown — must require explicit drain confirmation as a success criterion.

---

### Pitfall 4: In-flight workflows on the GKE cluster are abandoned at cutover

**What goes wrong:**
At cutover, any `ProcessMessageWorkflow` that has been retrying (4 attempts with exponential backoff means up to ~30s of wall time per message at minimum, longer with backoff) is mid-execution on the GKE Temporal cluster. If you point workers at Cloud and then tear down GKE, those workflows simply stop. The on-failure activity (`handle_process_message_failure_activity`) never fires because the workflow never reaches the failure branch — the cluster died first. The user's SMS is acknowledged (200 to Twilio) but never processed. Audit log row exists; `Job` / `WorkGoal` row never appears.

**Why it happens:**
Workflow state lives in the cluster's database (the in-cluster Temporal's Postgres in the GKE deploy). Workers don't carry state. Stopping the cluster mid-execution evaporates the runs. The webhook side already wrote the Message and committed — Twilio sees success — so there is no replay path.

**How to avoid:**
- **Drain protocol** before tearing down GKE Temporal:
  1. Stop accepting new SMS at the LB (or pause the Twilio webhook).
  2. Wait for `temporal workflow list --query 'ExecutionStatus="Running" AND WorkflowType="ProcessMessageWorkflow"'` to return empty.
  3. Take a final backup of the Temporal Postgres (in case of disputes about specific message IDs).
  4. Only then point workers at Cloud and tear down GKE.
- For longer-running workflows (the cron), `terminate` it explicitly on the old cluster after confirming it is re-registered on Cloud.
- The drain takes seconds for `ProcessMessageWorkflow` (these are short-lived) but the design must still make it explicit.

**Warning signs:**
- Audit log entries with no corresponding row in `jobs` or `work_goals` for the same `message_id`, dated around cutover.
- `process_message_workflow_completed_total` counter shows a gap during cutover that does not match the Twilio inbound rate.

**Phase to address:** Cutover phase. Document a pre-cutover drain checklist in the phase plan, with a verification step (workflow list query returns empty).

---

### Pitfall 5: Custom search attributes on Postgres visibility are namespace-scoped — not global

**What goes wrong:**
Any `temporal workflow list --query "..."` filter that uses a custom search attribute (e.g., `MessageSid="SM123"`, `FromNumber="+1..."`) silently returns empty results, or fails with `search attribute not registered`, after the visibility migration. Existing dashboards or tooling that relied on Elasticsearch-style global search attributes — or that were copy-pasted from Temporal docs assuming ES — break.

**Why it happens:**
Per Temporal docs (verified): **on Elasticsearch/OpenSearch, custom search attributes are global across all namespaces. On PostgreSQL/MySQL/SQLite (with Temporal v1.20+), custom search attributes are namespace-scoped** and must be explicitly registered per namespace via `temporal operator search-attribute create --namespace <ns> --name <name> --type <type>`. Furthermore, **dual-visibility migration is not supported for ES → Postgres** per Temporal docs — so there is no in-place migration path for historical search-attribute data on running workflows.

**How to avoid:**
- Audit current search-attribute usage: `grep -r "search_attributes" src/` — confirm whether the app code sets any. (Reading `src/temporal/workflows.py`: it does **not** set custom search attributes, so we are not actively dependent on them. This is good news — the migration risk is lower than feared.)
- For *future* attributes (and any tooling/runbooks that reference them), register them per-namespace at deploy time with a one-shot init script.
- Replace any Temporal UI bookmarks or runbooks built on global ES queries.
- Accept that historical visibility data on closed workflows is not migrated. Closed workflow searchability ends at the cutover line.

**Warning signs:**
- Temporal CLI returns `search attribute X is not registered for this namespace`.
- Temporal UI list filter that worked yesterday now shows zero results with no error.
- `temporal operator search-attribute list --namespace <ns>` shows fewer attributes than expected.

**Phase to address:** Phase that switches Temporal to Postgres visibility. Include a search-attribute registration step keyed off an explicit list.

---

### Pitfall 6: Postgres visibility cannot handle the same query patterns as OpenSearch at scale

**What goes wrong:**
Postgres visibility implements a subset of the search query language. Complex filters that worked on OpenSearch — keyword tokenization, prefix searches, range + text composite filters, `ORDER BY` on multiple fields — are slower or unsupported on Postgres. At low workflow volume (Vici's current scale: SMS-rate-limited at 5/min/user) this is invisible. As volume grows, list queries time out.

**Why it happens:**
Postgres visibility uses `WHERE` clauses on a single `executions_visibility` table. There is no inverted index, no analyzer-based text search, no distributed query planning. Temporal docs explicitly recommend Elasticsearch/OpenSearch for any service handling more than a few executions.

**How to avoid:**
- Keep workflow volume modest. Vici today is well within Postgres visibility's comfort zone (well under 100 workflows/sec sustained).
- Set explicit list-query SLOs: anything slower than 2s in the Temporal UI is a flag to revisit visibility backend choice.
- Index the `executions_visibility` table on the columns used by the cron query (`workflow_type_name`, `start_time`).
- Document the regression boundary: "this works for Vici's traffic profile; revisit at >X workflows/min."

**Warning signs:**
- Temporal UI list pages take >5s to load.
- `pg_stat_statements` shows top queries against `executions_visibility` with high mean exec time.
- `temporal workflow list` CLI calls timeout.

**Phase to address:** Phase that switches to Postgres visibility. Capture a baseline measurement (current workflow count + query time on a representative filter) so future regression is detectable.

---

### Pitfall 7: `temporalio/auto-setup` image is not safe for production use

**What goes wrong:**
The current local-dev compose uses `temporalio/auto-setup:1.26.2`. Carrying this into `docker-compose.prod.yml` would be a critical mistake — `auto-setup` runs migrations and creates a default namespace on every start, has no auth configured by default, and is documented by Temporal as a *development-only* image. (And per the milestone goal, in-cluster Temporal goes away entirely — Temporal Cloud replaces it. But there is real risk during the milestone of someone copy-pasting the dev compose into the prod compose.)

**Why it happens:**
Familiarity bias: the dev compose works, "just copy it." The image name does not contain the word "dev" or any other warning. Helm chart users normally use `temporalio/server` plus `temporalio/admin-tools` separately and run schema setup as a one-shot job — that complexity gets lost in translation.

**How to avoid:**
- The production compose for v1.1 should have **zero in-cluster Temporal services**. The only Temporal-related code path is `Client.connect("<ns>.<id>.tmprl.cloud:7233", ...)`.
- Add a CI lint that fails if `docker-compose.prod.yml` references `temporalio/auto-setup` or any `temporalio/*` server image.
- Remove the dev `temporal` and `temporal-ui` services from the prod compose entirely; if the team wants a UI in prod, point a browser at Temporal Cloud's UI directly.

**Warning signs:**
- `docker-compose.prod.yml` references `temporalio/auto-setup`.
- A `temporal` or `temporal-ui` service block exists in the prod compose.

**Phase to address:** Phase that introduces `docker-compose.prod.yml`. Include a "no in-cluster Temporal services" assertion in the phase's success criteria.

---

### Pitfall 8: `:latest` image tags break reproducibility and silently introduce regressions

**What goes wrong:**
Current dev compose uses `image: temporalio/ui:latest`. If carried forward, a `docker compose pull && docker compose up -d` on Tuesday gets a different image than the one on Monday. A breaking change in the upstream image (e.g., new env var name, default TLS requirement, schema change) causes a production outage with no code change attributable. Rollback is hard because there is no record of which prior tag was running.

**Why it happens:**
`:latest` is convenient during dev and never gets fixed before the prod compose is written. CI typically does not enforce tag pinning.

**How to avoid:**
- Pin every `image:` to a specific tag with digest: `image: grafana/grafana:11.4.0@sha256:<digest>`. The digest pin is what actually guarantees immutability — tags are mutable.
- Pin our app image too: `image: ghcr.io/<org>/vici:<git_sha>` — never `:latest`.
- Add a CI step that greps `docker-compose.prod.yml` for `:latest` and fails the build.
- Pre-pull images on the deploy host before swap: `docker compose pull && docker compose up -d --no-build`.

**Warning signs:**
- Any line in `docker-compose.prod.yml` matching `image: .*:latest` or `image: [^@]*$` (no digest).
- Production behavior change without a corresponding git commit.

**Phase to address:** Phase that introduces `docker-compose.prod.yml`. Pinning is a one-time discipline cheap to land and expensive to retrofit.

---

### Pitfall 9: Compose `secrets:` are not encrypted at rest and `env_file:` leaks into image history if misused

**What goes wrong:**
Two related but distinct mistakes:
1. **`env_file` in build context** — if `.env.app` is in the build context (project root) and the Dockerfile has `COPY . .` or `COPY .env* .`, the secrets land in image layers permanently and ship to whatever registry receives the image. Anyone with image-pull access can extract them.
2. **Compose `secrets:` are plaintext on the host** — Compose's `secrets:` block (file-based) mounts the file at `/run/secrets/<name>` inside the container, which is better than env vars (not visible in `docker inspect`, not in env to child processes), but the **source file on the host is plaintext** and not encrypted. Treating Compose secrets like Swarm/K8s secrets gives a false sense of security.

**Why it happens:**
- The current `Dockerfile` uses `COPY src/ ./src/` (narrow) and `COPY migrations/ ./migrations/` — safe today. The risk is that someone "simplifies" this to `COPY . .` during the de-platforming, which would sweep `.env.*` files in.
- Compose secrets are documented as "secrets" without front-loading the encryption-at-rest caveat.

**How to avoid:**
- Keep Dockerfile `COPY` instructions narrow and explicit. Add `.env*`, `*.pem`, `*.key`, `secrets/`, `.planning/` to `.dockerignore` so even an accidental wide copy excludes them.
- Use Compose `secrets:` for runtime secrets (cert, API keys), backed by host files in a directory with mode `0700`, owned by the deploy user. Document that backups and snapshots of the host include those files.
- Never `RUN echo $SECRET > file` in a Dockerfile — use `RUN --mount=type=secret,id=foo` with BuildKit.
- Add a CI step that runs `docker history <image> --no-trunc` and greps for known secret prefixes (e.g., `sk-`, `Bearer `, `-----BEGIN`).

**Warning signs:**
- `docker history <image>` shows ENV layers containing key-value pairs that look secret-shaped.
- `.env.production` exists in the project root and is not in `.dockerignore`.
- `git log --all -- '.env*'` shows env files were ever committed.

**Phase to address:** Phase that introduces the Docker-only secret distribution path (compose `secrets:` block, removal of ESO). Must precede any phase that puts a real production credential into the deploy.

---

### Pitfall 10: Default `0.0.0.0` port bindings expose internal services to the public internet

**What goes wrong:**
The current dev compose binds every service's port as `"X:Y"`, which is shorthand for `0.0.0.0:X:Y`. On a VPS/EC2/bare-metal deploy host, this means Postgres on `5432`, Prometheus on `9090`, Grafana on `3000`, Jaeger Query on `16686`, the Temporal UI on `8080`, and OpenSearch on `9200` are reachable from any IP that can route to the host. UFW/iptables rules at the OS level **do not protect these ports** because Docker writes its own iptables rules and bypasses them.

**Why it happens:**
The dev compose was written for `localhost` access from the developer's browser; the syntax doesn't change between dev and prod. Operators assume the OS firewall protects them; it doesn't because Docker manipulates iptables directly.

**How to avoid:**
- In `docker-compose.prod.yml`, bind every internal service to `127.0.0.1` explicitly:
  ```yaml
  ports:
    - "127.0.0.1:9090:9090"   # Prometheus
    - "127.0.0.1:3000:3000"   # Grafana
    - "127.0.0.1:16686:16686" # Jaeger UI
  ```
- Better: drop the `ports:` block entirely for services that only need intra-compose access. Postgres should not have a host-side port at all in production — only the `app` service talks to it via the Docker network.
- The only public-facing port should be the reverse proxy (nginx/Caddy) on `:443`. Everything else is `127.0.0.1`-bound, accessed via `ssh -L` for ops or behind the reverse proxy with auth.
- Verify post-deploy: `nmap <public-ip>` from off-host should show only `:443` (and `:80` for ACME).

**Warning signs:**
- `docker compose ps` shows `0.0.0.0:5432->5432/tcp` for Postgres.
- A port scan from outside the host returns more than the expected public surface.
- Grafana login screen reachable on `<host>:3000` from a browser off the host.

**Phase to address:** Phase that introduces `docker-compose.prod.yml`. Add an explicit "all non-public ports bound to 127.0.0.1" success criterion.

---

### Pitfall 11: Grafana ships with `admin/admin` credentials by default

**What goes wrong:**
`src/config.py` has `grafana_admin_password: str = "admin"`. If `.env.production` doesn't override it, Grafana boots with `admin/admin`. Combined with Pitfall 10 (port `3000` bound to `0.0.0.0`), an attacker drives by, logs in as admin, gets datasource access to Prometheus, and can pivot to internal metrics — including any business metrics that leak PII (rare, but possible).

**Why it happens:**
The default is "admin/admin" specifically because Grafana wants to force a first-login password change in interactive setups — but that flow does not run in headless `provisioning/`-driven deploys. So the password stays as the env-supplied default.

**How to avoid:**
- Remove the default value from `grafana_admin_password` and require it via `_validate_required_credentials` when `env != "local"`.
- Generate a 32+ char random password at deploy time, store in compose `secrets:`, mount into Grafana via `GF_SECURITY_ADMIN_PASSWORD__FILE=/run/secrets/grafana_pw` (Grafana supports the `__FILE` suffix natively).
- Set `GF_AUTH_ANONYMOUS_ENABLED=false` and `GF_USERS_ALLOW_SIGN_UP=false` explicitly.
- Combined with Pitfall 10: bind Grafana to `127.0.0.1` so even with weak credentials the attack surface is local-only.

**Warning signs:**
- `.env.production` contains `GRAFANA_ADMIN_PASSWORD=admin` or is missing the var entirely.
- Grafana login from outside the host succeeds with default creds.
- `src/config.py` still has the `"admin"` default in tree.

**Phase to address:** Phase that introduces production observability stack. Make Grafana password mandatory in production env validation.

---

### Pitfall 12: ALWAYS_ON OTel sampler emits every span in production — expensive and known

**What goes wrong:**
Per `PROJECT.md` Key Decisions: "ALWAYS_ON OTel sampler — Unambiguous trace coverage; no parent-based override confusion. Implemented — Phase 02.3." This is a deliberate choice and the rationale is sound for a low-volume SMS app — but it has known scaling cost. As Vici grows, every Temporal workflow start, every activity, every Pinecone call, every OpenAI call generates spans that flow to the Jaeger collector. If Jaeger is backed by self-hosted Postgres (per the v1.1 plan replacing OpenSearch) or by any disk-bound store, span volume grows linearly with traffic and storage fills up silently.

**Why it happens:**
The decision was correct for v1.0's volume profile. The danger is forgetting that the decision was *volume-conditional* and not revisiting it as Vici scales. ALWAYS_ON does not auto-degrade.

**How to avoid:**
- Document the volume threshold at which sampling should switch (e.g., "revisit at >10 workflows/sec sustained").
- Wire a Prometheus alert on Jaeger collector ingestion rate or backing-store disk usage.
- When the threshold is hit, switch to `ParentBased(TraceIdRatioBased(0.1))` — only 10% of root spans are sampled, but parent decisions are inherited, so within-trace causality is preserved.
- Keep the trace backend retention bounded: configure storage TTL (e.g., 7d) so unbounded growth doesn't masquerade as "everything is fine."

**Warning signs:**
- Jaeger backend storage > 80% full.
- Span ingestion rate trending up linearly with traffic with no plateau.
- Trace queries in Jaeger UI taking longer over time.

**Phase to address:** Phase that builds the production observability stack. Even if ALWAYS_ON is kept for v1.1, the alert and the documented threshold must land in the same phase.

---

### Pitfall 13: Prometheus runs out of disk silently with no retention configured

**What goes wrong:**
Prometheus's default retention is **15 days**, but storage is unbounded by size. On a host with limited disk, the TSDB can fill the volume; on the same volume Postgres lives, Postgres then fails to write WAL and the app starts erroring on every transaction. Single-disk failure → cascading outage that looks like a database problem but is actually a metrics-storage problem.

**Why it happens:**
Defaults are written for deployments with dedicated storage. Single-host compose deploys typically share one volume. The metrics service is "infrastructure" — invisible until it fails.

**How to avoid:**
- Set explicit retention flags on Prometheus:
  ```yaml
  command:
    - --config.file=/etc/prometheus/prometheus.yml
    - --storage.tsdb.retention.time=30d
    - --storage.tsdb.retention.size=10GB
  ```
- Put Prometheus on a named volume separate from the Postgres data volume.
- Alert on `prometheus_tsdb_storage_blocks_bytes` >80% of the configured size limit.
- Alert on host disk usage >85% as a backstop.

**Warning signs:**
- `df -h` on deploy host approaching full on the shared volume.
- Postgres errors `could not write to file "pg_wal/...": No space left on device`.
- Prometheus startup log shows `level=warn msg="Bytes Limit ... is exceeded"`.

**Phase to address:** Phase that builds production observability stack.

---

### Pitfall 14: Pulumi destroy fails partially and the team deletes the state file to "fix it"

**What goes wrong:**
`pulumi destroy` errors out partway through (e.g., a GKE node pool has stuck pods, an orphaned LB, a finalizer on a cluster role). An impatient operator runs `pulumi state delete` or removes the state backend entirely "to start clean." Now Pulumi has no record of the resources that *were* successfully torn down, but more critically, **the resources that failed to destroy are still running in GCP and Pulumi no longer knows about them**. They keep accruing cost, the GKE cluster keeps running, and there's no `pulumi destroy` path to revisit.

**Why it happens:**
Pulumi state is the source of truth Pulumi uses to know what to destroy. Deleting state ≠ deleting cloud resources. The CLI wording around state deletion does not always make the consequences obvious during a frustrated cleanup session.

**How to avoid:**
- **Order of operations:** `pulumi destroy` must complete (no errors, all resources deleted) before deleting any state. If destroy fails, fix the failing resource (manual cleanup of stuck finalizers, force-delete LBs, etc.) and re-run destroy until it returns clean.
- Use `pulumi state delete <urn>` only for individual resources Pulumi mismanages — never wholesale.
- Tag every Pulumi-created GCP resource with `pulumi-stack=<stack-name>` so manual cleanup via `gcloud` is feasible if state is lost.
- Take a `pulumi stack export > backup-state.json` before any destructive operation.
- After destroy, audit GCP console for: GKE clusters, persistent disks, load balancers, static IPs, Cloud SQL instances, NAT gateways, VPC networks, service accounts, secrets in Secret Manager. Each costs money if left.

**Warning signs:**
- GCP billing dashboard shows non-zero charges after the "we destroyed everything" date.
- `gcloud compute instances list`, `gcloud container clusters list`, `gcloud sql instances list` return non-empty.
- `gcloud compute addresses list` shows reserved-but-unused IPs (these accrue charges).

**Phase to address:** Phase that performs GKE/GCP teardown. The phase plan must make "pulumi destroy returns clean exit code" a hard gate before "delete state file" is even allowed.

---

### Pitfall 15: Removing GKE-related code leaves orphaned config, references, and dead env vars

**What goes wrong:**
After deleting `pulumi/`, `helm/`, `k8s/`, and `render.yaml`, references to those paths and to GCP-specific env vars persist scattered through the codebase: GitHub Actions workflows that reference `helm/`, README sections that document a Cloud SQL setup, `.env.example` with Cloud SQL Auth Proxy vars, comments in code that mention GKE, the `Dockerfile` comment "GKE runs migrations as a separate K8s Job before deployment" (line 37), Pulumi-specific imports, and ESO `ExternalSecret` CRD references.

Worse, `src/config.py` may carry env vars that only make sense in the GKE world (Cloud SQL Auth Proxy URL components, ESO secret prefixes, GCP project ID, GCS bucket names for backups). These linger in `Settings`, fail validation differently in different environments, and confuse future readers.

**Why it happens:**
Deletion is hard to do exhaustively. Grep gets some references; semantic refs (e.g., a comment mentioning "GKE Job") miss; tests and CI configs are easy to overlook.

**How to avoid:**
- Build a checklist of search terms BEFORE deleting anything: `gke`, `gcp`, `helm`, `pulumi`, `cloud_sql`, `cloudsql`, `eso`, `external-secrets`, `kubectl`, `kubernetes`, `k8s`, `render.yaml`, `tcld` (if in legacy infra scripts), GCP project IDs, the GKE cluster name.
- After deletion, run `rg -i '<term>'` for each. Every hit must be addressed (kept with justification, removed, or rewritten to be hosting-agnostic).
- Audit `src/config.py` against the *new* env var surface (`.env.example` for v1.1) — every field in `Settings` must correspond to a current concern. Delete dead fields; the codebase will break the imports of anything that referenced them, surfacing the dependencies.
- Update the Dockerfile comment at line 37 — this is documentation that becomes wrong the moment GKE is gone.
- Audit `.github/workflows/*.yml` for any step that runs `helm`, `kubectl`, `gcloud`, or `pulumi`. Delete or rewrite.

**Warning signs:**
- `rg gke` returns matches outside `.planning/` after the deletion phase.
- `Settings` has fields nothing in `src/` reads (orphaned).
- CI fails on missing `helm` or `kubectl` binary on the runner.
- A README link points to a `helm/` or `pulumi/` path that no longer exists.

**Phase to address:** Final cleanup phase of v1.1. Should be a dedicated phase, not an afterthought tacked onto another phase.

---

### Pitfall 16: Building images on the deploy host is slow, painful, and exposes source

**What goes wrong:**
The Dockerfile expects the build context to include `src/`, `migrations/`, `pyproject.toml`, `uv.lock`. Naive deploys do `git pull && docker compose up --build` on the deploy host. This:
- Requires source on the host (security: any compromise gets full source).
- Requires `git` and the build toolchain on the host.
- Takes minutes per build (uv install + slim Python deps).
- Burns deploy-host CPU and memory; can OOM if the host is small.
- Multi-arch builds via QEMU emulation are 5-20x slower than native — actively harmful if the deploy host is ARM and CI is x86 (or vice versa).

**Why it happens:**
"Just pull and rebuild" is the simplest mental model and works in dev. The failure modes only show up at the size of a small VPS, by which point it's late.

**How to avoid:**
- Build images in CI (GitHub Actions, etc.) on x86 runners; push to a registry (`ghcr.io`, ECR, GCR) tagged with the git SHA. The deploy host pulls the prebuilt image. No source on the deploy host.
- For multi-arch, use `docker buildx build --platform linux/amd64,linux/arm64 --push ...` in CI. Use `--platform=$BUILDPLATFORM` in Dockerfile FROM to pin builder stages to native arch (avoids QEMU emulation during builds).
- The deploy compose references `image:` only (no `build:` block in the prod compose). The local-dev compose can keep `build:` for fast iteration.
- Pull is faster than build by orders of magnitude and is reproducible across hosts.

**Warning signs:**
- `docker compose up --build` runs on the deploy host as part of the deploy script.
- Source code is present on the deploy host.
- Deploy time scales with image build time (>1 minute).
- Application source files appear in `docker exec <app> ls -la /app` and were freshly modified.

**Phase to address:** Phase that introduces production CI/build pipeline. Must precede any real production deploy.

---

### Pitfall 17: `.env`, `.env.production` resolution surprises with Compose

**What goes wrong:**
Docker Compose loads `.env` automatically from the directory where the compose command runs. `env_file:` directives load *additional* files. But:
- Variable substitution in the compose file itself (`${FOO}`) reads from `.env` only — not from `env_file:`.
- An `env_file:` block lists files in **lowest-to-highest precedence** order; the *last* file wins on conflicts.
- Setting `--env-file .env.production` on the CLI replaces the default `.env` but does **not** affect `env_file:` blocks.
- Variables already set in the shell environment override file values (this is the most common foot-gun).

The net effect: a deploy script that sets `DATABASE_URL=...` in a CI runner's environment silently overrides whatever is in `.env.production`. Or, two different `env_file:` files set the same key and the operator doesn't realize which one wins.

**Why it happens:**
The precedence chain has six layers (CLI flag, shell env, --env-file flag, .env file, env_file: block, image ENV). Most teams learn one layer and assume the rest is consistent.

**How to avoid:**
- Use **one** mechanism in production. Recommend: `env_file: [.env.production]` per service, and **never** rely on shell env or compose-level `${FOO}` substitution for production values.
- Don't put secrets in `.env*` files at all — use Compose `secrets:` for those (see Pitfall 9).
- After a deploy, verify: `docker compose exec app env | sort` and diff against the expected env. CI can run this check.
- Document the precedence rules in a `DEPLOY.md` with a worked example.

**Warning signs:**
- `docker compose config` (which renders the final compose) shows env values that don't match `.env.production`.
- The same env var appears in multiple `env_file:` files.
- A deploy works on one host and fails on another with the same compose file but different shell env.

**Phase to address:** Phase that introduces `docker-compose.prod.yml` and the `.env.production` discipline.

---

### Pitfall 18: Compose `depends_on: service_healthy` doesn't wait for the worker's actual readiness

**What goes wrong:**
The current compose has the `app` service `depends_on: postgres: service_healthy, temporal: service_healthy`. After the move to Temporal Cloud, the `temporal` dependency goes away — but the new failure mode is that the app starts before it can reach Temporal Cloud (cold DNS, transient network) and the worker's first `Client.connect` fails. With no retry loop, the worker dies and the Docker restart policy kicks in. If the restart policy is `on-failure` (current dev compose has none specified), the container is kept down. If it's `always` or `unless-stopped`, restart loops eat CPU.

**Why it happens:**
`depends_on` only orchestrates startup order on the *same compose stack*. External dependencies (Temporal Cloud, Twilio, OpenAI, Pinecone) are out of compose's scope. The lifespan code in `src/main.py` has no retry around Temporal client connection.

**How to avoid:**
- Add `restart: unless-stopped` to the `app` service in production compose.
- In `get_temporal_client`, wrap `Client.connect` in a bounded retry with exponential backoff for the *initial* connect (e.g., 5 attempts, 2s → 30s), so a transient DNS or network blip doesn't crash the worker.
- Keep the worker's *running* connection separate — once connected, the SDK's gRPC client handles reconnects automatically.
- Add a Prometheus alert for `up{job="vici-app"} == 0` to detect crash loops.

**Warning signs:**
- Container exits with code 1 within seconds of `docker compose up`, restart counter increments.
- Log line `failed to connect to all addresses` from worker startup.
- `docker compose ps` shows app container in `restarting` state.

**Phase to address:** Phase that introduces Temporal Cloud connection (the retry) AND the phase that introduces the prod compose (restart policy).

---

### Pitfall 19: Postgres data volume is not backed up, and a single bad migration loses everything

**What goes wrong:**
On GKE, Cloud SQL gave automated backups, point-in-time recovery, and HA failover. The Docker-only baseline replaces Cloud SQL with `postgres:16` running in a container with a Docker volume. **There is no automatic backup.** A bad migration, a `docker compose down -v` mistake, or host disk failure loses every user, message, job, and audit log.

**Why it happens:**
Cloud SQL backups are invisible — they "just work." When the dependency goes away, the responsibility doesn't get reassigned because nobody noticed they had it.

**How to avoid:**
- Add a `pg_dump` cron container or a host-level cron that runs `docker exec vici-postgres pg_dump -Fc -U vici vici > backup-$(date -I).pgdump` daily, retains 7 days locally and 30 days off-host (S3, B2, etc.).
- Test restore at least once: `pg_restore -d vici_test backup-YYYY-MM-DD.pgdump`. An untested backup is a fiction.
- Use a named Docker volume (not a bind mount in the project dir) for Postgres data so it survives `docker compose down -v` only when explicitly intended.
- Document the RPO (e.g., "we accept up to 24h of data loss") explicitly. If RPO is tighter, set up streaming replication or use a managed Postgres instead.

**Warning signs:**
- No backup files exist on the deploy host or off-host store.
- `docker volume inspect <pg-volume>` shows it was created less recently than the project (suggests the volume was destroyed and recreated, losing data).
- Postgres `pg_stat_database.deadlocks` rising (data integrity proxy).

**Phase to address:** Phase that introduces production Postgres (replacement of Cloud SQL). Backup + tested restore must be in the same phase, not a follow-up.

---

### Pitfall 20: `WorkflowAlreadyStartedError` semantics differ between Temporal Cloud and self-hosted on first deploy

**What goes wrong:**
The current code's cron registration relies on catching `WorkflowAlreadyStartedError` and `RPCError(ALREADY_EXISTS)` to be idempotent. On the first deploy to Temporal Cloud, neither error fires (the namespace is empty), so the cron registers fine. Subsequent deploys hit the catch path and pass. **However**, if the team manually terminates the cron in Temporal Cloud UI ("oops, wrong schedule") and redeploys without changing the workflow ID, the start_workflow call hits `Workflow with id ... is already running` because terminated workflows occupy the ID for the namespace's retention period (default 30 days for Cloud namespaces). The current code's catch path passes silently, but the cron is *not* actually re-registered with a new schedule.

**Why it happens:**
Temporal's workflow ID semantics interact with retention period and `WorkflowIdReusePolicy`. The current code uses defaults (`AllowDuplicate` is a per-call setting; without specifying, Cloud defaults often mean "reject duplicate while running"). Catching the error masks the case where the cron *should* have been updated but wasn't.

**How to avoid:**
- For schedule changes, use Temporal's first-class **Schedule API** (`Client.create_schedule`) rather than `start_workflow(... cron_schedule=...)`. Schedules are first-class objects with update semantics.
- If staying with cron-on-start_workflow, when changing the schedule, terminate the existing workflow AND wait for retention to expire OR change the workflow ID.
- Log the cron schedule that was actually registered (read it back from the API after register) so config drift is observable.

**Warning signs:**
- `pinecone_sync_attempt_total` rate doesn't change after a deploy that "changed the cron schedule."
- Two cron workflows with similar IDs visible in Temporal Cloud UI.
- The cron schedule shown in Temporal Cloud UI doesn't match `settings.temporal.cron_schedule_pinecone_sync`.

**Phase to address:** Phase that introduces Temporal Cloud connection. Migrate to Schedule API in the same phase if possible.

---

### Pitfall 21: Worker identity changes break sticky workflow optimization (cosmetic but confusing)

**What goes wrong:**
Sticky execution — Temporal's perf optimization that routes a workflow's tasks back to the worker that last handled it — depends on worker identity. The Temporal Python SDK sets a default worker identity from `<pid>@<hostname>`. In compose, hostnames are container IDs (random hex). Every `docker compose up` produces a new identity. After a deploy, every running workflow's sticky-cache entry is stale, the next task goes to a non-sticky worker, and there's a brief latency bump.

This is *not* a correctness issue — Temporal handles non-sticky correctly — but it shows up as "every deploy causes a 1-second latency spike across all in-flight workflows," and confuses ops.

**Why it happens:**
Sticky cache is designed to survive *normal* worker churn but not whole-fleet replacements. The cache TTL is short (default ~30s), so sticky-after-deploy is a transient effect.

**How to avoid:**
- Set an explicit, stable worker identity that includes deploy version: `Worker(client, identity=f"vici-worker@{settings.git_sha}", ...)`. Different SHAs intentionally break stickiness; same SHA preserves it across container restarts.
- Don't try to preserve stickiness across deploys — accept the latency bump and instrument it (`temporal_workflow_task_latency_seconds` histogram). If the bump is > tolerance, sticky cache TTL can be tuned.
- Stagger worker rollouts (kill old workers in batches) so the bump is amortized rather than synchronized.

**Warning signs:**
- A latency histogram on Temporal task processing shows a synchronized spike at every deploy.
- Temporal UI shows worker identities as bare container IDs (hard to attribute).

**Phase to address:** Phase that introduces Temporal Cloud connection. Setting `identity=` on the Worker is a one-line fix.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Run `docker compose up --build` on the deploy host | One-step deploy, no registry needed | Source on host (security), slow deploys, no rollback, no multi-arch | Only acceptable for v1.1 *during initial bring-up* before CI image build is wired. Must be removed before "production" claim. |
| Bind every service to `0.0.0.0` "just to test" | Easy curl from off-host during smoke testing | Public exposure of Postgres, Grafana, Prometheus, Jaeger UI; persistent attack surface | Never. Use `ssh -L` for one-off off-host access. |
| Skip Postgres backups until "later" | Faster phase completion | A single bad migration or `down -v` is a total data loss event with no recovery | Never. Backup + tested restore must land with the Postgres phase. |
| Keep `:latest` tags in prod compose | Convenient image refresh | Non-reproducible deploys, silent regressions, painful rollback | Never in `docker-compose.prod.yml`. Acceptable only in `docker-compose.yml` (dev). |
| Defer cert rotation until first expiry | One less thing to build | Production-killing outage at the 1-year mark with no in-place fix | Never. Rotation runbook + alert must land with Temporal Cloud connection phase. |
| Reuse dev compose as prod compose | Skips the "what's different in prod" thinking | Carries `auto-setup`, `:latest` tags, `0.0.0.0` bindings, weak Grafana password into production | Never. `docker-compose.prod.yml` is its own artifact. |
| Delete `pulumi/`, `helm/`, `k8s/` before `pulumi destroy` succeeds | Makes the cleanup PR shorter | Orphaned GCP resources accruing cost, no path back to destroy them via IaC | Never. Strict order: destroy first, delete IaC second. |
| Keep `temporal_address` as the only Temporal env var | Smaller config diff | First production connect to Cloud fails because no namespace/TLS set | Never. Add `temporal_namespace` + TLS fields *before* attempting the Cloud connect. |
| Use `.env` files for production secrets | Familiar pattern | Plaintext on host, easy to commit, leaks via image build context | Acceptable only for non-secret config. Real secrets go through compose `secrets:`. |
| Run Prometheus without retention flags | Default works initially | TSDB fills volume → cascading Postgres failure | Never. Always set both retention.time and retention.size. |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Temporal Cloud | `Client.connect(addr)` with no namespace/TLS | `Client.connect(addr, namespace="<n>.<id>", tls=TLSConfig(client_cert=..., client_private_key=...))` |
| Temporal Cloud | Use namespace name only (`vici-prod`) | Always include account suffix (`vici-prod.a1b2c`) in `namespace=` and CLI |
| Temporal Cloud auth | Embed cert content directly in env var | Mount cert files via Compose `secrets:` at `/run/secrets/temporal_cert`, read at connect time |
| Postgres visibility | Reuse OpenSearch list-filter queries verbatim | Re-test all queries against Postgres; register custom search attributes per-namespace explicitly |
| Postgres visibility | Assume search attributes carry over from old cluster | They don't. ES → Postgres has no dual-visibility migration support. Closed workflow searchability ends at cutover. |
| OpenAI / Pinecone (unchanged but env-dependent) | Hardcode endpoint URLs in code | Env-driven, settings-typed (already correct in current code; preserve through de-platforming) |
| Twilio | Forget `webhook_base_url` changes when host changes | The validated v1.0 requirement depends on the public URL Twilio posts to. New host = update Twilio console + `WEBHOOK_BASE_URL` env. |
| OTel collector → Jaeger | Assume `jaeger-collector:4317` resolves cross-network | All compose services must share a network (default works); when split into multiple compose files, declare an explicit external network. |
| Prometheus → app `/metrics` | Forget to scrape the new container DNS name | `prometheus.yml` `static_configs.targets` must use the compose service name (`app:8000`), not `localhost`. |
| Docker registry pulls | Anonymous pulls hit rate limits at Docker Hub | Pull from `ghcr.io` (no rate limit for our own images) or authenticate the deploy host to Docker Hub. |
| Reverse proxy (nginx/Caddy) | Forget WebSocket upgrade for Temporal UI / Grafana live | Configure `proxy_set_header Upgrade $http_upgrade` and `Connection "upgrade"` for any service using SSE/WebSocket. |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| ALWAYS_ON sampler at scale | Jaeger storage fills; trace UI slows | Switch to `ParentBased(TraceIdRatioBased(0.1))` past threshold | At sustained >10 workflows/sec or >100 spans/sec |
| Postgres visibility for high-volume queries | List queries time out; Temporal UI sluggish | Add indexes on `executions_visibility(workflow_type_name, start_time)`; consider OS visibility plugin if scale demands | At >100 list-query/min or >1M visibility rows |
| Single Postgres for app + Temporal visibility | Resource contention; one bad query starves the other | Run separate Postgres instances or schemas with connection-limit isolation | At >10 active connections sustained |
| QEMU multi-arch builds | 5-20x slower image builds; CI timeouts | Build natively on matching-arch runners (x86 runner for x86 image, ARM runner for ARM image) | Any time multi-arch builds take >5 min |
| Naive `docker compose up --build` on every deploy | Multi-minute deploy time; OOM on small VPS | Build in CI, push to registry, deploy host pulls only | Once deploy host has <2GB RAM or builds take >30s |
| Unbounded Prometheus retention | Disk fills; Postgres WAL writes fail | Set `--storage.tsdb.retention.time=30d --storage.tsdb.retention.size=10GB` | Within weeks at any sustained span/metric rate |
| Sticky cache thrash on deploy | Latency spike at every restart | Set stable `Worker(identity=...)` keyed on git SHA; stagger rollouts | Visible at >5 in-flight workflows per worker |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Default `admin/admin` Grafana | Credential takeover, pivot to internal metrics | Require non-default password via `_validate_required_credentials`; mount via `__FILE` env var pattern |
| `0.0.0.0` port bindings on dev-internal services | Public exposure of Postgres, Grafana, Prometheus, Jaeger UI | Bind to `127.0.0.1` explicitly or omit `ports:` block; rely on Docker network |
| `:latest` tags | Supply-chain risk; non-reproducible | Pin to digest: `image: foo:1.2.3@sha256:...` |
| Compose `secrets:` treated as encrypted | False sense of security; host file is plaintext | Document explicitly; restrict host file mode to `0600`, owned by deploy user |
| `env_file:` containing secrets | Backups, logs, `docker inspect`-equivalents may leak | Use `secrets:` for credentials; `env_file:` for non-secret config only |
| Compose `secrets:` source committed to git | Permanent secret leak in git history | `.gitignore` + `.dockerignore` `secrets/`, `.env*`, `*.pem`, `*.key` |
| TLS cert files in Dockerfile `COPY` instructions | Secrets baked into image layers, leak on registry push | Never. Mount at runtime via `secrets:` |
| Build args (`--build-arg SECRET=...`) | Visible in image history | Use `RUN --mount=type=secret,id=foo` (BuildKit) instead |
| Postgres exposed to internet for "remote admin" | Direct DB compromise | Bind to `127.0.0.1`; use `ssh -L 5432:postgres:5432` for ad-hoc access |
| ESO config left in repo after migration | Confusion about source of truth; future reader thinks ESO is still active | Delete `helm/`, `pulumi/`, all `ExternalSecret` CRDs; grep for `ExternalSecret` and remove every reference |

---

## "Looks Done But Isn't" Checklist

Phase reviewers should verify each:

- [ ] **Temporal Cloud connection:** verify `Client.connect` includes `namespace=` AND TLS material; verify worker shows up as a poller in Temporal Cloud UI (not just "no connection error").
- [ ] **Cert lifecycle:** verify Prometheus exposes a `temporal_client_cert_expires_seconds` gauge AND there is an alert rule for it.
- [ ] **Cron migration:** verify exactly one running cron workflow in Temporal Cloud; verify schedule matches config; verify the old GKE cron is terminated.
- [ ] **Visibility migration:** verify any operational queries used in runbooks/dashboards return expected results against Postgres visibility.
- [ ] **In-flight drain:** verify `temporal workflow list --query 'ExecutionStatus="Running"'` in old GKE cluster returns empty *before* teardown.
- [ ] **Port bindings:** verify `nmap` from off-host shows only intended public ports (`:443`, maybe `:80` for ACME).
- [ ] **Grafana password:** verify default is removed from `src/config.py`; verify production startup fails if password not set; verify Grafana login does not accept `admin/admin`.
- [ ] **Image pinning:** verify `docker-compose.prod.yml` has zero `:latest` references and every `image:` includes a digest.
- [ ] **Postgres backups:** verify backup file from <24h ago exists; verify a restore test was performed and documented.
- [ ] **Prometheus retention:** verify `--storage.tsdb.retention.time` and `--storage.tsdb.retention.size` are both set.
- [ ] **Pulumi destroy:** verify GCP console shows zero resources tagged `pulumi-stack=<vici-stack>`; verify GCP billing for the project is at zero recurring charges.
- [ ] **Code cleanup:** `rg -i 'gke|gcp|helm|pulumi|cloud_sql|external-secret|render\.yaml'` returns hits only in archived `.planning/` directories or comments deliberately preserved with rationale.
- [ ] **Dockerfile comment update:** line 37 ("GKE runs migrations as a separate K8s Job before deployment") rewritten to reflect new deploy flow.
- [ ] **`.dockerignore`:** verify `.env*`, `*.pem`, `*.key`, `secrets/`, `pulumi/`, `helm/`, `k8s/`, `.planning/` are all listed.
- [ ] **CI/CD:** verify GitHub Actions workflows have no remaining `helm`, `kubectl`, `gcloud`, or `pulumi` steps.
- [ ] **Worker identity:** verify `Worker(identity=...)` is set to a stable, version-aware string.
- [ ] **Connection retry:** verify `get_temporal_client` has bounded-retry on initial connect; verify `restart: unless-stopped` is set on the app service.
- [ ] **Reverse proxy:** verify only one public port binding, behind TLS, with auth on any UI surface.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Temporal Cloud connection broken at deploy | LOW | Roll back container image; debug `Settings` validation locally; redeploy. Workflows resume on reconnect. |
| Cert expired in production | MEDIUM | Generate new cert via tcld; copy to host; `docker compose up -d --no-deps app`. In-flight workflows complete on reconnect. |
| Cron registered with wrong schedule | LOW | Terminate the cron in Temporal UI; redeploy with corrected config; verify new schedule registered. |
| In-flight workflows lost during cutover | HIGH | Reconciliation script: query `audit_log` for messages without `jobs`/`work_goals` rows, replay through pipeline. Owner-aware: not all messages have a job/goal outcome (unknown branch). |
| Custom search attribute query broken | LOW | Register the attribute in the new namespace via `temporal operator search-attribute create`; backfill is not possible for closed workflows but new workflows work. |
| Postgres visibility queries timing out | MEDIUM | Add database indexes; if persistent, consider OS visibility plugin or Temporal Cloud (which uses ES under the hood). |
| Grafana compromised via default password | HIGH | Rotate password; rotate Prometheus/Grafana shared secrets if any; audit dashboard access logs; bind port to 127.0.0.1. |
| Public Postgres port discovered | CRITICAL | Immediately bind to 127.0.0.1; rotate Postgres password; audit `pg_stat_activity` and connection log; assume DB credentials compromised. |
| Pulumi state deleted before destroy | HIGH | Manually walk GCP console: GKE clusters, persistent disks, LBs, static IPs, Cloud SQL, NATs, VPCs, service accounts, secrets. Use `pulumi-stack=` tag if present. Submit GCP billing-credit request if charges accrued. |
| Grafana / Prometheus disk full | MEDIUM | Stop services; truncate TSDB to recent data; set retention flags; restart. Some metric history is lost. |
| Image built on deploy host using stale code | LOW | Pull latest image from registry; `docker compose up -d --no-deps`. Move build to CI to prevent recurrence. |
| Wrong env var precedence on deploy | LOW | `docker compose exec app env | sort` to see actual; fix `.env.production`; `docker compose up -d --force-recreate app`. |
| Sticky cache thrash visible as latency spike | LOW | Cosmetic; set stable `Worker(identity=...)` and let next deploy normalize. |

---

## Pitfall-to-Phase Mapping

This is the input the roadmap should use. Phases are conceptual labels — actual phase numbers depend on roadmap construction.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Temporal Cloud connection shape | "Temporal Cloud connection" phase | Worker shows up as poller in Cloud UI; first activity completes |
| 2. Cert lifecycle | "Temporal Cloud connection" phase (same phase, not later) | Prometheus gauge + alert rule both present in tree |
| 3. Cron duplicate registration | "GKE Temporal teardown" phase | `temporal workflow list` in Cloud shows exactly one cron |
| 4. In-flight workflows abandoned | "GKE Temporal teardown" / cutover phase | Pre-cutover workflow-list-empty check is a phase success criterion |
| 5. Search attributes scope change | "Postgres visibility migration" phase | Per-namespace registration script; existing queries audited |
| 6. Postgres visibility query limits | "Postgres visibility migration" phase | Baseline measurement of representative list query latency |
| 7. `auto-setup` image in prod | "Production compose introduction" phase | CI grep for `temporalio/auto-setup` returns zero |
| 8. `:latest` tags | "Production compose introduction" phase | CI grep for `:latest` in prod compose returns zero |
| 9. Compose secrets vs env_file leakage | "Secrets distribution" phase (replaces ESO) | `.dockerignore` audit; image-history grep for known secret patterns |
| 10. `0.0.0.0` port bindings | "Production compose introduction" phase | `nmap` from off-host shows only public ports |
| 11. Grafana default password | "Production observability" phase | `_validate_required_credentials` requires `grafana_admin_password`; default removed from `src/config.py` |
| 12. ALWAYS_ON sampler scaling cost | "Production observability" phase | Documented threshold + alert; do not change sampler in v1.1, just instrument |
| 13. Prometheus retention | "Production observability" phase | Both `retention.time` and `retention.size` flags set in compose |
| 14. Pulumi state deleted prematurely | "GKE/GCP teardown" phase | `pulumi destroy` clean exit code is a hard gate |
| 15. Orphaned GKE/GCP code references | "Cleanup" phase (dedicated final phase) | `rg -i` checklist all return clean |
| 16. Building on deploy host | "CI image build" phase (precedes any prod deploy) | Prod compose has no `build:` blocks; only `image:` |
| 17. `.env` precedence surprises | "Production compose introduction" phase | DEPLOY.md documents precedence; CI smoke-test verifies env at runtime |
| 18. App startup race against Temporal Cloud | "Temporal Cloud connection" phase + prod compose phase | Bounded retry in code + `restart: unless-stopped` in compose |
| 19. Postgres backups missing | "Self-managed Postgres" phase (replaces Cloud SQL) | Tested restore demonstrated in phase plan |
| 20. Cron schedule update via start_workflow | "Temporal Cloud connection" phase | Migrate to Schedule API or document workflow-ID-bump procedure |
| 21. Worker identity churn | "Temporal Cloud connection" phase | `Worker(identity=...)` is set to a stable string |

---

## Sources

- [Temporal Cloud connection (Python SDK)](https://docs.temporal.io/develop/python/client/temporal-client) — verified mTLS connection shape, `namespace=` requirement
- [Temporal Cloud Namespaces](https://docs.temporal.io/cloud/namespaces) — verified namespace ID format `<name>.<account-id>`
- [Temporal Visibility (Postgres vs Elasticsearch)](https://docs.temporal.io/visibility) — verified namespace-scoping difference, no dual-vis ES→PG migration support
- [Temporal Search Attributes](https://docs.temporal.io/search-attribute) — verified per-namespace registration on SQL backends
- [Temporal Self-hosted Visibility setup](https://docs.temporal.io/self-hosted-guide/visibility) — verified Postgres v12+ requirement
- [Temporal Manual Migration](https://docs.temporal.io/cloud/migrate/manual) — verified s2s-proxy + drain pattern
- [Temporal Sticky Execution](https://docs.temporal.io/sticky-execution) — verified worker identity → sticky cache mapping
- [Temporal Schedule (vs cron)](https://docs.temporal.io/schedule) — verified Schedule API as preferred alternative to `cron_schedule=`
- [Docker secrets (Phase blog)](https://phase.dev/blog/docker-compose-secrets/) — env var leakage patterns
- [Dockerfile secrets in image layers (Xygeni)](https://xygeni.io/blog/dockerfile-secrets-why-layers-keep-your-sensitive-data-forever/) — verified layer immutability
- [Stop using env vars for secrets in Compose](https://medium.com/@bernard.sofeng/stop-using-environment-variables-for-secrets-in-docker-compose-fd0be09ebcc5) — runtime risk patterns
- [BuildKit `--mount=type=secret`](https://oneuptime.com/blog/post/2026-02-08-how-to-use-run-mounttypesecret-for-build-time-secrets/view) — verified build-time secret pattern
- [5 Docker Compose mistakes in production (Elest.io)](https://blog.elest.io/5-docker-compose-mistakes-that-will-bite-you-in-production/) — verified `0.0.0.0` default + iptables bypass
- [Why You Should Never Expose Docker Ports Carelessly (buka.sh)](https://corner.buka.sh/why-you-should-never-expose-docker-ports-carelessly-and-what-to-do-instead/) — `127.0.0.1:` binding pattern
- [Pulumi destroy failures](https://www.pulumi.com/docs/support/troubleshooting/common-issues/destroy-failures/) — verified destroy-before-state-delete order
- [Pulumi state delete CLI](https://www.pulumi.com/docs/iac/cli/commands/pulumi_state_delete/) — verified individual-resource scope
- [Pulumi retainOnDelete blog](https://www.pulumi.com/blog/retainondelete/) — context on retention semantics
- [OpenTelemetry sampling spec](https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/trace/sdk.md) — verified ParentBased + TraceIdRatioBased pattern
- [OpenTelemetry sampling strategies (OneUptime)](https://oneuptime.com/blog/post/2026-01-24-opentelemetry-sampling-strategies/view) — production cost guidance
- [Docker Compose multi-platform builds](https://docs.docker.com/build/building/multi-platform/) — verified buildx + `--platform` pattern
- [Docker Compose healthcheck/depends_on (Last9)](https://last9.io/blog/docker-compose-health-checks/) — verified `service_healthy` semantics
- [Daylight AI: Migrating off Temporal Cloud at 500/sec](https://daylight.ai/blog/how-we-migrated-off-temporal-cloud-without-downtime) — real-world drain pattern (read in the *opposite* direction for our case)
- [Temporal Community: workflow ID retention](https://community.temporal.io/t/retention-and-duplicate-workflow-policy/8586) — verified ID reuse policy interaction with retention
- Internal: `src/temporal/worker.py`, `src/config.py`, `docker-compose.yml`, `Dockerfile` — verified current shape against pitfall risks

---
*Pitfalls research for: GKE/GCP → Docker-only de-platforming (milestone v1.1)*
*Researched: 2026-05-01*
*Confidence: HIGH (all critical claims verified against Temporal docs, Docker docs, Pulumi docs, OTel spec; current-source code reads were used to ground each pitfall in observable code in this repo)*
