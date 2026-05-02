---
phase: 5
slug: ghcr-image-distribution-ci-validation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-01
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Phase 5 has no Python code deltas — deliverables are workflow YAML, a 1-line compose stub, and 4 file deletions. Validation is shell-based + workflow-triggered. Existing pytest suite continues to run unchanged as the `test` job in `ci.yml`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | None new. Validation is shell-based: `docker compose config`, `actionlint`, `gh workflow run`, `docker buildx imagetools inspect` + `jq`. Existing pytest suite (Python 3.12 + uv) keeps running as the `test` job in `ci.yml`. |
| **Config file** | `pyproject.toml` (existing) for pytest; no new config files |
| **Quick run command** | `docker compose -f docker-compose.yml config --quiet && GIT_SHA=$(git rev-parse --short=7 HEAD) docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` |
| **Full suite command** | Quick + `actionlint .github/workflows/ci.yml` (after Wave 0 install) + `gh workflow run ci.yml --ref <branch>` (manual trigger producing a real GHCR push + verify-job assertion replay) |
| **Estimated runtime** | Quick: ~5s. Full suite (including E2E workflow trigger): ~5-8 min wall-clock for the full pipeline (build-amd64 || build-arm64 → merge → verify). |

---

## Sampling Rate

- **After every task commit:** Run quick command (both compose validates, ~5s).
- **After every plan wave:** Run full suite. For workflow-touching waves, push to a feature branch and `gh workflow run ci.yml --ref <branch>` to exercise build/merge/verify end-to-end.
- **Before `/gsd-verify-work`:** Full suite green AND a real `main` push has produced a `sha-<short>` tag in GHCR with the verify job green.
- **Max feedback latency:** ~5s (quick) / ~8 min (E2E workflow run).

---

## Per-Task Verification Map

> Plan IDs are not yet assigned (planner runs next). This table will be backfilled with `{N}-01-01`-style task IDs once PLAN.md files exist. The rows below capture validation samples per phase requirement; planner is expected to map each into one or more concrete task acceptance criteria.

| Sample | Requirement | Plan / Task | Test Type | Automated Command | File Exists | Status |
|--------|-------------|-------------|-----------|-------------------|-------------|--------|
| Compose base validates | CI-03 | TBD (compose-validate job) | static | `docker compose -f docker-compose.yml config --quiet` exits 0 | ❌ W0 (compose-validate job in ci.yml) | ⬜ pending |
| Compose base+prod validates with GIT_SHA set | CI-03 | TBD (compose-validate job) | static | `GIT_SHA=$(git rev-parse --short=7 HEAD) docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` exits 0 | ❌ W0 (compose-validate job in ci.yml + docker-compose.prod.yml) | ⬜ pending |
| Compose base+prod fails loud without GIT_SHA | D-03 | TBD (compose-validate job) | static-negative | `unset GIT_SHA; docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` exits 15 with stderr containing literal `GIT_SHA must be set to the 7-char short SHA` | ❌ W0 (docker-compose.prod.yml content) | ⬜ pending |
| Multi-arch tag pushed on main | CI-01 | TBD (build-amd64 + build-arm64 + merge jobs) | E2E | `gh workflow run ci.yml --ref <branch>` then `docker buildx imagetools inspect ghcr.io/ahcarpenter/vici:sha-<short>` returns both `linux/amd64` and `linux/arm64` platform manifests | ❌ W0 (3 new workflow jobs) | ⬜ pending |
| SHA-only tag, no `:latest` | CI-02 | TBD (metadata-action config) | static + post-push | (a) grep workflow YAML to confirm no `:latest` literal AND no `flavor: latest=` true; (b) one-time post-publish `gh api /users/ahcarpenter/packages/container/vici/versions \| jq '[.[].metadata.container.tags[]] \| unique'` lists only `sha-*` entries | ❌ W0 (metadata-action input + manual visibility post-toggle) | ⬜ pending |
| Prod overlay references correct image | CI-02 (b) | TBD (docker-compose.prod.yml creation) | static | `grep -F 'image: ghcr.io/ahcarpenter/vici:sha-${GIT_SHA' docker-compose.prod.yml` exits 0 | ❌ W0 (docker-compose.prod.yml file) | ⬜ pending |
| Verify job: both platforms present | CI-01 | TBD (verify job) | E2E | Verify job runs `docker buildx imagetools inspect --raw <ref>` then `jq -e '[.manifests[] \| select(.platform.architecture != "unknown") \| .platform.architecture] \| sort == ["amd64","arm64"]'` returns true | ❌ W0 (verify job in ci.yml) | ⬜ pending |
| Verify job: attestation manifests present | D-14 (folded) | TBD (verify job) | E2E | Verify job `jq -e '[.manifests[] \| select(.annotations["vnd.docker.reference.type"] == "attestation-manifest")] \| length >= 2'` returns true | ❌ W0 (verify job + provenance/sbom flags on build-push-action) | ⬜ pending |
| Anonymous pull works post-toggle | CI-01 / D-08 | TBD (verify job) | E2E | Verify job runs WITHOUT `docker/login-action` and successfully completes `imagetools inspect`. (First push fails by design; operator toggles GHCR public; re-run via `workflow_dispatch` passes.) | ❌ W0 (verify job authoring + manual operator step) | ⬜ pending |
| Legacy CD workflow files deleted | CI-04 | TBD (file deletions) | static | `test ! -e .github/workflows/cd-base.yml && test ! -e .github/workflows/cd-dev.yml && test ! -e .github/workflows/cd-staging.yml && test ! -e .github/workflows/cd-prod.yml` exits 0 | ❌ W0 (delete operations) | ⬜ pending |
| Stale GKE secrets removed from remaining workflows | D-17 | TBD (workflow YAML scrub) | static | `grep -rE 'WIF_PROVIDER\|WIF_SERVICE_ACCOUNT\|PULUMI_CONFIG_PASSPHRASE' .github/workflows/` exits 1 (no matches) | ❌ W0 (scrub operation in ci.yml or other surviving workflow) | ⬜ pending |
| Concurrency group queues without canceling | D-12 | TBD (workflow concurrency block) | static | `grep -F 'cancel-in-progress: false' .github/workflows/ci.yml` exits 0 AND `grep -F 'group: ghcr-' .github/workflows/ci.yml` exits 0 | ❌ W0 (concurrency block in ci.yml) | ⬜ pending |
| Action versions are current | (research correction) | TBD (workflow YAML pins) | static | All `uses:` references in new jobs pin to: `docker/build-push-action@v7`, `docker/metadata-action@v6`, `docker/setup-buildx-action@v4`, `docker/login-action@v4`, `actions/upload-artifact@v7`, `actions/download-artifact@v8`, `actions/checkout@v6` | ❌ W0 (workflow YAML authoring) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `.github/workflows/ci.yml` — extend with 5 new jobs: `compose-validate`, `build-amd64`, `build-arm64`, `merge`, `verify`. Existing `lint`, `test`, `pip-audit` jobs stay untouched per D-15.
- [ ] `docker-compose.prod.yml` — create with the exact image-only stub from D-02 (3 lines: `services:` / `app:` / `image: ghcr.io/ahcarpenter/vici:sha-${GIT_SHA:?GIT_SHA must be set to the 7-char short SHA}`)
- [ ] Delete `.github/workflows/cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml` (D-16)
- [ ] Scrub `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, `PULUMI_CONFIG_PASSPHRASE` `secrets:` references from any surviving workflow YAML (D-17)
- [ ] (Optional but recommended) Document `actionlint` install for local pre-merge use; add as a CI step if planner judges the additional ~5s job warranted
- [ ] Operator-action documentation in PLAN.md acceptance criteria for D-08 (manual GHCR `Settings → Code & automation → Packages → vici → Change visibility → Public` toggle after first push) and D-18 (manual `Settings → Branches` ruleset update to remove `cd-prod` / `cd-staging` from required status checks before Phase 5 PR merge)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| GHCR package visibility set to public | CI-01 / D-08 | First push creates the package as private; toggle requires GitHub UI navigation. Phase 5 explicitly chose manual one-time op over `gh api` automation. | After the first successful push to `main` (with `verify` job expected to fail on first run), navigate to `https://github.com/users/ahcarpenter/packages/container/vici/settings`, scroll to "Danger Zone", click "Change visibility", select "Public", confirm. Then re-trigger workflow via `gh workflow run ci.yml --ref main` and confirm verify job passes. |
| Branch protection / required-status-checks updated | CI-04 / D-18 | Required-status-check rulesets reference job names (`cd-prod`, `cd-staging`) that no longer exist after Phase 5 deletions. UI-only update; cannot be done programmatically without `gh api` calls scoped to settings (out of repo). | Before merging the Phase 5 PR, navigate to `Settings → Rules → Rulesets` (or `Settings → Branches → Branch protection rules` if classic protection is still in use), open the ruleset for `main`, locate "Require status checks", remove `cd-prod`, `cd-staging`, `cd-dev`, `cd-base` if present, and save. |

---

## Validation Sign-Off

- [ ] All tasks have `<acceptance_criteria>` with grep-verifiable conditions (planner enforces)
- [ ] Sampling continuity: every plan wave has at least one shell-verifiable check (compose-config, grep, file-existence, or jq-on-imagetools-inspect)
- [ ] Wave 0 covers all MISSING references — every row in the verification map is mapped to a Wave 0 deliverable
- [ ] No watch-mode flags (none used in shell-based validation)
- [ ] Feedback latency < 5s for quick command; full E2E pipeline ~8 min
- [ ] Two manual-only verifications documented (D-08, D-18) — these CANNOT be automated and the planner must encode them as `autonomous: false` tasks or as explicit operator-action acceptance criteria
- [ ] `nyquist_compliant: true` set in frontmatter once planner has mapped every row to a concrete task ID

**Approval:** pending
