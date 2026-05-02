# Phase 5: GHCR Image Distribution & CI Validation - Context

**Gathered:** 2026-05-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Publish multi-arch (linux/amd64 + linux/arm64) Docker images of the Vici app to GitHub Container Registry on every push to `main`, every git tag matching `v*`, and on manual `workflow_dispatch`. Images are SHA-pinned (`sha-<7char>`) and immutable — no `:latest` tag is ever applied. CI also validates both compose overlays (`docker-compose.yml` alone, and base + `docker-compose.prod.yml`) on every push and pull request, blocking the merge on any compose-config error. Phase 5 also creates a minimal `docker-compose.prod.yml` stub (image-only override) so the second compose-validate command has something to validate, and deletes the four legacy GKE-targeted CD workflow files (`cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`) plus any of their stale secret references in remaining workflows.

Phase 5 does not flesh out the prod overlay (Phase 6), does not move secrets to compose-native `secrets:` (Phase 7), does not touch Temporal or the bundled observability containers (Phase 8), and does not delete `infra/`, `helm/`, `k8s/`, ESO, or `render.yaml` (Phase 9 — last by mandate).

</domain>

<decisions>
## Implementation Decisions

### Prod Overlay Stub (`docker-compose.prod.yml`)
- **D-01:** Phase 5 creates `docker-compose.prod.yml` so CI-03 fully passes from day one. The stub is the minimum viable override — image-only on the `app` service.
- **D-02:** Stub contents are exactly:
  ```yaml
  services:
    app:
      image: ghcr.io/ahcarpenter/vici:sha-${GIT_SHA:?GIT_SHA must be set to the 7-char short SHA}
  ```
  Nothing else. No `pull_policy`, no `command:` override, no bind-mount removal, no healthcheck — all deferred to Phase 6.
- **D-03:** `${GIT_SHA:?...}` fail-loud substitution is mandatory. If `GIT_SHA` is unset, `docker compose config` exits non-zero with the explanatory message. Silent expansion to `sha-` (broken image ref) is rejected. Aligns with the `_validate_required_credentials` fail-fast precedent (Phase 02.11).
- **D-04:** The CI compose-validate step exports `GIT_SHA=$(git rev-parse --short=7 HEAD)` immediately before running `docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet`. Operators do the same on the host before `docker compose ... up -d`. The 7-char short SHA matches the existing `cd-base.yml:49` precedent.
- **D-05:** The prod overlay stub uses the literal string `ghcr.io/ahcarpenter/vici` (not `${{ github.repository_owner }}` since compose files are deployment artifacts that operators read as plain strings). The workflow uses `${{ github.repository_owner }}` instead — see D-13.

### Build Triggers + Tags
- **D-06:** Workflow triggers: `push: branches: [main]`, `push: tags: ['v*']`, and `workflow_dispatch`. PRs do **not** build images — lint/test/compose-config on PRs is the merge gate.
- **D-07:** Image tags are SHA-only: every successful build pushes exactly one tag, `ghcr.io/<owner>/vici:sha-<7char>`. No `:latest`, no `:main`, no semver tags from git tags. Release semantics live in git tags + GitHub Releases, not image tags. Tag computation uses `docker/metadata-action@v5` with `type=sha,prefix=sha-,format=short`.
- **D-08:** GHCR package visibility is set to **public** via a one-time manual GitHub Settings toggle (`github.com/users/ahcarpenter/packages/container/vici/settings`) after the first successful push. The PLAN.md acceptance criteria must call this step out so verification catches it. Automated visibility-flipping via `gh api` is rejected as overkill for a one-time op.
- **D-09:** Verification of success criterion #2 ("pullable by an unauthenticated CI job AND reports both architectures") runs as a **separate `verify` job** in the same workflow. The verify job has no GHCR push credentials and no `actions/login`. It runs `docker buildx imagetools inspect --raw ghcr.io/<owner>/vici:sha-<short>` and `jq`-asserts both `linux/amd64` and `linux/arm64` platform manifests are present. The job fails the workflow if either is missing.

### Multi-Arch Build Approach
- **D-10:** Per-arch builds run on **native runners** in a matrix: `linux/amd64` on `ubuntu-latest`, `linux/arm64` on `ubuntu-24.04-arm` (free for public repos). No QEMU emulation. Each per-arch build pushes by digest only (`outputs: type=image,push-by-digest=true,name-canonical=true`). A third `merge` job runs `docker buildx imagetools create --tag ghcr.io/<owner>/vici:sha-<short>` to publish the multi-arch manifest. Total wall-clock ~3–5 min vs ~10–12 min for QEMU.
- **D-11:** Build cache is **GHA cache, scoped per-arch**: `cache-from: type=gha,scope=amd64` (or `arm64`) and `cache-to: type=gha,mode=max,scope=<arch>`. Matches `cd-base.yml:67-68` precedent. Repo quota (~10GB) is fine for a small Python image.
- **D-12:** Concurrency is **no cancellation**: `concurrency: { group: ghcr-${{ github.ref }}, cancel-in-progress: false }`. Pushes queue and run sequentially; every SHA on `main` history gets its image. Cancelling in-progress would break the "every main SHA has a pullable image" invariant that the SHA-pinned prod overlay depends on for rollback.
- **D-13:** GHCR namespace in the workflow uses `${{ github.repository_owner }}` (lowercased via `tr '[:upper:]' '[:lower:]'` since GHCR rejects mixed-case). The prod overlay stub uses the literal `ahcarpenter/vici` for operator readability (see D-05). If the repo ever transfers, the workflow auto-adapts and the prod overlay gets a one-line update at that time.
- **D-14:** SBOM and SLSA provenance attestations are **enabled** in Phase 5: `provenance: mode=max` and `sbom: true` on the `docker/build-push-action@v6` step. This folds the deferred todo `260501-sbom-provenance-attestations.md` into Phase 5 since the build infrastructure is being authored from scratch and the flags are additive. The verify job's jq query must filter on `manifests[].platform.architecture != "unknown"` for the platform-presence assertion AND assert that `manifests[].mediaType` includes `application/vnd.in-toto+json` entries (one per platform) for the attestation-presence assertion. A brief operator-facing verification note goes in the README's deployment section.

### Workflow File Structure
- **D-15:** Single extended `.github/workflows/ci.yml`. The existing lint/format/pip-audit/pytest jobs stay; new jobs added: `compose-validate` (runs on PRs and main; runs `docker compose ... config --quiet` for both base and base+prod), `build-amd64` and `build-arm64` (matrix; gated `if: github.event_name != 'pull_request'` so PRs skip), `merge` (combines digests into multi-arch manifest), and `verify` (separate runner, no GHCR creds, asserts platform + attestation manifests).

### Legacy CD Deletion Scope
- **D-16:** Delete the four GKE-targeted workflow files: `.github/workflows/cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`. The infrastructure those workflows reference (`infra/`, `helm/`, `k8s/`, ESO config, `render.yaml`, `Pulumi.*.yaml`) stays untouched until Phase 9 INFRA-01.
- **D-17:** Scrub stale GKE-era secret references from any **remaining** workflow YAML — `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, `PULUMI_CONFIG_PASSPHRASE` `secrets:` declarations. The secrets stay defined in GitHub Settings (out of repo scope) but the workflow YAML stops referencing them.
- **D-18:** PLAN.md's acceptance criteria must include a manual operator-action note: branch protection rules and required-status-check rulesets that reference the deleted `cd-prod` / `cd-staging` jobs need to be updated in GitHub Settings → Branches before merge of the Phase 5 PR. Phase 5 cannot edit GitHub Settings programmatically; the planner must flag this as a blocking pre-merge step.

### Claude's Discretion
- Exact pinned `uses:` versions for `docker/setup-buildx-action`, `docker/metadata-action`, `docker/login-action`, `docker/build-push-action` — pick latest stable major (v5 / v6 as appropriate) and pin to the major.
- Verify-job timeout — pick a sensible default (10 min covers any GHCR cold-pull edge case).
- Whether the `verify` job needs `docker login` to GHCR for the namespace-check edge case where the package is still private at first push — workflow can defensively skip the verify on the very first push only (gate via `continue-on-error` on first run, or just document that the public-toggle step happens before the second push). Planner picks.
- Exact `jq` query syntax for the manifest-inspection assertions — `[.manifests[].platform.architecture] | sort` style, planner picks.

### Folded Todos
- **`260501-sbom-provenance-attestations.md`** — originally deferred during v1.1 scoping to keep Phase 5 focused. Folded back in because the build infrastructure (`ci.yml` build/push steps) is being authored from scratch in Phase 5 and the change is purely additive (`provenance: mode=max` + `sbom: true` flags + verify-job assertion update). Filename hint in the todo points at `release.yml` but Phase 5 uses a single extended `ci.yml` — the planner should rename the file reference. The deferred todo's acceptance criteria flow directly into D-14.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements
- `.planning/ROADMAP.md` §"Phase 5: GHCR Image Distribution & CI Validation" — phase goal and four success criteria
- `.planning/REQUIREMENTS.md` §"CI / Image Distribution (CI)" — CI-01 (release workflow), CI-02 (SHA tagging, no `:latest`), CI-03 (compose validation on every push), CI-04 (cd-*.yml deletion)
- `.planning/PROJECT.md` §"Current Milestone: v1.1 De-platform — Docker-Only Base" — milestone goal and target features

### Codebase intel
- `.planning/codebase/INTEGRATIONS.md` §"CI/CD" — current CI surface (ci.yml lint/test, cd-* GKE deploy chain, Pulumi state, WIF auth)
- `.planning/codebase/STACK.md` — Python 3.12 + uv + FastAPI runtime context (informs Dockerfile understanding)

### Existing CI / build artifacts (touched by this phase)
- `.github/workflows/ci.yml` — existing lint/format/pip-audit/pytest workflow; Phase 5 extends it
- `.github/workflows/cd-base.yml` — reusable GKE-deploy workflow; **DELETE in Phase 5**
- `.github/workflows/cd-dev.yml` — dev-stack deploy trigger; **DELETE in Phase 5**
- `.github/workflows/cd-staging.yml` — staging-stack deploy trigger; **DELETE in Phase 5**
- `.github/workflows/cd-prod.yml` — prod-stack deploy trigger (with environment gate); **DELETE in Phase 5**
- `Dockerfile` — multi-stage Python 3.12-slim build (uv-based); Phase 5 publishes this image but does not modify it
- `docker-compose.yml` — current 8-service base compose; Phase 5 validates it but does not modify it
- `pyproject.toml` / `uv.lock` — build context for the Dockerfile

### Folded todo source
- `.planning/todos/pending/260501-sbom-provenance-attestations.md` — defines the SBOM + provenance acceptance criteria now folded into D-14

### Implementation references (downstream researcher should fetch via Context7 / web)
- `docker/build-push-action@v6` README — multi-arch build, cache modes, provenance/sbom flags, push-by-digest pattern
- `docker/metadata-action@v5` README — `type=sha,prefix=sha-,format=short` tag spec
- `docker/setup-buildx-action@v3` README — buildx driver setup
- Docker Docs §"Multi-platform images" — canonical split-runner + manifest-merge pattern (matches D-10)
- GitHub Docs §"Publishing Docker images to GHCR" — `permissions: { packages: write }`, `GITHUB_TOKEN` auth, public-package toggle
- GitHub Actions §"`ubuntu-24.04-arm` runners" — free arm64 runners for public repos

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`Dockerfile`**: already multi-stage (builder → runtime), uv-based, non-root user (`appuser`), HEALTHCHECK probes `/health`, CMD runs uvicorn. Production-ready as-is for Phase 5 publish. Builds clean on both amd64 and arm64 (no platform-specific binaries; uv-resolved deps in `uv.lock` are platform-portable for the runtime targets).
- **`.github/workflows/ci.yml`**: current pattern uses `astral-sh/setup-uv@v5` with `enable-cache: true`, runs `uv sync --frozen` then ruff + pytest with SQLite-based test fixtures. Phase 5 keeps this surface untouched and adds new jobs alongside.
- **`.github/workflows/cd-base.yml:48-68`**: existing pattern for `git rev-parse --short=7 HEAD` → `steps.sha.outputs.sha`, `docker/setup-buildx-action@v3`, `docker/build-push-action@v6` with `cache-from: type=gha`, `cache-to: type=gha,mode=max`. Phase 5 reuses these patterns but retargets to GHCR and splits into native-arch matrix.

### Established Patterns
- **`uses:` major-version pinning**: existing workflows pin to majors (`@v4`, `@v5`, `@v6`). Phase 5 follows.
- **7-char short SHA as image identity**: `cd-base.yml:49` sets the precedent. Phase 5 inherits.
- **GHA cache via `type=gha`**: `cd-base.yml:67-68` sets the precedent. Phase 5 extends with per-arch `scope=` to avoid cross-arch cache collisions.
- **SQLite for CI tests**: `ci.yml:39` uses `DATABASE_URL: sqlite+aiosqlite:///./test.db` to avoid service containers. Phase 5's compose-validate job is similarly self-contained — no service containers needed; `docker compose config` is a static parse.
- **Fail-fast credential validation**: `Settings._validate_required_credentials` (Phase 02.11) precedent for fail-loud-on-missing-env. The `${GIT_SHA:?...}` substitution mirrors this.

### Integration Points
- **`Dockerfile`** is the build context for the new GHCR publish — no changes required.
- **`.github/workflows/ci.yml`** is the workflow that gets extended (not a new `release.yml`).
- **`docker-compose.yml`** is the base file that the new compose-validate step parses — no changes required in Phase 5.
- **`docker-compose.prod.yml`** is **created** by Phase 5 as an image-only stub; Phase 6 expands it.
- **GitHub Settings (out of repo)** — manual operator step for (a) GHCR package visibility toggle to public after first push, (b) branch protection rule update to remove deleted `cd-*` required checks. PLAN.md must flag both.

</code_context>

<specifics>
## Specific Ideas

- Image namespace: `ghcr.io/ahcarpenter/vici` (literal in prod overlay; `${{ github.repository_owner }}` lowercased in workflow).
- SHA tag prefix: `sha-` (matches roadmap success criterion #1 verbatim — `sha-<short>`, not `<short>` or `git-<short>`).
- Tag format: 7-char short SHA via `git rev-parse --short=7 HEAD` or `docker/metadata-action@v5` with `type=sha,prefix=sha-,format=short`.
- Native arm64 runner: `ubuntu-24.04-arm` (GitHub free public-repo offering — confirm availability with the project's runner tier; fall back to QEMU if not available, but planner should default to native).
- Concurrency group: `ghcr-${{ github.ref }}` (per-ref, not global — allows `main` and tag pushes to run independently).
- Verify-job tooling: `docker buildx imagetools inspect --raw <ref>` piped through `jq`. Asserts both `[.manifests[] | select(.platform.architecture != "unknown") | .platform.architecture]` contains `amd64` and `arm64`, and `[.manifests[] | select(.mediaType == "application/vnd.in-toto+json")] | length` is `>= 2`.

</specifics>

<deferred>
## Deferred Ideas

- **PR-time image build verification** (multi-arch buildx with `--push=false` to catch Dockerfile breakage before merge). Captured during the triggers discussion. Adds ~5–10 min per PR; defensible if Dockerfile churn becomes frequent. Track as a new todo (`pending/`) for future consideration; does NOT belong in Phase 5.
- **Tighten `pip-audit` to hard-fail** (currently `continue-on-error: true` in `ci.yml:30`). Already captured in the Phase 999.1 backlog (`.planning/phases/999.1-concerns-remediation-close-outstanding-items-from-2026-04-22/`). Out of scope for Phase 5.
- **Cosign image signing** (supply-chain hardening beyond SBOM/provenance). Already deferred at the milestone level (`REQUIREMENTS.md` §"Future Requirements"). Not Phase 5.
- **OCI artifact retention policy** for old SHA-tagged images (every push leaves a permanent image; over time the GHCR namespace accumulates). Not in any current requirement; raise during a future ops/cleanup phase if storage becomes a concern.

</deferred>

---

*Phase: 5-GHCR Image Distribution & CI Validation*
*Context gathered: 2026-05-01*
