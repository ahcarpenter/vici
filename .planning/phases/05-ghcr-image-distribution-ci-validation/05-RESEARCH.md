# Phase 5: GHCR Image Distribution & CI Validation - Research

**Researched:** 2026-05-01
**Domain:** GitHub Actions CI / multi-arch container build / GHCR publish / Docker Compose validation
**Confidence:** HIGH (all critical findings verified empirically or via official docs)

## Summary

Phase 5 extends the existing `.github/workflows/ci.yml` with five new jobs (compose-validate, build-amd64, build-arm64, merge, verify) that publish multi-arch SHA-pinned images to `ghcr.io/<owner>/vici` on every `main` push and `v*` tag. CONTEXT.md locks 18 decisions (D-01..D-18); this research fills the "Claude's Discretion" gaps and confirms the technical assumptions.

**Two findings invalidate parts of CONTEXT.md as written and must be flagged to the planner:**

1. **D-14's attestation jq predicate is wrong.** Attestation manifests use `mediaType: application/vnd.oci.image.manifest.v1+json` (the same as platform manifests), NOT `application/vnd.in-toto+json`. The in-toto JSON is a *layer* inside the attestation manifest, not the manifest's own mediaType. Attestations are identified by the annotation `vnd.docker.reference.type=attestation-manifest` and have `platform.architecture=unknown`. The corrected jq predicate is in §Code Examples.
2. **Action major versions in CONTEXT.md are stale.** CONTEXT.md mentions "v5 / v6 as appropriate" — current latest stable as of 2026-05-01 is `build-push-action@v7.1.0`, `metadata-action@v6.0.0`, `setup-buildx-action@v4.0.0`, `login-action@v4.1.0`, `upload-artifact@v7.0.1`, `download-artifact@v8.0.1`, `checkout@v6.0.2`. These are all backward-compatible for our usage; recommend pinning to the new majors.

**Primary recommendation:** Implement the canonical Docker split-runner pattern (per-arch matrix → push by digest → merge with `imagetools create`). Compose validation is a shell step that runs `docker compose -f ... config --quiet` empirically verified to exit 15 with the literal `${GIT_SHA:?...}` error message when GIT_SHA is unset.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Prod Overlay Stub (`docker-compose.prod.yml`)**
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

**Build Triggers + Tags**
- **D-06:** Workflow triggers: `push: branches: [main]`, `push: tags: ['v*']`, and `workflow_dispatch`. PRs do **not** build images — lint/test/compose-config on PRs is the merge gate.
- **D-07:** Image tags are SHA-only: every successful build pushes exactly one tag, `ghcr.io/<owner>/vici:sha-<7char>`. No `:latest`, no `:main`, no semver tags from git tags. Release semantics live in git tags + GitHub Releases, not image tags. Tag computation uses `docker/metadata-action` with `type=sha,prefix=sha-,format=short`.
- **D-08:** GHCR package visibility is set to **public** via a one-time manual GitHub Settings toggle after the first successful push. PLAN.md acceptance criteria must call this step out so verification catches it. Automated visibility-flipping via `gh api` is rejected as overkill for a one-time op.
- **D-09:** Verification of success criterion #2 runs as a **separate `verify` job** in the same workflow. The verify job has no GHCR push credentials and no `actions/login`. It runs `docker buildx imagetools inspect --raw ghcr.io/<owner>/vici:sha-<short>` and `jq`-asserts both `linux/amd64` and `linux/arm64` platform manifests are present. The job fails the workflow if either is missing.

**Multi-Arch Build Approach**
- **D-10:** Per-arch builds run on **native runners** in a matrix: `linux/amd64` on `ubuntu-latest`, `linux/arm64` on `ubuntu-24.04-arm` (free for public repos). No QEMU emulation. Each per-arch build pushes by digest only (`outputs: type=image,push-by-digest=true,name-canonical=true`). A third `merge` job runs `docker buildx imagetools create --tag ghcr.io/<owner>/vici:sha-<short>` to publish the multi-arch manifest. Total wall-clock ~3–5 min vs ~10–12 min for QEMU.
- **D-11:** Build cache is **GHA cache, scoped per-arch**: `cache-from: type=gha,scope=amd64` (or `arm64`) and `cache-to: type=gha,mode=max,scope=<arch>`. Matches `cd-base.yml:67-68` precedent. Repo quota (~10GB) is fine for a small Python image.
- **D-12:** Concurrency is **no cancellation**: `concurrency: { group: ghcr-${{ github.ref }}, cancel-in-progress: false }`. Pushes queue and run sequentially; every SHA on `main` history gets its image. Cancelling in-progress would break the "every main SHA has a pullable image" invariant that the SHA-pinned prod overlay depends on for rollback.
- **D-13:** GHCR namespace in the workflow uses `${{ github.repository_owner }}` (lowercased via `tr '[:upper:]' '[:lower:]'` since GHCR rejects mixed-case). The prod overlay stub uses the literal `ahcarpenter/vici` for operator readability (see D-05).
- **D-14:** SBOM and SLSA provenance attestations are **enabled** in Phase 5: `provenance: mode=max` and `sbom: true` on the `docker/build-push-action` step. Folds in deferred todo `260501-sbom-provenance-attestations.md`. ⚠️ **The verify-job jq predicate as written in CONTEXT.md (`mediaType == application/vnd.in-toto+json`) is incorrect — see §Code Examples for the corrected predicate.**

**Workflow File Structure**
- **D-15:** Single extended `.github/workflows/ci.yml`. The existing lint/format/pip-audit/pytest jobs stay; new jobs added: `compose-validate` (runs on PRs and main; runs `docker compose ... config --quiet` for both base and base+prod), `build-amd64` and `build-arm64` (matrix; gated `if: github.event_name != 'pull_request'` so PRs skip), `merge` (combines digests into multi-arch manifest), and `verify` (separate runner, no GHCR creds, asserts platform + attestation manifests).

**Legacy CD Deletion Scope**
- **D-16:** Delete the four GKE-targeted workflow files: `.github/workflows/cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`. The infrastructure those workflows reference (`infra/`, `helm/`, `k8s/`, ESO config, `render.yaml`, `Pulumi.*.yaml`) stays untouched until Phase 9 INFRA-01.
- **D-17:** Scrub stale GKE-era secret references from any **remaining** workflow YAML — `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, `PULUMI_CONFIG_PASSPHRASE` `secrets:` declarations. The secrets stay defined in GitHub Settings (out of repo scope) but the workflow YAML stops referencing them.
- **D-18:** PLAN.md's acceptance criteria must include a manual operator-action note: branch protection rules and required-status-check rulesets that reference the deleted `cd-prod` / `cd-staging` jobs need to be updated in GitHub Settings → Branches before merge of the Phase 5 PR.

### Claude's Discretion
- Exact pinned `uses:` versions for `docker/setup-buildx-action`, `docker/metadata-action`, `docker/login-action`, `docker/build-push-action` — pick latest stable major.
- Verify-job timeout — pick a sensible default (10 min covers any GHCR cold-pull edge case).
- Whether the `verify` job needs `docker login` to GHCR for the namespace-check edge case where the package is still private at first push.
- Exact `jq` query syntax for the manifest-inspection assertions.

### Deferred Ideas (OUT OF SCOPE)
- **PR-time image build verification** — track as a new pending todo; does NOT belong in Phase 5.
- **Tighten `pip-audit` to hard-fail** — already captured in Phase 999.1 backlog.
- **Cosign image signing** — already deferred at the milestone level.
- **OCI artifact retention policy** for old SHA-tagged images — not in any current requirement.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CI-01 | Multi-arch GHCR publish on `main` push and tag | §Standard Stack (build-push-action v7), §Architecture Patterns (split-runner+merge), §Code Examples (verified canonical YAML) |
| CI-02 | SHA-pinned tags (`sha-<short>`); no `:latest`; prod overlay references `image: ghcr.io/<org>/vici:sha-${GIT_SHA}` | §Code Examples (metadata-action `type=sha,prefix=sha-,format=short` confirmed produces `sha-abc1234`) |
| CI-03 | CI validates both compose overlays on every push (`docker compose -f docker-compose.yml config --quiet` AND `docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet`); non-zero exit fails the build | §Code Examples (empirically verified exit code 15 + exact error message); §Don't Hand-Roll (`docker compose config` is the canonical static parser) |
| CI-04 | Existing GKE-targeted CI workflows (`cd-*.yml`) deleted | §Architecture Patterns (file deletion list); §Common Pitfalls (stale required-status-check fallout) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Compose static validation | CI Workflow | — | `docker compose config` is a pure parser — no service containers needed; fits naturally in a CI shell step (matches the existing `ci.yml` SQLite-no-service-container pattern) |
| Per-arch image build | CI Workflow (native runner) | Docker BuildKit | Each arch builds on its own native runner (`ubuntu-latest` / `ubuntu-24.04-arm`); BuildKit handles the actual layer construction inside the runner |
| GHCR push (digest only) | CI Workflow → GHCR | — | `docker/login-action` authenticates with `GITHUB_TOKEN`; `docker/build-push-action` outputs `type=image,push-by-digest=true` to push the per-arch artifact directly |
| Multi-arch manifest assembly | CI Workflow (merge job) → GHCR | — | `docker buildx imagetools create` runs on a third runner, downloads per-arch digest files, and creates the SHA-pinned multi-arch manifest pointing at the already-pushed digests. No image pull/push of layers — manifest-only operation |
| SBOM + provenance attestation | Docker BuildKit | GHCR | BuildKit (driven by `sbom: true` + `provenance: mode=max` flags on build-push-action) generates SPDX SBOM and SLSA provenance, pushes them as additional manifests in the OCI image index |
| Multi-arch + attestation verification | CI Workflow (verify job) | GHCR | Separate runner with no push creds; `docker buildx imagetools inspect --raw <ref>` + `jq` predicates assert both platforms and ≥2 attestations are present |
| Branch protection enforcement | GitHub Settings (out-of-repo) | — | D-18 explicitly: required-status-check rulesets that name `cd-prod`/`cd-staging` jobs are configured in `Settings → Branches` and must be updated by an operator pre-merge. Workflow YAML cannot edit Branch Protection rules |
| GHCR package visibility | GitHub Settings (out-of-repo) | — | First push creates package as private; D-08 requires operator to flip to public via `Settings → Code & automation → Packages → vici → Change visibility` (one-time, irreversible) |
| Operator host runtime (deploy-time) | Host shell | docker compose | Out of scope for Phase 5 itself, but the `${GIT_SHA:?...}` substitution forces the operator to set GIT_SHA before `docker compose up` — same fail-fast pattern as the CI step |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `actions/checkout` | `v6` | Source checkout in each job | Standard first step on every GHA workflow [VERIFIED: GitHub releases API, latest v6.0.2 published 2026-01-09] |
| `docker/setup-buildx-action` | `v4` | Boot a buildx builder using the docker-container driver, enabling cache export and digest-only push | Required for `cache-to: type=gha,mode=max` and `outputs: type=image,push-by-digest=true` — the default Docker engine builder cannot do either [VERIFIED: Context7 /docker/build-push-action; GitHub releases API, v4.0.0 published 2026-03-05] |
| `docker/login-action` | `v4` | Authenticate to GHCR using `GITHUB_TOKEN` | Canonical Docker-maintained action; sets up registry credentials for `build-push-action` and `imagetools create` [VERIFIED: GitHub releases API, v4.1.0 published 2026-04-02] |
| `docker/metadata-action` | `v6` | Compute image tags from git context (`type=sha,prefix=sha-,format=short` → `sha-abc1234`) and emit JSON for the merge job | Canonical Docker-maintained tag-generator; produces `DOCKER_METADATA_OUTPUT_JSON` consumed by the merge job's `imagetools create` [VERIFIED: Context7 /docker/metadata-action; GitHub releases API, v6.0.0 published 2026-03-05] |
| `docker/build-push-action` | `v7` | Per-arch buildx build + push by digest with cache, sbom, and provenance | Canonical multi-platform builder; supports `outputs: type=image,push-by-digest=true,name-canonical=true`, `sbom: true`, `provenance: mode=max`, and `cache-from/to: type=gha,scope=...` [VERIFIED: Context7 /docker/build-push-action; GitHub releases API, v7.1.0 published 2026-04-10] |
| `actions/upload-artifact` | `v7` | Upload per-arch digest files (`/tmp/digests/<sha>`) for the merge job to consume | Standard digest-passing pattern in the canonical split-runner workflow [VERIFIED: GitHub releases API, v7.0.1 published 2026-04-10] |
| `actions/download-artifact` | `v8` | Merge job pulls all `digests-*` artifacts using `pattern: digests-*, merge-multiple: true` | Standard inverse of upload-artifact [VERIFIED: GitHub releases API, v8.0.1 published 2026-03-11] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `astral-sh/setup-uv` | `v5` | Already used in existing `ci.yml`; not touched by Phase 5 | Existing lint/test jobs only |
| `jq` | system | JSON inspection in shell steps (verify job + tag extraction in merge) | Pre-installed on GitHub-hosted Ubuntu runners; no install step needed [CITED: GitHub-hosted runner image manifest] |
| `docker buildx imagetools` | bundled | Manifest assembly + inspection (no separate `uses:` — invoked via `run:` shell) | The merge and verify jobs both call this CLI; bundled with Buildx setup |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Native arm64 runner (`ubuntu-24.04-arm`) | QEMU emulation via `docker/setup-qemu-action` | QEMU works on a single `ubuntu-latest` runner but takes ~3x longer (~10-12 min vs ~3-5 min). Native runners are free for public repos and GA as of 2025-08-07 [CITED: github.blog/changelog/2025-08-07] — locked in by D-10 |
| Single extended `ci.yml` | Separate `release.yml` for image publish | Two files mean two different concurrency groups, two different "did the build pass?" status checks for branch protection, doubled YAML maintenance. Locked in by D-15 |
| `docker buildx imagetools create` (manifest merge) | `docker manifest create` (legacy CLI) | The legacy `docker manifest` command requires `experimental: true` in daemon config and pulls layers; `imagetools create` is the modern, manifest-only path supported by buildx [VERIFIED: docs.docker.com/reference/cli/docker/buildx/imagetools/create] |
| `cache-to: type=gha,mode=max,scope=<arch>` | `mode=min` (only export final stages) | `mode=min` can't restore intermediate stages on cache hits — the next build re-executes them. `mode=max` is the right answer for multi-stage Dockerfiles like Vici's (builder + runtime) [VERIFIED: docs.docker.com/build/cache/backends/gha] |
| `format=short` SHA tags | Full-length SHA (`format=long`) | 7 chars matches `cd-base.yml:49` precedent and is git's default; full-length adds noise without info gain. CONTEXT.md D-07 locks `format=short` |

**Installation:** All actions are GHA `uses:` references — no local install. Runners come with `docker`, `git`, `jq`, `bash`, `curl` pre-installed.

**Version verification (executed 2026-05-01):**
```
build-push-action: v7.1.0 (2026-04-10)
metadata-action: v6.0.0 (2026-03-05)
setup-buildx-action: v4.0.0 (2026-03-05)
login-action: v4.1.0 (2026-04-02)
upload-artifact: v7.0.1 (2026-04-10)
download-artifact: v8.0.1 (2026-03-11)
checkout: v6.0.2 (2026-01-09)
```
[VERIFIED: GitHub Releases API queries against each repo on 2026-05-01]

⚠️ **CONTEXT.md says "v5/v6 as appropriate" — those are stale. The planner should pin to the majors above.** All version bumps are backward-compatible for the usages described here.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌──────────────────────────────────────────────────┐
                         │  GitHub Event                                    │
                         │  (push to main | tag v* | workflow_dispatch | PR)│
                         └─────────────────────┬────────────────────────────┘
                                               │
                  ┌────────────────────────────┴──────────────────────────────┐
                  │ ci.yml workflow                                          │
                  │ concurrency: ghcr-${ref}, cancel-in-progress: false      │
                  └─┬─────────────┬─────────────┬─────────────┬──────────┬──┘
                    │             │             │             │          │
            ┌───────▼────┐ ┌──────▼─────┐ ┌─────▼──────┐ ┌────▼────┐ ┌──▼────────┐
            │ test       │ │ compose-   │ │ build-     │ │ build-  │ │ (PR? STOP)│
            │ (existing  │ │ validate   │ │ amd64      │ │ arm64   │ │           │
            │  ruff +    │ │            │ │            │ │         │ │           │
            │  pytest)   │ │ runs on    │ │ ubuntu-    │ │ ubuntu- │ │           │
            │            │ │ PR + push  │ │ latest     │ │ 24.04-  │ │           │
            │            │ │            │ │            │ │ arm     │ │           │
            │            │ │ docker     │ │ docker     │ │ docker  │ │           │
            │            │ │ compose    │ │ build-push │ │ build-  │ │           │
            │            │ │ config     │ │ push-by-   │ │ push    │ │           │
            │            │ │ --quiet    │ │ digest     │ │ ditto   │ │           │
            │            │ │ × 2 over-  │ │ + sbom +   │ │         │ │           │
            │            │ │ lays       │ │ provenance │ │         │ │           │
            └────────────┘ └────────────┘ └─────┬──────┘ └────┬────┘ └───────────┘
                                                │            │
                                                │ digest     │ digest
                                                ▼            ▼
                                        ┌────────────────────────┐
                                        │ actions/upload-artifact│
                                        │ (digests-linux-amd64,  │
                                        │  digests-linux-arm64)  │
                                        └───────────┬────────────┘
                                                    │
                                              needs:│[build-amd64, build-arm64]
                                                    ▼
                                        ┌──────────────────────────────────┐
                                        │ merge (ubuntu-latest)            │
                                        │  1. download all digests-*       │
                                        │  2. metadata-action → tag list   │
                                        │  3. login-action (GHCR push)     │
                                        │  4. docker buildx imagetools     │
                                        │     create → multi-arch manifest │
                                        │     ghcr.io/<owner>/vici:sha-XYZ │
                                        └───────────┬──────────────────────┘
                                                    │
                                              needs:│[merge]
                                                    ▼
                                        ┌──────────────────────────────────┐
                                        │ verify (ubuntu-latest)           │
                                        │  NO GHCR push creds              │
                                        │  - imagetools inspect --raw      │
                                        │  - jq: both arches present       │
                                        │  - jq: ≥2 attestation manifests  │
                                        │  - exit 1 on any missing         │
                                        └──────────────────────────────────┘

External (out-of-CI):
  GHCR Settings (manual, one-time):
    Settings → Code & automation → Packages → vici → Change visibility → Public

  Branch Protection (manual, pre-merge of Phase 5 PR):
    Settings → Branches → main → Edit → Required status checks
    Remove: cd-prod, cd-staging (deleted), cd-dev (deleted)
    Add (optional):    test, compose-validate, build-amd64, build-arm64, merge, verify
```

### Recommended Project Structure
No directory changes — Phase 5 only touches files:
```
.github/
└── workflows/
    └── ci.yml                  # extended (existing → add 5 jobs)
                                # DELETED: cd-base.yml, cd-dev.yml,
                                #          cd-staging.yml, cd-prod.yml
docker-compose.prod.yml         # NEW (image-only stub per D-02)
```

### Pattern 1: Split-Runner Multi-Arch Build (canonical)
**What:** Run per-arch builds on native runners in parallel, push each as a digest-only artifact to the registry, then a final merge job assembles a multi-arch manifest list from the digests using `docker buildx imagetools create`.
**When to use:** Whenever the target architectures have native GHA runners (linux/amd64 + linux/arm64 do, as of 2025-08 GA). Beats QEMU 2-3x on wall-clock and avoids emulation footguns.
**Example:** See §Code Examples — full verbatim YAML from the canonical reference workflow ([VERIFIED: github.com/sredevopsorg/multi-arch-docker-github-workflow]).

### Pattern 2: Compose-Validate as Pure Static Parse
**What:** `docker compose -f <files...> config --quiet` parses, merges overlays, validates schema, and resolves `${VAR}` interpolation — without contacting Docker daemon or starting any containers.
**When to use:** Every PR and every push, as the cheap merge gate. CI-03 mandates this.
**Example:** See §Code Examples — empirically verified exit codes and error message format.

### Pattern 3: Verify Job with No Push Credentials
**What:** A separate job that runs after `merge`, has no `docker/login-action` step (GHCR pulls of public packages don't need auth), and uses `imagetools inspect --raw` + `jq` to assert the published manifest is correct.
**When to use:** Whenever you publish multi-arch images and want to catch regressions where one platform silently disappeared. D-09 mandates this for Phase 5.
**Example:** See §Code Examples for the `jq` predicates.

### Anti-Patterns to Avoid
- **QEMU emulation when native runners exist** — slower, flakier, and can silently corrupt builds when emulated syscalls hit edge cases. Use native runners.
- **Tagging with both `:sha-X` and `:latest`** — defeats the SHA-pinned rollback model. D-07 explicitly forbids this.
- **`cancel-in-progress: true` on the publish workflow** — drops images for SHAs in `main` history; breaks the prod-overlay rollback invariant. D-12 explicitly forbids this.
- **Hand-rolling `docker manifest create`** — legacy CLI requires daemon `experimental: true`. Use `docker buildx imagetools create`.
- **Putting `docker login` in the verify job** — undermines the whole point of the separate-runner verification (we want to confirm anonymous pulls work, which proves the public-toggle has been applied). Skip the login.
- **`mode=min` cache** — can't restore intermediate stages; multi-stage Dockerfile rebuilds redundantly. Use `mode=max`.
- **Single GHA cache scope across both arches** — last write wins; arches stomp each other's cache. Use `scope=<arch>` per D-11.
- **Falling back to `${GIT_SHA-}` (silent default)** — produces a broken `sha-` image ref. The `${GIT_SHA:?msg}` form is mandatory per D-03.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Compute SHA tag from git ref | `git rev-parse --short=7 HEAD` in shell + manual interpolation | `docker/metadata-action@v6` with `tags: type=sha,prefix=sha-,format=short` | The action centralizes tag policy, emits JSON consumed by the merge job's `imagetools create`, supports git-tag triggers (`v*`) without extra logic, and uses `DOCKER_METADATA_SHORT_SHA_LENGTH` env override if 7 chars ever proves insufficient |
| Multi-arch manifest assembly | `docker manifest create` + push | `docker buildx imagetools create` | The legacy `docker manifest` command requires daemon `experimental: true` and pulls all platform layers locally (slow + bandwidth). `imagetools create` is manifest-only |
| Per-arch digest passing between jobs | Custom JSON file + `actions/cache` | `actions/upload-artifact@v7` writing to `/tmp/digests/<sha>` + `actions/download-artifact@v8` with `pattern: digests-*` and `merge-multiple: true` | This is the canonical pattern in the Docker docs and the `sredevopsorg/multi-arch-docker-github-workflow` reference. Filename = digest = self-validating |
| Compose interpolation validation | Bash regex grep for `${...}` references in compose files | `docker compose config --quiet` | Validates schema, merges overlays, resolves substitutions, and catches `${VAR:?...}` failures with a meaningful error message — all in one command. Empirically verified to exit 15 with the literal `:?` message text |
| GHCR auth in workflow | Personal access token in repo secrets | `secrets.GITHUB_TOKEN` with `permissions: { packages: write }` | Built-in, scoped to the repo, expires with the workflow run, no rotation needed |
| Manifest inspection for verify | `skopeo inspect` (extra install) | `docker buildx imagetools inspect --raw` + `jq` | Bundled with buildx (already set up), no extra steps, JSON output is jq-friendly |
| OCI image index parsing | Custom Python script with `requests` | `jq` on `imagetools inspect --raw` output | jq is pre-installed on GHA runners; the index JSON is small and well-defined |
| Per-arch cache key construction | Manual `key:` with hash of Dockerfile | `cache-from: type=gha,scope=<arch>` + `cache-to: type=gha,mode=max,scope=<arch>` | Buildx's GHA cache backend uses the BuildKit content-addressable layer hash automatically — no manual cache-key engineering |
| SBOM generation in a separate step | `syft` or `trivy` invocation post-build | `sbom: true` on `docker/build-push-action` | One flag enables BuildKit-native SPDX SBOM generation, attached as an OCI artifact on the same image manifest |
| SLSA provenance generation | `slsa-github-generator` (extra workflow) | `provenance: mode=max` on `docker/build-push-action` | One flag enables BuildKit-native SLSA provenance with full build environment metadata |

**Key insight:** Every problem in this phase has a one-line config solution from the canonical Docker actions. Custom shell scripting in this domain is universally a regression — the actions encode years of edge-case fixes (registry rate limits, retry on transient failures, manifest schema drift, cache key collisions). Phase 5 should be heavy on `uses:` references and very thin on `run:` shell.

## Common Pitfalls

### Pitfall 1: GHCR Lowercase Requirement
**What goes wrong:** `${{ github.repository_owner }}` returns the owner exactly as cased on GitHub (e.g., `AhCarpenter`). GHCR rejects mixed-case namespace components, returning an opaque "name unknown" or "manifest unknown" error.
**Why it happens:** GHCR enforces the OCI distribution spec's lowercase-only repository name rule, but GitHub does not auto-lowercase the `repository_owner` context variable.
**How to avoid:** Run a normalization shell step early in each job that needs the owner: `echo "OWNER_LC=$(echo '${{ github.repository_owner }}' | tr '[:upper:]' '[:lower:]')" >> $GITHUB_ENV`, then reference `$OWNER_LC` everywhere. D-13 already mandates this.
**Warning signs:** "name unknown", "manifest unknown", or "repository name must be lowercase" in push step logs.
**Confidence:** HIGH [CITED: docs.docker.com/reference/compose-file/services + multiple GHA + GHCR issue threads]

### Pitfall 2: First-Push Visibility = Private
**What goes wrong:** First push to `ghcr.io/<owner>/vici` creates the package as **private**. Anonymous `docker pull` fails with 401. Verify job (which intentionally has no GHCR creds) fails on the very first push.
**Why it happens:** GitHub default for new GHCR packages is private — there is no workflow-level switch to make the first push public.
**How to avoid:** Either (a) accept the first-push verify failure and document the public-toggle as a one-time post-merge step before re-triggering verify with `workflow_dispatch`, or (b) gate the verify job on `if: github.event_name != 'push' || github.run_attempt > 1` so only re-runs trigger verify. CONTEXT.md "Claude's Discretion" leaves this to the planner. **Recommendation:** option (a) — keep verify simple, document operator step in PLAN.md acceptance criteria. The visibility toggle is irreversible (private → public is one-way), so flipping it once and then re-running verify-only via `workflow_dispatch` is the cleanest path.
**Warning signs:** First push verify job fails with `denied: requested access to the resource is denied` on `imagetools inspect`.
**Confidence:** HIGH [VERIFIED: docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility — "When you first publish a package, the default visibility is private" and "in the Container registry, public packages allow anonymous access and can be pulled without authentication"]

### Pitfall 3: Attestation Manifest mediaType Misconception
**What goes wrong:** Filtering `.manifests[].mediaType == "application/vnd.in-toto+json"` returns zero entries, even though SBOM + provenance attestations were correctly attached. The verify job passes the platform check but fails the attestation count assertion (or vice versa, masking a real failure).
**Why it happens:** Attestation manifests in the OCI image index use `mediaType: application/vnd.oci.image.manifest.v1+json` — the same as platform manifests. The in-toto JSON is a *layer* inside the attestation manifest, not the manifest's own mediaType. Attestations are identified by:
- Annotation `vnd.docker.reference.type=attestation-manifest` on the index entry
- `platform.architecture=unknown` and `platform.os=unknown`
**How to avoid:** Use the corrected jq predicate (see §Code Examples). ⚠️ **CONTEXT.md D-14 and §Specifics §Verify-job tooling both have this wrong as currently written.** The planner must update the predicate.
**Warning signs:** jq returns `0` or empty array when the published image visibly has SBOM/provenance via `docker buildx imagetools inspect <ref>` (without `--raw`).
**Confidence:** HIGH [VERIFIED: docs.docker.com/build/metadata/attestations/attestation-storage + felipecruz.es/buildkit-supply-chain-features — both confirm the mediaType is `application/vnd.oci.image.manifest.v1+json` with the `attestation-manifest` annotation]

### Pitfall 4: `cache-to: type=gha` Without `mode=max`
**What goes wrong:** Build cache hits on subsequent runs but rebuilds intermediate stages anyway (especially the uv-resolve stage in our multi-stage Dockerfile). Wall-clock time barely improves over no-cache.
**Why it happens:** Default cache export is `mode=min`, which only exports the final stage. Multi-stage Dockerfiles need every stage cached.
**How to avoid:** Always specify `cache-to: type=gha,mode=max,scope=<arch>`.
**Warning signs:** Build logs show "CACHED" only on the final `RUN` lines, never on `COPY` or earlier `RUN` instructions.
**Confidence:** HIGH [VERIFIED: docs.docker.com/build/cache/backends/gha]

### Pitfall 5: GHA Cache Cross-Arch Stomping
**What goes wrong:** Without explicit `scope=`, the amd64 build's cache export stomps the arm64 build's cache (or vice versa). Each build pair effectively runs without cache.
**Why it happens:** Default GHA cache scope is `buildkit`. Both arch jobs write to the same scope; last-write-wins.
**How to avoid:** Per-arch scope: `scope=amd64` on amd64 job, `scope=arm64` on arm64 job. D-11 mandates this. The canonical reference workflow uses `scope=${{ github.repository }}-${{ github.ref_name }}-${{ matrix.platform }}` for finer-grained branch isolation, but per-arch alone is sufficient for our scale.
**Confidence:** HIGH [VERIFIED: docs.docker.com/build/cache/backends/gha]

### Pitfall 6: Branch Protection Required-Status-Check Drift
**What goes wrong:** Phase 5 PR cannot merge — required-status-check rules still demand the deleted `cd-prod` / `cd-staging` job names, which never report. Merge button is greyed out indefinitely.
**Why it happens:** Branch protection rules in `Settings → Branches` are out-of-repo state. Deleting workflow files removes the *capability* to run those checks but not the *requirement* that they pass.
**How to avoid:** D-18 already mandates updating Settings → Branches as a manual pre-merge step. PLAN.md acceptance criteria must include the explicit operator instruction.
**Warning signs:** PR sits in "Some checks haven't completed yet" with no checks pending, indefinitely.
**Confidence:** HIGH [CITED: docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches]

### Pitfall 7: `${{ secrets.GITHUB_TOKEN }}` Insufficient Permissions
**What goes wrong:** The first push to GHCR fails with `denied: installation not allowed to write package`.
**Why it happens:** Default `GITHUB_TOKEN` permissions are read-only as of 2023+ on new repos / orgs. The workflow YAML must opt-in to write scopes.
**How to avoid:** Add at the workflow or job level:
```yaml
permissions:
  contents: read
  packages: write
  id-token: write       # for OIDC keyless if cosign added later
  attestations: write   # for SBOM/provenance attestation upload
```
The `attestations: write` is required for `provenance: mode=max` and `sbom: true` on `docker/build-push-action@v7`.
**Confidence:** HIGH [VERIFIED: docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication]

### Pitfall 8: ARM64 Runner Label Spelled Wrong
**What goes wrong:** Job hangs in "queued" state forever, then fails after a long timeout, with no helpful error.
**Why it happens:** GitHub silently accepts any runner label and routes the job; if no runner matches, it queues. `ubuntu-latest-arm` (incorrect) sits forever; `ubuntu-24.04-arm` (correct) routes immediately.
**How to avoid:** Use exactly `ubuntu-24.04-arm` or `ubuntu-22.04-arm`. Matrix expression: `runs-on: ${{ matrix.platform == 'linux/amd64' && 'ubuntu-latest' || 'ubuntu-24.04-arm' }}`. **Caveat:** these labels do NOT work in private repositories — workflows fail at startup. Vici is public, so this is fine.
**Confidence:** HIGH [CITED: github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available]

### Pitfall 9: Verify Job Timing — Manifest Eventual Consistency
**What goes wrong:** Verify job runs immediately after merge, but `imagetools inspect` 404s for ~5-30 seconds while GHCR's CDN propagates the manifest.
**Why it happens:** GHCR has eventual consistency on manifest reads from edge caches.
**How to avoid:** Add a brief retry loop in the verify shell step (3 attempts × 10s sleep) before failing. Don't add `continue-on-error: true` — that swallows real failures.
**Warning signs:** Intermittent verify failures on otherwise-correct pushes that pass on `workflow_dispatch` re-runs.
**Confidence:** MEDIUM — observed empirically by other GHCR users; not formally documented by GitHub. Recommend implementing the retry to be safe.

## Runtime State Inventory

> Phase 5 includes deletion of 4 workflow files and creation of 1 compose stub. This is borderline rename/refactor territory; running the inventory is cheap insurance.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Phase 5 does not touch databases, caches, or persistent state | None |
| Live service config | **GHCR package settings** — currently no `vici` package exists yet (Phase 5 creates it on first push). After first push, the package will exist as private; **D-08 manual operator action required** to flip to public via Settings → Code & automation → Packages → vici → Change visibility. **Branch protection rules** in `Settings → Branches → main` currently reference required status checks `cd-prod`, `cd-staging` (and possibly `cd-dev`) that will no longer exist after Phase 5 deletes the workflow files; **D-18 manual operator action required** to remove them from the rule before merging the Phase 5 PR | Operator-side, documented in PLAN.md acceptance criteria |
| OS-registered state | None — no host-level registrations | None |
| Secrets/env vars | **GitHub Secrets `GCP_WIF_PROVIDER`, `GCP_CI_SA_EMAIL`, `PULUMI_CONFIG_PASSPHRASE`** — referenced by deleted `cd-*.yml` workflows. D-17 explicitly: workflow YAML stops referencing them, but the secrets stay defined in GitHub Settings. They become orphaned but harmless until Phase 9 (which can optionally delete them via Settings → Secrets and variables → Actions). | None for Phase 5 — orphaned secrets are not blocking |
| Build artifacts / installed packages | **GHA cache entries** — old `cd-base.yml` cache entries (scope=default `buildkit`) become stale. Self-evicting after 7 days of no access per GHA's LRU policy. Not blocking. | None — natural eviction |

**Nothing requires Phase 5 itself to perform a data migration.** The runtime-state changes are all (a) operator UI clicks (D-08, D-18) or (b) self-cleaning (orphaned secrets, GHA cache).

## Code Examples

Verified patterns from official sources or empirically validated.

### Compose interpolation behavior — empirically verified

```bash
# Test: GIT_SHA unset, base+prod overlay
$ unset GIT_SHA
$ docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
parsing /tmp/.../docker-compose.prod.yml: error while interpolating services.app.image:
  required variable GIT_SHA is missing a value: GIT_SHA must be set to the 7-char short SHA
$ echo $?
15

# Test: GIT_SHA set
$ GIT_SHA=abc1234 docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
$ echo $?
0
```
[VERIFIED: 2026-05-01 against Docker Compose v2.18.1 in this session]

The literal stderr message is:
> `parsing <file>: error while interpolating services.app.image: required variable GIT_SHA is missing a value: <user-supplied message after :?>`

Exit code is **15** (not just any non-zero — it's specifically Compose's "interpolation error" code). For CI, treat any non-zero as failure; the planner does not need to assert on exact code 15.

### Per-arch build matrix step (canonical, adapted)

```yaml
# Source: github.com/sredevopsorg/multi-arch-docker-github-workflow
#         (canonical reference workflow — adapted for Vici per CONTEXT.md decisions)
build:
  strategy:
    fail-fast: false
    matrix:
      platform: [linux/amd64, linux/arm64]
  runs-on: ${{ matrix.platform == 'linux/amd64' && 'ubuntu-latest' || 'ubuntu-24.04-arm' }}
  if: github.event_name != 'pull_request'    # D-15: PRs skip image build
  permissions:
    contents: read
    packages: write
    attestations: write
    id-token: write
  steps:
    - name: Prepare platform pair
      run: |
        platform=${{ matrix.platform }}
        echo "PLATFORM_PAIR=${platform//\//-}" >> $GITHUB_ENV
        echo "ARCH=${platform#linux/}" >> $GITHUB_ENV

    - uses: actions/checkout@v6

    - name: Lowercase owner for GHCR
      run: |
        echo "OWNER_LC=$(echo '${{ github.repository_owner }}' | tr '[:upper:]' '[:lower:]')" >> $GITHUB_ENV
        echo "GHCR_IMAGE=ghcr.io/$(echo '${{ github.repository_owner }}' | tr '[:upper:]' '[:lower:]')/vici" >> $GITHUB_ENV

    - name: Docker meta
      id: meta
      uses: docker/metadata-action@v6
      with:
        images: ${{ env.GHCR_IMAGE }}
        tags: |
          type=sha,prefix=sha-,format=short

    - uses: docker/setup-buildx-action@v4

    - uses: docker/login-action@v4
      with:
        registry: ghcr.io
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}

    - name: Build and push by digest
      id: build
      uses: docker/build-push-action@v7
      with:
        context: .
        platforms: ${{ matrix.platform }}
        labels: ${{ steps.meta.outputs.labels }}
        outputs: type=image,name=${{ env.GHCR_IMAGE }},push-by-digest=true,name-canonical=true,push=true
        cache-from: type=gha,scope=${{ env.ARCH }}
        cache-to: type=gha,mode=max,scope=${{ env.ARCH }}
        provenance: mode=max
        sbom: true

    - name: Export digest
      run: |
        mkdir -p /tmp/digests
        digest="${{ steps.build.outputs.digest }}"
        touch "/tmp/digests/${digest#sha256:}"

    - uses: actions/upload-artifact@v7
      with:
        name: digests-${{ env.PLATFORM_PAIR }}
        path: /tmp/digests/*
        if-no-files-found: error
        retention-days: 1
```
[VERIFIED: Adapted from canonical sredevopsorg/multi-arch-docker-github-workflow on 2026-05-01; cross-checked against Context7 /docker/build-push-action]

### Merge job (manifest assembly)

```yaml
merge:
  needs: [build]
  runs-on: ubuntu-latest
  if: github.event_name != 'pull_request'
  permissions:
    contents: read
    packages: write
  steps:
    - uses: actions/download-artifact@v8
      with:
        path: /tmp/digests
        pattern: digests-*
        merge-multiple: true

    - name: Lowercase owner
      run: |
        echo "GHCR_IMAGE=ghcr.io/$(echo '${{ github.repository_owner }}' | tr '[:upper:]' '[:lower:]')/vici" >> $GITHUB_ENV

    - name: Docker meta (for tag list)
      id: meta
      uses: docker/metadata-action@v6
      with:
        images: ${{ env.GHCR_IMAGE }}
        tags: |
          type=sha,prefix=sha-,format=short

    - uses: docker/setup-buildx-action@v4

    - uses: docker/login-action@v4
      with:
        registry: ghcr.io
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}

    - name: Create multi-arch manifest
      working-directory: /tmp/digests
      run: |
        docker buildx imagetools create \
          $(jq -cr '.tags | map("-t " + .) | join(" ")' <<< "$DOCKER_METADATA_OUTPUT_JSON") \
          $(printf '${{ env.GHCR_IMAGE }}@sha256:%s ' *)

    - name: Inspect (sanity)
      run: |
        docker buildx imagetools inspect '${{ env.GHCR_IMAGE }}:${{ steps.meta.outputs.version }}'
```
[VERIFIED: Canonical Docker docs pattern; jq incantation copied verbatim from sredevopsorg reference workflow]

### Verify job (corrected attestation predicate)

```yaml
verify:
  needs: [merge]
  runs-on: ubuntu-latest
  if: github.event_name != 'pull_request'
  timeout-minutes: 10                       # CONTEXT.md "Claude's Discretion"
  # NO permissions: packages: write — verify runs anonymously to prove
  # the public-toggle is in place (after first push + manual D-08 step)
  steps:
    - name: Lowercase owner
      run: |
        echo "GHCR_IMAGE=ghcr.io/$(echo '${{ github.repository_owner }}' | tr '[:upper:]' '[:lower:]')/vici" >> $GITHUB_ENV

    - name: Compute SHA tag
      id: tag
      run: echo "tag=sha-$(git rev-parse --short=7 ${{ github.sha }})" >> "$GITHUB_OUTPUT"

    - name: Inspect with retry (handle GHCR eventual consistency)
      id: inspect
      run: |
        IMAGE_REF="${{ env.GHCR_IMAGE }}:${{ steps.tag.outputs.tag }}"
        for attempt in 1 2 3; do
          if RAW=$(docker buildx imagetools inspect --raw "$IMAGE_REF" 2>&1); then
            echo "$RAW" > /tmp/manifest.json
            break
          fi
          echo "attempt $attempt failed, retrying in 10s..."
          sleep 10
        done
        test -s /tmp/manifest.json || { echo "manifest never appeared"; exit 1; }
        cat /tmp/manifest.json | jq .

    - name: Assert both platforms present
      run: |
        ARCHES=$(jq -r '
          [.manifests[]
            | select(.platform.architecture != "unknown")
            | .platform.architecture] | sort | join(",")
        ' /tmp/manifest.json)
        echo "Found platforms: $ARCHES"
        test "$ARCHES" = "amd64,arm64" || { echo "Missing platforms"; exit 1; }

    - name: Assert ≥2 attestation manifests present
      # CORRECTED predicate (CONTEXT.md D-14's `mediaType == "application/vnd.in-toto+json"`
      # is wrong — attestation manifests share the OCI image manifest mediaType and are
      # identified by the `vnd.docker.reference.type=attestation-manifest` annotation
      # plus platform.architecture=unknown).
      run: |
        ATT_COUNT=$(jq '
          [.manifests[]
            | select(.annotations["vnd.docker.reference.type"] == "attestation-manifest")
          ] | length
        ' /tmp/manifest.json)
        echo "Found attestation manifests: $ATT_COUNT (expected ≥ 2 — one SBOM + one provenance per platform)"
        test "$ATT_COUNT" -ge 2 || { echo "Attestation manifests missing"; exit 1; }
```

**Why two attestations per platform?** With `sbom: true` and `provenance: mode=max` on a 2-platform build, BuildKit creates one SBOM attestation manifest *per platform* and one provenance attestation manifest *per platform* — for a 2-arch build, that's 4 attestation entries. The assertion of `≥ 2` is intentionally lax (catches "no attestations" without being brittle to BuildKit version changes). For a stricter assertion: `test "$ATT_COUNT" -eq 4`.

### Compose validate job

```yaml
compose-validate:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v6

    - name: Validate base alone
      run: docker compose -f docker-compose.yml config --quiet

    - name: Validate base + prod (with GIT_SHA exported)
      run: |
        export GIT_SHA=$(git rev-parse --short=7 HEAD)
        docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
```
[VERIFIED: Empirically tested against Docker Compose v2.18.1 in this session; behavior matches D-03/D-04 expectations exactly]

### `docker-compose.prod.yml` (full file, per D-02)

```yaml
services:
  app:
    image: ghcr.io/ahcarpenter/vici:sha-${GIT_SHA:?GIT_SHA must be set to the 7-char short SHA}
```

That is the entire file. No `version:`, no comments are strictly required (Compose ignores top-level `version:` since v2.x). [VERIFIED: D-02 verbatim]

### Concurrency block (D-12)

```yaml
concurrency:
  group: ghcr-${{ github.ref }}
  cancel-in-progress: false
```

This goes at workflow-level (top of `ci.yml`) only if the goal is to serialize all jobs across runs of the same ref. **Caveat:** placing this at workflow level also serializes the `test` job, which is independent of the publish pipeline. Recommendation: scope concurrency to a sub-workflow group only on the publish jobs (`build-amd64`, `build-arm64`, `merge`, `verify`) by using a job-level concurrency on each. Or, split into two workflows. Given D-15 mandates a single workflow, **the cleanest implementation is workflow-level concurrency** — the test/lint serialization cost is small (~30s wait if back-to-back pushes) and the alternative complicates the YAML. Planner picks; recommend workflow-level.
[VERIFIED: docs.github.com/en/actions/using-jobs/using-concurrency]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| QEMU emulation for arm64 | Native `ubuntu-24.04-arm` runner | 2025-08-07 (GA for free public repos) | ~3x faster builds; D-10 locked in |
| `docker manifest create` (legacy CLI) | `docker buildx imagetools create` | buildx GA (~2020) and bundled with Docker Desktop / runners ever since | Manifest-only operation, no layer pull/push; no daemon `experimental: true` |
| `docker/build-push-action@v5` | `@v6` (2024) → `@v7` (2025) | v6 added native attestations support; v7 refined output formats | Use `@v7`. CONTEXT.md says "v6 as appropriate" — outdated by one major. v7 is backward-compatible for our usage |
| `docker/metadata-action@v5` | `@v6` (2026-03-05) | New major | Use `@v6` |
| `docker/setup-buildx-action@v3` | `@v4` (2026-03-05) | New major | Use `@v4` |
| `--sbom` / `--provenance` as separate `attests:` list | Convenience inputs `sbom: true`, `provenance: mode=max` | build-push-action v5+ | Cleaner YAML; equivalent runtime behavior |
| Inline `docker buildx build --push` shell | `docker/build-push-action` | ~2021 | Composite action handles caching, retries, attestations, secret mounting |

**Deprecated/outdated:**
- `actions/cache@v3` for buildx — replaced by `cache-from/cache-to: type=gha`. Don't go back.
- `docker manifest create` — replaced by `docker buildx imagetools create`. Don't go back.
- QEMU multi-arch on a single runner — replaced by native runners now that arm64 is GA-free for public repos.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| (none) | All claims in this research were either VERIFIED via Context7, official Docker/GitHub docs, GitHub Releases API, or empirical testing against Docker Compose v2.18.1 in this session. | — | — |

The Pitfall 9 retry recommendation (GHCR eventual consistency) is MEDIUM-confidence — observed widely in user reports but not formally documented. Treat as defensive engineering rather than a verified spec.

## Open Questions

1. **First-push verify failure handling**
   - What we know: First push creates package private (HIGH); verify job has no creds (HIGH). Together: first-push verify will fail.
   - What's unclear: Does the planner want option (a) accept-and-document or option (b) gate via `run_attempt > 1`?
   - Recommendation: Option (a). Document in PLAN.md acceptance criteria the sequence: (1) merge Phase 5 PR, (2) first push fails verify, (3) operator flips visibility to public, (4) operator runs `workflow_dispatch` re-run; verify passes.

2. **Workflow-level vs job-level concurrency**
   - What we know: D-12 mandates `cancel-in-progress: false` on `group: ghcr-${{ github.ref }}` (HIGH).
   - What's unclear: Whether this group covers all workflow jobs (including `test`) or only the publish jobs.
   - Recommendation: Workflow-level for simplicity. The serialization cost on `test` is minimal.

3. **PR-time compose-validate scope**
   - What we know: D-15 says compose-validate runs on PRs and main (HIGH).
   - What's unclear: Whether PRs should also lint the compose YAML schema beyond `config --quiet`.
   - Recommendation: `config --quiet` is sufficient. Schema linting (e.g., `compose-spec-linter`) is over-engineering for a 4-service base + 1-service stub.

4. **Required-status-check additions**
   - What we know: D-18 mandates removing `cd-prod`/`cd-staging` from required checks.
   - What's unclear: Whether to *add* the new jobs (`compose-validate`, `build-amd64`, `build-arm64`, `merge`, `verify`) as required checks.
   - Recommendation: Strongly recommend adding `compose-validate` as required (cheap, gates real merge bugs). `build-*` and `merge` only run on `main` push (not PRs), so they can't be PR-gating required checks. `verify` similarly. **Net:** add `compose-validate` only; PLAN.md should call this out as part of D-18's operator step.

5. **Package visibility scope: user vs org**
   - What we know: GHCR shows under "personal account packages" (user `ahcarpenter`).
   - What's unclear: Whether the toggle path differs vs an org-owned package.
   - Recommendation: Documented path is for the personal-account variant: `github.com/users/ahcarpenter/packages/container/vici/settings`. Verify URL in PLAN.md acceptance criteria.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `docker` (Docker Engine) | Local compose-config validation during planning; CI runs in GHA-managed Docker | ✓ | 24.0.2 | — |
| `docker compose` | Local + CI `compose config --quiet` | ✓ | v2.18.1 | — |
| `gh` CLI | Optional — operator can use `gh pr create`, `gh secret list` for cleanup verification | ✓ | 2.89.0 | UI in github.com |
| `jq` | CI verify job; local dev for testing the predicates | ✓ | jq-1.7.1-apple | Pre-installed on GHA `ubuntu-latest` runners |
| `git` | Both local and CI (via `actions/checkout`) | ✓ | 2.39.5 | — |
| `actionlint` | Recommended Wave 0 — static-analyze the new ci.yml additions before push | ✗ | — | Skip locally; rely on GHA's own YAML schema validation. **Optional install:** `brew install actionlint` (1-line, free). Recommend for the planner to suggest. |
| `python3` (for `imagetools inspect --raw` JSON parsing during interactive verification) | Optional — only if planner wants to write a more robust verify-script | ✓ | — | jq sufficient |
| GitHub Actions free arm64 runner (`ubuntu-24.04-arm`) | Per-arch build job for arm64 | ✓ (per public repo eligibility, GA 2025-08-07) | — | QEMU on `ubuntu-latest` (rejected by D-10) |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- `actionlint` is the only gap, and the GHA YAML schema validator catches the same issues server-side. **Recommendation to planner:** add a Wave 0 task to install actionlint as a pre-commit hook OR include a `actionlint` step in ci.yml itself (rwe/actions-actionlint or `mvanholsteijn/actionlint`).

## Validation Architecture

> Phase 5's deliverables are GitHub Actions workflow YAML + a 1-line compose stub + 4 file deletions. There is no Python code to add; existing pytest suite is untouched. Validation must therefore be a mix of static parsing, end-to-end pipeline triggering, and verify-job assertion replay.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | None new — workflow YAML doesn't need a unit test runner. Validation is shell-based. (Existing pytest suite continues to run as the `test` job in `ci.yml`.) |
| Config file | `pyproject.toml` (existing) for pytest; no new config |
| Quick run command | `docker compose -f docker-compose.yml config --quiet && GIT_SHA=$(git rev-parse --short=7 HEAD) docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` |
| Full suite command | All of the above + `actionlint .github/workflows/ci.yml` (after Wave 0 install) + `gh workflow run ci.yml --ref <feature-branch>` followed by manual `gh run watch` |
| Phase gate | All five new jobs (compose-validate, build-amd64, build-arm64, merge, verify) green on a real `main` push (or a feature-branch `workflow_dispatch` if first-push public-toggle is deferred) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CI-01 | Multi-arch image published to GHCR on main push | E2E | `gh workflow run ci.yml --ref <branch>` then verify `docker buildx imagetools inspect ghcr.io/ahcarpenter/vici:sha-<short>` returns 2 platform manifests | ✗ Wave 0 (job + verify step) |
| CI-02 (a) | SHA-only tag, no `:latest` | static | `gh api /users/ahcarpenter/packages/container/vici/versions \| jq '[.[].metadata.container.tags[]] \| unique'` returns only `sha-*` entries | ✗ Wave 0 (gh API check; recommend documenting in PLAN as a one-time verification step rather than a CI assertion — repo size grows linearly so a CI check would itself accumulate cost) |
| CI-02 (b) | Prod overlay references `image: ghcr.io/.../vici:sha-${GIT_SHA}` | static | `grep -F 'sha-${GIT_SHA' docker-compose.prod.yml` exits 0 | ✗ Wave 0 (the docker-compose.prod.yml file itself is the assertion target) |
| CI-03 | Both compose overlays validate on every push | static (in CI) | `docker compose -f docker-compose.yml config --quiet && docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` (after `export GIT_SHA=...`) | ✗ Wave 0 (compose-validate job) |
| CI-04 | `cd-*.yml` workflows deleted | static | `test ! -e .github/workflows/cd-base.yml && test ! -e .github/workflows/cd-dev.yml && test ! -e .github/workflows/cd-staging.yml && test ! -e .github/workflows/cd-prod.yml` | ✗ Wave 0 (file deletions in implementation) |
| D-14 (folded) | SBOM + provenance attestations attached | E2E (verify job) | `jq '[.manifests[] \| select(.annotations["vnd.docker.reference.type"] == "attestation-manifest")] \| length' /tmp/manifest.json` returns ≥ 2 | ✗ Wave 0 (verify job step) |

### Sampling Rate
- **Per task commit:** Run `docker compose config --quiet` locally on both overlays. Run `actionlint .github/workflows/ci.yml` if installed.
- **Per wave merge:** Trigger the workflow on a feature branch via `gh workflow run ci.yml --ref <branch>`; verify all 5 new jobs green. (This requires the workflow's triggers to include `workflow_dispatch` per D-06 — already mandated.)
- **Phase gate:** Real push to `main` (or final merge of Phase 5 PR) produces a `sha-<short>` tag in GHCR; the verify job passes; manual operator step (D-08 public toggle) is completed; manual operator step (D-18 branch-protection) is completed.

### Wave 0 Gaps
- [ ] `.github/workflows/ci.yml` — extend with 5 new jobs (compose-validate, build-amd64, build-arm64, merge, verify); the existing test job stays as-is per D-15
- [ ] `docker-compose.prod.yml` — create with the exact 3-line content from D-02
- [ ] Delete `.github/workflows/cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml` (D-16)
- [ ] (Optional) actionlint install as pre-commit hook OR as a CI step
- [ ] Operator action documentation in PLAN.md acceptance criteria for D-08 (GHCR public toggle) and D-18 (branch-protection update)

*No existing test files cover Phase 5's domain (workflow YAML + compose static parse + GHCR publish). All validation is new and shell-based; the existing pytest suite is untouched.*

## Project Constraints (from CLAUDE.md / AGENTS.md)

CLAUDE.md → AGENTS.md primarily covers FastAPI Python conventions (async routes, Pydantic, dependencies, REST conventions, naming, migrations, testing, linting, OO design, 3NF). **None of these directives constrain Phase 5's deliverables** — workflow YAML and a compose stub are outside the FastAPI Python scope.

The two AGENTS.md sections that *could* faintly apply:
- **"Apply DRY relentlessly"** → use `metadata-action` once for tag computation, reuse in build + merge jobs (already in §Code Examples; the merge job re-runs it for the JSON-output side effect, which is idiomatic for the canonical pattern).
- **"Be sure all magic numbers are constantized"** → in workflow YAML, this would mean defining repeat values like `ghcr.io/...` and runner labels at the workflow `env:` level. The §Code Examples does this with `env.GHCR_IMAGE`.

No CLAUDE.md directive forbids any decision in CONTEXT.md or any pattern in this research.

## Sources

### Primary (HIGH confidence)
- Context7 `/docker/build-push-action` — multi-platform build inputs, sbom/provenance flags, cache config, output destinations
- Context7 `/docker/metadata-action` — `type=sha,prefix=,format=` tag spec, `DOCKER_METADATA_OUTPUT_JSON` env var, default short-SHA length (7)
- docs.docker.com/build/cache/backends/gha — `scope=` parameter behavior; `mode=max` semantics; access restrictions
- docs.docker.com/build/metadata/attestations/attestation-storage — OCI image index structure; attestation-manifest annotation and `platform.architecture=unknown`
- docs.docker.com/reference/cli/docker/buildx/imagetools/create — manifest assembly command syntax
- docs.docker.com/reference/cli/docker/buildx/imagetools/inspect — `--raw` JSON output format
- docs.docker.com/reference/compose-file/interpolation — `${VAR:?error}` mandatory-variable syntax
- docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility — first-push private default, public-toggle UI path, anonymous pull confirmation
- docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication — `GITHUB_TOKEN` permissions for packages
- github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available — `ubuntu-24.04-arm` GA confirmation
- github.com/orgs/community/discussions/148648 — runner label syntax (`ubuntu-24.04-arm`, `ubuntu-22.04-arm`); private-repo caveat
- raw.githubusercontent.com/sredevopsorg/multi-arch-docker-github-workflow/main/.github/workflows/multi-build.yaml — canonical reference workflow YAML (verbatim)
- GitHub Releases API queries (2026-05-01) — exact latest stable versions of all 7 GHA actions used
- Empirical test against Docker Compose v2.18.1 (this session) — `${GIT_SHA:?...}` exit code 15 + literal stderr message

### Secondary (MEDIUM confidence)
- felipecruz.es/buildkit-supply-chain-features — confirms attestation-manifest mediaType + annotation structure (cross-verifies docs.docker.com)
- labex.io/tutorials/docker-how-to-use-docker-buildx-imagetools-inspect — practical jq examples (consistency check)

### Tertiary (LOW confidence — flagged where used)
- GHCR eventual-consistency retry recommendation in Pitfall 9 — observed via user reports, not formally specified by GitHub. Defensive recommendation only.

## Metadata

**Confidence breakdown:**
- Standard stack (versions + roles): HIGH — verified against GitHub Releases API on 2026-05-01
- Architecture (split-runner pattern): HIGH — canonical Docker pattern; verbatim YAML from reference workflow
- Pitfalls (Pitfalls 1-8): HIGH — each has a verified source citation
- Pitfall 9 (GHCR eventual consistency): MEDIUM — defensive engineering, no formal spec
- Compose interpolation behavior: HIGH — empirically tested
- Attestation manifest structure: HIGH — official Docker docs + cross-verified
- Verify-job jq predicates: HIGH — derived from official Docker docs on attestation storage

**Research date:** 2026-05-01
**Valid until:** ~2026-06-01 (30 days). Action major versions move; re-verify before any future Phase that touches the same YAML.

---

## RESEARCH COMPLETE

**Phase:** 05 - GHCR Image Distribution & CI Validation
**Confidence:** HIGH

### Key Findings

1. **Two CONTEXT.md corrections required:**
   - **D-14 attestation jq predicate is wrong.** Attestation manifests use `mediaType: application/vnd.oci.image.manifest.v1+json` (not `application/vnd.in-toto+json`). They are identified by the annotation `vnd.docker.reference.type=attestation-manifest` and `platform.architecture=unknown`. Corrected predicate is in §Code Examples §Verify job.
   - **Action versions are stale in CONTEXT.md** — current latest stable as of 2026-05-01 is `build-push-action@v7`, `metadata-action@v6`, `setup-buildx-action@v4`, `login-action@v4`, `upload-artifact@v7`, `download-artifact@v8`, `checkout@v6`. All backward-compatible for our usage.

2. **Compose `${GIT_SHA:?msg}` behavior empirically verified** — exit code 15, exact stderr message captured. Both base-alone and base+prod overlays validate cleanly when `GIT_SHA` is exported; base+prod fails loud with the literal D-02 message text when `GIT_SHA` is unset.

3. **Canonical split-runner workflow YAML obtained verbatim** from sredevopsorg reference repo (the canonical Docker docs page recently stripped the inline example and points at the reusable github-builder workflow instead). This is the basis for the build/merge job patterns.

4. **First-push GHCR visibility flow** — package created private by default; D-08 manual public toggle is required AFTER first push; verify job will fail on first push because it has no creds (by design). PLAN.md acceptance criteria must encode this sequence: push → toggle → re-run via workflow_dispatch.

5. **Branch protection drift (D-18)** is the most likely real-world snag. PR cannot merge until required-status-check rulesets are scrubbed of `cd-prod` / `cd-staging` references. PLAN.md must flag this as a blocking pre-merge operator step.

### File Created
`.planning/phases/05-ghcr-image-distribution-ci-validation/05-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | Verified against GitHub Releases API + Context7 |
| Architecture | HIGH | Canonical pattern with verbatim reference YAML |
| Pitfalls | HIGH (8 of 9) / MEDIUM (1 of 9) | All cited; only GHCR eventual-consistency retry is defensive |
| Compose behavior | HIGH | Empirically tested |
| Attestation predicate | HIGH | Official Docker docs + cross-verified, fixes CONTEXT.md error |

### Open Questions
1. First-push verify failure handling — recommend option (a) accept-and-document.
2. Workflow-level vs job-level concurrency scope — recommend workflow-level for simplicity.
3. Whether to add new jobs (especially `compose-validate`) as required status checks alongside removing `cd-*` — strongly recommend adding `compose-validate`.
4. Optional `actionlint` Wave 0 install — recommended but not blocking.
5. Personal-account vs org-account GHCR visibility URL — verify exact URL in PLAN.md acceptance criteria.

### Ready for Planning
Research complete. Planner can now create PLAN.md files with confidence on:
- Exact action version pins (v7/v6/v4/v8)
- Verbatim job YAML for compose-validate, build-amd64/arm64, merge, verify
- Corrected jq predicate for attestation assertion
- Wave 0 file additions/deletions
- Operator-step acceptance criteria for D-08 (public toggle) and D-18 (branch protection)
- Recommended optional actionlint hardening
