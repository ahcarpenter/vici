# Phase 5: GHCR Image Distribution & CI Validation - Pattern Map

**Mapped:** 2026-05-01
**Files analyzed:** 7 (1 modify, 1 create, 4 delete, 1 conditional-modify)
**Analogs found:** 6 / 7 (the conditional-modify "scrub stale secrets" file does not currently exist — see "No Analog Found")

## File Classification

| New/Modified File | Operation | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|-----------|------|-----------|----------------|---------------|
| `.github/workflows/ci.yml` | modify (extend) | CI workflow | event-driven (push/PR/dispatch) | itself (lines 1-48) + `cd-base.yml:46-68` | exact (existing file) + role-match (build pattern) |
| `docker-compose.prod.yml` | create | Compose overlay | static config | `docker-compose.yml:55-70` (`app` service block) | role-match (compose service stanza) |
| `.github/workflows/cd-base.yml` | delete | Reusable CI workflow | — | n/a (deletion) | n/a |
| `.github/workflows/cd-dev.yml` | delete | CI workflow trigger | — | n/a (deletion) | n/a |
| `.github/workflows/cd-staging.yml` | delete | CI workflow trigger | — | n/a (deletion) | n/a |
| `.github/workflows/cd-prod.yml` | delete | CI workflow trigger | — | n/a (deletion) | n/a |
| (D-17) any surviving workflow with stale secret refs | conditional-modify | CI workflow | — | none — only `ci.yml` survives and it has no `WIF_*` / `PULUMI_*` refs | no analog needed |

**Job-level classification within the extended `ci.yml`:**

| New Job | Role within workflow | Data Flow | Closest Analog | Notes |
|---------|---------------------|-----------|----------------|-------|
| `compose-validate` | Static-parse gate | request-response (shell exit code) | `ci.yml:23-27` (Lint / Format check pattern: simple shell `run:` with non-zero exit on failure) | Pure shell; runs on PR + push |
| `build-amd64` / `build-arm64` (matrix) | Per-arch image build + digest push | batch (build → digest artifact) | `cd-base.yml:46-68` (sha-output, buildx setup, build-push-action with GHA cache) | Retarget GCP-AR → GHCR; add `push-by-digest=true`, `sbom`, `provenance`, per-arch `scope=` |
| `merge` | Manifest assembly | transform (digests → multi-arch manifest) | None in current codebase — pattern from RESEARCH.md §Code Examples §Merge job | Net-new pattern; uses `docker buildx imagetools create` |
| `verify` | Post-publish assertion | request-response (inspect + jq) | None in current codebase — pattern from RESEARCH.md §Code Examples §Verify job | Net-new pattern; runs anonymously (no GHCR creds) |

## Pattern Assignments

### `.github/workflows/ci.yml` — extend, do not rewrite

**Analog (the file itself, existing top-level structure to preserve):**

**Trigger pattern** (`ci.yml:3-7`) — extend `on:` to add `tags: ['v*']` and `workflow_dispatch`:
```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```
Phase 5 extends this to:
```yaml
on:
  push:
    branches: [main]
    tags: ['v*']
  pull_request:
    branches: [main]
  workflow_dispatch:
```

**Existing job structure to preserve untouched** (`ci.yml:9-47`):
```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install dependencies
        run: uv sync --frozen
      - name: Lint
        run: uv run ruff check src/ tests/ infra/
      - name: Format check
        run: uv run ruff format --check src/ tests/ infra/
      - name: CVE scan (pip-audit)
        continue-on-error: true
        run: |
          uv export --no-hashes --format requirements-txt --frozen > /tmp/requirements.txt
          uvx pip-audit -r /tmp/requirements.txt
      - name: Test
        run: uv run pytest tests/ -x --tb=short -q
        env:
          DATABASE_URL: sqlite+aiosqlite:///./test.db
          ...
```
Phase 5 keeps `test:` exactly as-is. The 5 new jobs are appended as siblings of `test:` under the same `jobs:` map.

**Style conventions to match in the new jobs:**
- 2-space indentation, no trailing whitespace
- `uses: <action>@<major>` (already follows: `@v4`, `@v5` in existing; Phase 5 adds `@v4` `@v6` `@v7` `@v8` per RESEARCH.md §Standard Stack)
- `name:` on every step that does non-trivial work (matches `ci.yml:23, 26, 29, 35`)
- `runs-on: ubuntu-latest` unbroken-string (matches `ci.yml:11`)
- `actions/checkout` is the first step in any job that touches the repo (matches `ci.yml:14`)

**Concurrency block to add at workflow level** (no analog in current `ci.yml`; closest precedent is `cd-staging.yml:17-19` and `cd-prod.yml:17-19` — both use `cancel-in-progress: false` for the same reason D-12 does):
```yaml
# from cd-staging.yml:14-19
# WR-02 fix: serialize staging deploys per stack. cancel-in-progress
# is false here because a staging deploy is manually dispatched and
# should never be silently cancelled mid-apply by a follow-up click.
concurrency:
  group: cd-staging
  cancel-in-progress: false
```
Phase 5 adopts the same `cancel-in-progress: false` rationale (D-12: rollback invariant) but uses `group: ghcr-${{ github.ref }}`.

---

### `build-amd64` / `build-arm64` jobs (matrix in extended `ci.yml`)

**Analog:** `.github/workflows/cd-base.yml:30-68` (the entire `build:` job — being deleted in this same phase, but its patterns directly inform the new GHCR build).

**SHA-extraction pattern** (`cd-base.yml:43-49`):
```yaml
    outputs:
      sha: ${{ steps.sha.outputs.sha }}
    steps:
      - uses: actions/checkout@v4

      - id: sha
        run: echo "sha=$(git rev-parse --short=7 HEAD)" >> "$GITHUB_OUTPUT"
```
Phase 5 replaces the manual `git rev-parse` shell step with `docker/metadata-action@v6` (per "Don't Hand-Roll" guidance in RESEARCH.md §Don't Hand-Roll), but the **7-char short SHA contract is preserved verbatim** (D-04, D-07). The verify job, which has no metadata-action context, falls back to the literal `cd-base.yml:49` pattern: `git rev-parse --short=7 ${{ github.sha }}`.

**Buildx + build-push-action pattern** (`cd-base.yml:51-68`):
```yaml
      - uses: google-github-actions/auth@v3        # DELETE — replaced by docker/login-action@v4
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.WIF_SERVICE_ACCOUNT }}

      - uses: docker/setup-buildx-action@v3        # bump to @v4 per RESEARCH.md §Standard Stack

      - name: Configure Docker for Artifact Registry   # DELETE — GHCR uses login-action
        run: gcloud auth configure-docker us-central1-docker.pkg.dev --quiet

      - uses: docker/build-push-action@v6           # bump to @v7
        if: inputs.command == 'up'                  # DELETE — Phase 5 has no `up`/`preview` split
        with:
          context: .
          push: true                                # REPLACE with outputs: type=image,push-by-digest=true,...
          tags: us-central1-docker.pkg.dev/${{ inputs.gcp_project }}/vici-images/vici:${{ steps.sha.outputs.sha }}
                                                    # REPLACE — labels-only via metadata-action; tags assembled in merge
          cache-from: type=gha                      # ADD scope=${{ env.ARCH }} per D-11
          cache-to: type=gha,mode=max               # ADD scope=${{ env.ARCH }} per D-11
                                                    # ADD provenance: mode=max + sbom: true per D-14
```

**Diff summary** (what to copy, what to drop, what to add):

| Element | From `cd-base.yml` | Phase 5 build job |
|---------|--------------------|--------------------|
| `actions/checkout` | `@v4` (line 46) | `@v6` (RESEARCH §Standard Stack) |
| Auth | `google-github-actions/auth@v3` (lines 51-54) | **DELETE.** Replace with `docker/login-action@v4` against `registry: ghcr.io` (RESEARCH §Code Examples §Per-arch build matrix step) |
| `gcloud auth configure-docker` | line 58-59 | **DELETE.** GHCR auth is fully handled by login-action |
| `docker/setup-buildx-action` | `@v3` (line 56) | `@v4` |
| `docker/build-push-action` | `@v6` (line 61) | `@v7` |
| `if: inputs.command == 'up'` gate | line 62 | **REPLACE** with `if: github.event_name != 'pull_request'` at the job level (D-15) |
| `push: true` | line 65 | **REPLACE** with `outputs: type=image,name=${{ env.GHCR_IMAGE }},push-by-digest=true,name-canonical=true,push=true` |
| `tags:` | line 66 (single literal) | **REPLACE** with `labels: ${{ steps.meta.outputs.labels }}` (tags assembled in merge job from digests) |
| `cache-from: type=gha` | line 67 | **KEEP**, add `,scope=${{ env.ARCH }}` (D-11) |
| `cache-to: type=gha,mode=max` | line 68 | **KEEP**, add `,scope=${{ env.ARCH }}` (D-11) |
| `provenance` / `sbom` | not present | **ADD** `provenance: mode=max` + `sbom: true` (D-14) |

**Permissions block pattern** (`cd-base.yml:40-42`):
```yaml
    permissions:
      contents: read
      id-token: write
```
Phase 5 build job extends to:
```yaml
    permissions:
      contents: read
      packages: write          # ADD: GHCR push (Pitfall 7)
      attestations: write      # ADD: required for sbom/provenance (Pitfall 7)
      id-token: write          # KEEP: future-proofing for keyless signing
```

---

### `compose-validate` job (new, in extended `ci.yml`)

**Closest analog for shell-step style:** `ci.yml:29-33` (CVE scan step):
```yaml
      - name: CVE scan (pip-audit)
        continue-on-error: true
        run: |
          uv export --no-hashes --format requirements-txt --frozen > /tmp/requirements.txt
          uvx pip-audit -r /tmp/requirements.txt
```
Phase 5 follows the same multi-line `run: |` shape but **WITHOUT `continue-on-error: true`** — compose-validate is a hard merge gate (CI-03). The two-overlay validation matches the empirically verified pattern in RESEARCH.md §Code Examples §Compose validate job:
```yaml
      - name: Validate base alone
        run: docker compose -f docker-compose.yml config --quiet

      - name: Validate base + prod (with GIT_SHA exported)
        run: |
          export GIT_SHA=$(git rev-parse --short=7 HEAD)
          docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
```
The `git rev-parse --short=7 HEAD` invocation is **byte-for-byte identical** to `cd-base.yml:49` — that is the in-codebase precedent for the 7-char SHA.

---

### `merge` job (new, in extended `ci.yml`)

**No exact analog in current codebase.** The closest local pattern is the `needs:` chain shape in `cd-base.yml:70-72`:
```yaml
  deploy:
    runs-on: ubuntu-latest
    needs: [build]
```
Phase 5 merge job mirrors this dependency declaration: `needs: [build-amd64, build-arm64]`. Beyond `needs:`, the job body is fully net-new — extract from RESEARCH.md §Code Examples §Merge job (lines 454-499 of 05-RESEARCH.md). Key patterns:
- `actions/download-artifact@v8` with `pattern: digests-*` and `merge-multiple: true`
- `docker buildx imagetools create` (NOT legacy `docker manifest create` — see RESEARCH §Anti-Patterns)
- The `jq` incantation `$(jq -cr '.tags | map("-t " + .) | join(" ")' <<< "$DOCKER_METADATA_OUTPUT_JSON")` for tag list expansion

---

### `verify` job (new, in extended `ci.yml`)

**No analog in current codebase.** The pattern is entirely from RESEARCH.md §Code Examples §Verify job (lines 504-559 of 05-RESEARCH.md). Reference that section verbatim. Key load-bearing constraints:
- **No `permissions: packages: write`** — verify must be anonymous to prove the public-toggle worked (D-09, Pitfall 2)
- **Corrected jq predicate** — the attestation manifest filter is `select(.annotations["vnd.docker.reference.type"] == "attestation-manifest")`, NOT the `mediaType == "application/vnd.in-toto+json"` predicate written in CONTEXT.md D-14 (RESEARCH.md §Pitfall 3)
- **3-attempt retry loop with 10s sleep** — handles GHCR eventual consistency (RESEARCH §Pitfall 9)
- **`timeout-minutes: 10`** — covers cold-pull edge cases (RESEARCH §Code Examples)

---

### `docker-compose.prod.yml` (new, 3 lines per D-02)

**Analog:** `docker-compose.yml:55-70` — the existing `app:` service stanza, for indentation/key-style consistency.

**Existing `app:` service block** (`docker-compose.yml:55-70`):
```yaml
  app:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      jaeger-collector:
        condition: service_started
      temporal:
        condition: service_healthy
    env_file: .env.app
    volumes:
      - ./src:/app/src
    ports:
      - "8000:8000"
    command: >
      sh -c "uv run alembic upgrade head && uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"
```
Phase 5 prod overlay (full file per D-02):
```yaml
services:
  app:
    image: ghcr.io/ahcarpenter/vici:sha-${GIT_SHA:?GIT_SHA must be set to the 7-char short SHA}
```

**Style conventions to match from base compose:**
- 2-space top-level indentation under `services:`
- 4-space (2+2) indentation for keys under each service (`build:`, `image:`, `env_file:`, etc. all sit at 4 spaces in `docker-compose.yml`)
- No `version:` key at the top (base file omits it; Compose v2.x ignores it anyway — RESEARCH §Code Examples)
- Single trailing newline at EOF (matches `docker-compose.yml`)
- Bare string values for `image:` (no quotes around the literal — matches the pattern of `image: postgres:16` on `docker-compose.yml:3`, `image: opensearchproject/opensearch:2.19.4` on line 14, etc.)

**Why image-only stub matches base-file style:** The base file's `app:` service uses `build: .` to build locally. The prod overlay's job is to swap that one key for `image: ghcr.io/...` — Compose's deep-merge semantics handle everything else (the `env_file`, `depends_on`, `ports`, `command` from the base stay intact). D-02 explicitly forbids any other override in Phase 5; Phase 6 will expand.

---

### File deletions (`cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`)

No analog needed — pure deletion per D-16. The deletion is a `git rm` on each path. The patterns inside these files (build steps, concurrency blocks, secrets references) are extracted into the build/merge/verify job sections above before the files vanish.

**Verification command after deletion** (per VALIDATION.md §CI-04):
```bash
test ! -e .github/workflows/cd-base.yml \
  && test ! -e .github/workflows/cd-dev.yml \
  && test ! -e .github/workflows/cd-staging.yml \
  && test ! -e .github/workflows/cd-prod.yml
```

---

### D-17 stale-secret scrub (conditional)

**No work required.** The only workflow file surviving Phase 5 is `.github/workflows/ci.yml`, and a full read of that file (lines 1-48) shows zero references to `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, or `PULUMI_CONFIG_PASSPHRASE`. All stale secret references live in the four `cd-*.yml` files being deleted (lines 19-24, 41-43 of `cd-base.yml`; lines 41-43 of `cd-dev.yml`; lines 29-31 of `cd-staging.yml`; lines 30-32 of `cd-prod.yml`) — deletion eliminates them by definition. The planner should record D-17 as "satisfied transitively by D-16; no separate edit needed" rather than as a Wave 0 task.

---

## Shared Patterns

### Major-version pinning convention

**Source:** `ci.yml:14, 16` and `cd-base.yml:46, 56, 61, 78, 88, 92, 121`
**Apply to:** Every new `uses:` reference in Phase 5
```yaml
- uses: actions/checkout@v4         # ci.yml:14
- uses: astral-sh/setup-uv@v5       # ci.yml:16
- uses: docker/setup-buildx-action@v3   # cd-base.yml:56
- uses: docker/build-push-action@v6     # cd-base.yml:61
```
**Phase 5 adoption:** Same `@major` style; bump majors per RESEARCH.md §Standard Stack (`@v4` → `@v6` for checkout, `@v3` → `@v4` for buildx, `@v6` → `@v7` for build-push, etc.).

### `permissions:` block at job level for elevated scopes

**Source:** `cd-base.yml:40-42`
```yaml
    permissions:
      contents: read
      id-token: write
```
**Apply to:** `build-amd64`, `build-arm64`, `merge` jobs (need `packages: write`); `verify` job (no elevated scopes — explicitly anonymous per D-09).

### Concurrency block with `cancel-in-progress: false` for invariant-preserving pipelines

**Source:** `cd-staging.yml:14-19` and `cd-prod.yml:14-19`
```yaml
# WR-02 fix: serialize prod deploys per stack. cancel-in-progress is
# false because an approved prod deploy must never be silently
# cancelled mid-apply by a follow-up dispatch.
concurrency:
  group: cd-prod
  cancel-in-progress: false
```
**Apply to:** Workflow-level `concurrency:` block on `ci.yml`. D-12 mandates `cancel-in-progress: false` for the rollback-invariant reason (every `main` SHA must publish an image); the comment style ("X fix: serialize Y because Z") is a useful precedent for documenting the same rationale in the new block.

### Multi-line `run: |` shell step style

**Source:** `ci.yml:31-33` and `cd-base.yml:114-117`
```yaml
        run: |
          uv export --no-hashes --format requirements-txt --frozen > /tmp/requirements.txt
          uvx pip-audit -r /tmp/requirements.txt
```
**Apply to:** All new shell steps in `compose-validate`, the env-export step in `build-*`, the `imagetools create` step in `merge`, and the inspect+jq+retry steps in `verify`.

### `actions/checkout` as the first step

**Source:** `ci.yml:14`, `cd-base.yml:46, 78`
**Apply to:** Every Phase 5 job that touches the repo. The `verify` job notably does NOT need checkout — it operates purely on a remote registry — but `compose-validate`, `build-*`, and (optionally) `merge` do.

### `runs-on: ubuntu-latest` default

**Source:** `ci.yml:11`, `cd-base.yml:32, 71`
**Apply to:** All new jobs except `build-arm64`, which uses the conditional matrix expression `runs-on: ${{ matrix.platform == 'linux/amd64' && 'ubuntu-latest' || 'ubuntu-24.04-arm' }}` (RESEARCH §Code Examples §Per-arch build matrix step).

---

## No Analog Found

Files with no close match in the codebase (planner uses RESEARCH.md patterns instead):

| File / Job | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `merge` job | manifest assembly | transform | No prior multi-arch image work in this repo. Pattern is fully from RESEARCH.md §Code Examples §Merge job |
| `verify` job | post-publish assertion | request-response | No prior anonymous-pull verification in this repo. Pattern is fully from RESEARCH.md §Code Examples §Verify job (with the corrected attestation predicate flagged in §Pitfall 3) |
| `docker/login-action@v4` GHCR auth | registry auth | request-response | Existing repo authenticates to GCP Artifact Registry via WIF (`cd-base.yml:51-54`); GHCR via `GITHUB_TOKEN` is net-new. Pattern from RESEARCH §Code Examples |
| `outputs: type=image,push-by-digest=true,name-canonical=true,push=true` | digest-only push | streaming (digest → artifact) | Existing `cd-base.yml:65` uses simple `push: true` with literal tags. Push-by-digest is net-new. Pattern from RESEARCH §Code Examples |
| `actions/upload-artifact` for digest passing | inter-job data transfer | event-driven | Net-new in this repo. Pattern from RESEARCH §Code Examples |
| `docker/metadata-action@v6` | tag computation | transform | Existing `cd-base.yml:48-49` does the same thing in shell; metadata-action is the upgrade path. Pattern from RESEARCH §Code Examples and §Don't Hand-Roll |

## Metadata

**Analog search scope:**
- `.github/workflows/*.yml` (all 5 files: `ci.yml`, `cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`)
- `docker-compose.yml` (root)
- RESEARCH.md §Code Examples (lines 350-600 of `05-RESEARCH.md`) for net-new patterns

**Files scanned:** 6 (all read end-to-end; none required Grep-then-targeted-read)

**Pattern extraction date:** 2026-05-01

**Critical reminders for the planner:**
1. The four `cd-*.yml` files are being deleted in this same phase. Their build patterns (especially `cd-base.yml:48-68`) are the most informative analog — extract before merge.
2. CONTEXT.md D-14 contains a known-incorrect jq predicate. Use the corrected predicate from RESEARCH.md §Code Examples §Verify job (the `vnd.docker.reference.type=attestation-manifest` annotation filter), NOT the `mediaType == "application/vnd.in-toto+json"` form.
3. CONTEXT.md "Claude's Discretion" mentions "v5/v6 as appropriate" for action versions — this is stale. RESEARCH §Standard Stack pins the current majors (v4/v6/v7/v8) verified against the GitHub Releases API on 2026-05-01.
4. The existing `ci.yml` is **extended**, not rewritten. The `test:` job (lines 9-47) stays exactly as-is per D-15. New jobs are siblings appended to the same `jobs:` map.

## PATTERN MAPPING COMPLETE
