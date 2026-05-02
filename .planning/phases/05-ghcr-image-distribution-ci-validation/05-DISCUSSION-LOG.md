# Phase 5: GHCR Image Distribution & CI Validation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-01
**Phase:** 5-GHCR Image Distribution & CI Validation
**Areas discussed:** Prod overlay stub, Build triggers + tags, Multi-arch approach, Workflow file structure, Legacy CD deletion scope, Image namespace

---

## Prod Overlay Stub

### Q1: How should Phase 5 handle prod-overlay validation?

| Option | Description | Selected |
|--------|-------------|----------|
| Create minimal stub now | Phase 5 writes `docker-compose.prod.yml` with `image:` override on `app` so CI-03 fully passes. Phase 6 expands it. | ✓ |
| Validate base only in Phase 5 | CI step runs only `docker compose -f docker-compose.yml config --quiet`. Phase 6 adds the second step. | |
| Defer CI-03 entirely to Phase 6 | Phase 5 only does GHCR build/push + delete legacy CD; all compose-config moves to Phase 6. | |

**User's choice:** Create minimal stub now
**Notes:** Fully self-contained Phase 5; aligns with success criterion #3 wording.

### Q2: What goes in the stub?

| Option | Description | Selected |
|--------|-------------|----------|
| image-only override | ~5 lines, only sets `services.app.image`; everything else deferred to Phase 6. | ✓ |
| image + strip dev-mode | Image override + null `volumes:` + override `command:` to drop `--reload`. | |
| image + image-pull policy | Image override + `pull_policy: always`. | |

**User's choice:** image-only override
**Notes:** Cleanest separation; Phase 6 fleshes out the prod overlay in one coherent pass.

### Q3: How should `${GIT_SHA}` be substituted?

| Option | Description | Selected |
|--------|-------------|----------|
| Fail-loud `${GIT_SHA:?...}` | Compose fails with explanatory message if GIT_SHA is unset. | ✓ |
| Plain `${GIT_SHA}` | Standard substitution; silently expands to empty string if unset. | |
| Default to current commit `${GIT_SHA:-$(...)}` | Compose doesn't evaluate `$()` shell substitution; not viable. | |

**User's choice:** Fail-loud `${GIT_SHA:?GIT_SHA must be set to the 7-char short SHA}`
**Notes:** Aligns with `_validate_required_credentials` fail-fast precedent (Phase 02.11).

### Q4: Should the stub set `pull_policy: always`?

| Option | Description | Selected |
|--------|-------------|----------|
| Set `pull_policy: always` now | One line; ensures fresh pull of SHA-tag. | |
| Defer to Phase 6 | Keep stub strictly to `image:`; Phase 6 handles all production-shape concerns. | ✓ |
| You decide | — | |

**User's choice:** Defer to Phase 6
**Notes:** SHA-tags are immutable by convention; default policy is functionally fine.

---

## Build Triggers + Tags

### Q1: What events should fire the build?

| Option | Description | Selected |
|--------|-------------|----------|
| main push + git tag + workflow_dispatch | No PR builds. | ✓ (with todo for #2) |
| + PR builds (no push) | Adds `--push=false` multi-arch build to PR runs to catch Dockerfile breakage. | (deferred) |
| main push only (strict roadmap) | Literal interpretation of "every main push". | |

**User's choice:** Option 1 + add a todo for option 2
**Notes:** PR-time image verification noted as a deferred idea; not blocking Phase 5.

### Q2: What image tags get applied?

| Option | Description | Selected |
|--------|-------------|----------|
| SHA-only | Every build gets exactly `sha-<short>`. | ✓ |
| SHA + semver on tag pushes | Add `:v1.1.0` when a `v*.*.*` git tag is pushed. | |
| SHA + immutable digest output only | Push SHA tag and emit `sha256:...` digest as workflow output. | |

**User's choice:** SHA-only
**Notes:** Minimal, immutable; release semantics live in git tags + GitHub Releases.

### Q3: How should image visibility be set to public?

| Option | Description | Selected |
|--------|-------------|----------|
| Manual one-time GitHub Settings toggle | Operator clicks visibility toggle once after first push. PLAN.md flags it. | ✓ |
| Automated via `gh api` step | Workflow calls `gh api --method PATCH ... visibility=public`. | |
| Stay private + use `actions/login` | Verify step uses GITHUB_TOKEN; violates "unauthenticated" wording. | |

**User's choice:** Manual one-time GitHub setting
**Notes:** Simple; PLAN.md must include the manual step in acceptance criteria.

### Q4: How should success criterion #2 (unauthenticated pull + dual-arch manifest) be verified?

| Option | Description | Selected |
|--------|-------------|----------|
| Separate verify job | Fresh runner with no GHCR creds; runs `docker manifest inspect` + jq assertions. | ✓ |
| Inline step in build job + `docker logout` | Saves runner time but mixes concerns. | |
| Defer verification to manual / smoke-test | No automated guarantee per push. | |

**User's choice:** Separate verify job
**Notes:** Mirrors success criterion's "unauthenticated CI job" wording exactly.

---

## Multi-Arch Approach

### Q1: How are amd64 and arm64 images built?

| Option | Description | Selected |
|--------|-------------|----------|
| Single QEMU buildx job | One job, ~10–12 min, simplest YAML. Matches roadmap goal text. | |
| Split jobs on native runners + manifest merge | Matrix on `ubuntu-latest` + `ubuntu-24.04-arm`; third merge job. ~3–5 min total. | ✓ |
| Single buildx job with `cache-from: type=gha` | Same as option 1 with explicit cache. | |

**User's choice:** Split jobs on native runners + manifest merge
**Notes:** Properly fast; uses GitHub's free arm64 runner offering.

### Q2: Cache strategy?

| Option | Description | Selected |
|--------|-------------|----------|
| GHA cache, scoped per-arch | Matches existing `cd-base.yml:67-68` precedent; ~10GB quota. | ✓ |
| Registry cache via dedicated GHCR tag | No quota; pollutes GHCR namespace. | |
| No cache | Simplest; full build cost every push. | |

**User's choice:** GHA cache, scoped per-arch
**Notes:** `scope=amd64` and `scope=arm64` to avoid cross-arch collisions.

### Q3: Concurrency control?

| Option | Description | Selected |
|--------|-------------|----------|
| No cancellation | Pushes queue and run sequentially; every SHA gets its image. | ✓ |
| Cancel in-progress on newer push | Saves Actions minutes but breaks "every main SHA has an image" invariant. | |
| No concurrency directive | Unbounded parallelism; same outcome as option 1 without queue ordering. | |

**User's choice:** No cancellation
**Notes:** SHA-pinned prod overlay depends on every SHA having a pullable image.

### Q4: Provenance and SBOM defaults?

| Option | Description | Selected |
|--------|-------------|----------|
| Explicitly `provenance: false, sbom: false` | Defer attestations to the deferred todo phase. | |
| Accept defaults (`provenance: true, sbom: false`) | SLSA Level 1 provenance now; SBOM stays deferred. | |
| You decide | — | |

**User's choice:** Free-text — "Go ahead and ensure the deferred todo is handled"
**Notes:** Folds the deferred todo `260501-sbom-provenance-attestations.md` into Phase 5. Both `provenance: mode=max` and `sbom: true` are enabled. The verify job's jq query is updated to handle attestation entries.

---

## Workflow File Structure

### Q1: One workflow file or two?

| Option | Description | Selected |
|--------|-------------|----------|
| New `release.yml` for build/push/verify | `ci.yml` for lint/test/compose-validate; `release.yml` for build/push. | |
| Single extended `ci.yml` | One workflow with all jobs; gated by `if:` conditions. | ✓ |
| Three files | `ci.yml` + `release.yml` + `compose-validate.yml`. | |

**User's choice:** Single extended `ci.yml`
**Notes:** The deferred todo's filename hint (`release.yml`) needs updating to `ci.yml` when folded.

---

## Legacy CD Deletion Scope

### Q1: What gets removed in Phase 5?

| Option | Description | Selected |
|--------|-------------|----------|
| Just the four `cd-*.yml` workflow files | `infra/`, `helm/`, etc. stay until Phase 9. | |
| + unused GitHub Environments references | Also scrub stale `WIF_*` / `PULUMI_*` secret references in remaining workflows. | |
| + branch protection / rulesets review | Options 1–2 plus PLAN.md notes on manual operator action for branch protection. | ✓ |

**User's choice:** + branch protection / rulesets review
**Notes:** Phase 5 doesn't touch GitHub Settings programmatically but the PLAN.md must flag the manual pre-merge dependency.

---

## Image Namespace

### Q1: How is the GHCR namespace expressed?

| Option | Description | Selected |
|--------|-------------|----------|
| `${{ github.repository_owner }}` in workflow | Workflow auto-adapts on transfer; lowercase via `tr`. Prod overlay stub keeps literal. | ✓ |
| Hardcode `ahcarpenter/vici` everywhere | Simplest; sed-rename PR if repo transfers. | |
| `${{ github.repository }}` (combined) | Slightly more concise. | |

**User's choice:** `${{ github.repository_owner }}` in workflow
**Notes:** Prod overlay stub uses literal `ghcr.io/ahcarpenter/vici` for operator readability. Workflow lowercases `${{ github.repository_owner }}` since GHCR rejects mixed-case.

---

## Claude's Discretion

- Exact pinned `uses:` versions for buildx/login/metadata/build-push actions (planner picks latest stable major).
- Verify-job timeout (planner default).
- First-push edge case if package starts private (planner picks: `continue-on-error` on first run, or document the public-toggle as pre-second-push).
- Exact `jq` query syntax for manifest assertions (planner picks).

## Deferred Ideas

- **PR-time image build verification** — multi-arch buildx with `--push=false` to catch Dockerfile breakage before merge. Captured as a deferred todo to track for future consideration.
- **Tighten `pip-audit` to hard-fail** — already in Phase 999.1 backlog. Out of scope.
- **Cosign image signing** — already deferred at milestone level (REQUIREMENTS.md §"Future Requirements").
- **OCI artifact retention policy** — not in any current requirement; raise if GHCR storage becomes a concern.

## Folded Todos

- **`260501-sbom-provenance-attestations.md`** — folded into Phase 5 D-14. The deferred todo's acceptance criteria (`--sbom=true`, `--provenance=mode=max`, `imagetools inspect --raw` shows `application/vnd.in-toto+json`, brief operator note in deployment doc) flow directly into Phase 5's build/push step and verify-job assertions.
