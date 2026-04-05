---
phase: 03-temporal-in-cluster
plan: "03"
subsystem: infra
tags: [pulumi, temporal, opensearch, cloud-sql-proxy, helm, kubernetes, gke]

# Dependency graph
requires:
  - phase: 03-temporal-in-cluster
    provides: temporal.py, opensearch.py, secrets.py with all resources defined
  - phase: 03-temporal-in-cluster
    provides: infra/__main__.py (pre-wiring state from plan 03-01/03-02)
provides:
  - Temporal and OpenSearch wired into Pulumi entry point (__main__.py)
  - temporal-host secret value set in GCP Secret Manager
  - Full deployment verified: OpenSearch Running, schema migration Succeeded, all Temporal pods 2/2 Running
  - Temporal UI accessible via port-forward at localhost:8080
affects:
  - 04-app-runtime
  - any phase referencing TEMPORAL_HOST or temporal-frontend service

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Native K8s sidecar via initContainer with restartPolicy=Always (K8s 1.29+) for Cloud SQL Auth Proxy in Helm charts that lack sidecarContainers support"
    - "Chart-level serviceAccount at top level (not under server) for Temporal chart 0.74.0"
    - "setConfigFilePath=True to load sprig configmap for Temporal server v1.30+"

key-files:
  created: []
  modified:
    - infra/__main__.py
    - infra/components/temporal.py
    - infra/Pulumi.gks-refactor.yaml

key-decisions:
  - "server.sidecarContainers is not a valid key in chart 0.74.0; replaced with server.additionalInitContainers + restartPolicy: Always (native K8s sidecar pattern)"
  - "serviceAccount.name must be set at chart top level, not under server, in chart 0.74.0"
  - "Disabled chart-bundled schema jobs (schema.createDatabase/setup/update) in favour of our own temporal-schema-migration Job"
  - "OpenSearch wired as elasticsearch.external=True (ES v7 compat API) for Temporal visibility store"
  - "numHistoryShards=512 is permanent — cannot change after first deploy (D-05)"

patterns-established:
  - "Native sidecar pattern: use initContainer + restartPolicy=Always for Cloud SQL Auth Proxy when target Helm chart lacks sidecarContainers support"
  - "Stale orphan Helm releases must be pruned before redeploying to avoid pending-replace deadlocks"

requirements-completed: [TEMPORAL-01, TEMPORAL-02, TEMPORAL-03, TEMPORAL-04, TEMPORAL-05, TEMPORAL-06]

# Metrics
duration: multi-session
completed: 2026-04-05
---

# Phase 03 Plan 03: Wire OpenSearch and Temporal into Pulumi Entry Point + Verify Deployment Summary

**Temporal chart 0.74.0 fully deployed on GKE with Cloud SQL Auth Proxy native sidecar, OpenSearch visibility store, and all four server components (frontend, history, matching, worker) Running 2/2**

## Performance

- **Duration:** Multi-session (spanning prior session for Task 1 + current session for Tasks 2-3)
- **Started:** Prior session (Task 1 commit 5560cf9)
- **Completed:** 2026-04-05
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Wired `opensearch_release`, `temporal_schema_job`, and `temporal_release` into `infra/__main__.py` so `pulumi up` manages all resources end-to-end
- Confirmed `temporal-host` secret definition in `_SECRET_DEFINITIONS` and set its GCP Secret Manager value to `temporal-frontend.temporal.svc.cluster.local:7233`
- Full `pulumi up --stack gks-refactor` succeeded: OpenSearch pod Running in observability namespace, temporal-schema-migration Job SUCCEEDED (TTL-cleaned), all Temporal server pods 2/2 Running, Temporal UI accessible at http://localhost:8080

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire imports into __main__.py** - `5560cf9` (feat) — prior session
2. **Task 2 + bug fixes: Fix temporal.py helm values + confirm secret** - `6c2c1f3` (fix)

**Note:** Task 3 was a human verification checkpoint with no code changes.

## Files Created/Modified

- `infra/__main__.py` — Added `from components.opensearch import opensearch_release` and `from components.temporal import temporal_schema_job, temporal_release` imports
- `infra/components/temporal.py` — Fixed `server.sidecarContainers` → `server.additionalInitContainers` + `restartPolicy: Always`; added `serviceAccount` at chart top level; added `setConfigFilePath: True` and `configMapsToMount: sprig`
- `infra/Pulumi.gks-refactor.yaml` — Added encrypted `temporal_db_user` and `temporal_db_password` Pulumi config secrets

## Decisions Made

- **Native sidecar over sidecarContainers:** Chart 0.74.0 does not support `server.sidecarContainers`. Used `server.additionalInitContainers` with `restartPolicy: Always` instead, which activates K8s 1.29+ native sidecar semantics — the proxy starts before the main container and stays alive for the Job's lifetime.
- **serviceAccount at chart top level:** Chart 0.74.0 reads `serviceAccount.name` at root, not `server.serviceAccountName`. Set `serviceAccount: {create: false, name: temporal-app}`.
- **setConfigFilePath=True:** Required for Temporal server 1.30+ to load the sprig configmap instead of the embedded `config_template_embedded.yaml`. Was present in code but not taking effect due to stale Pulumi pending state from an interrupted prior deploy.
- **Stale orphan release cleanup:** Helm release `temporal-862f169c` was an orphan from an interrupted deploy. Deleted it manually before rerunning `pulumi up` to clear the pending-replace deadlock.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] server.sidecarContainers is not a real key in chart 0.74.0**
- **Found during:** Task 2 (deployment verification)
- **Issue:** `server.sidecarContainers` is silently ignored by chart 0.74.0 — Cloud SQL Auth Proxy was never injected into Temporal server pods, so server components could not reach Cloud SQL
- **Fix:** Replaced with `server.additionalInitContainers` containing the Auth Proxy container with `restartPolicy: Always` (native K8s sidecar pattern)
- **Files modified:** `infra/components/temporal.py`
- **Verification:** All four Temporal server pods reached 2/2 Running after fix
- **Committed in:** `6c2c1f3`

**2. [Rule 1 - Bug] serviceAccount.name must be at chart top level**
- **Found during:** Task 2 (deployment verification)
- **Issue:** KSA `temporal-app` was not being associated with Temporal server pods because the chart reads `serviceAccount.name` at root, not `server.serviceAccountName`
- **Fix:** Added `"serviceAccount": {"create": False, "name": "temporal-app"}` at chart root in values dict
- **Files modified:** `infra/components/temporal.py`
- **Verification:** Pods launched with correct service account, Workload Identity binding worked
- **Committed in:** `6c2c1f3`

**3. [Rule 3 - Blocking] Stale orphan Helm release blocked pulumi up**
- **Found during:** Task 2 (first pulumi up attempt)
- **Issue:** Prior interrupted deploy left a `temporal-862f169c` Helm release in a pending-replace state; subsequent `pulumi up` deadlocked
- **Fix:** Deleted orphan release manually (`helm delete temporal-862f169c -n temporal`) then re-ran `pulumi up`
- **Files modified:** None (operational cleanup)
- **Verification:** `pulumi up` completed successfully on next run
- **Committed in:** N/A (operational, no code change)

---

**Total deviations:** 3 auto-fixed (2 bugs, 1 blocking)
**Impact on plan:** All three fixes were necessary for the deployment to succeed. No scope creep.

## Issues Encountered

- Stale Pulumi pending state from a prior interrupted deploy caused `setConfigFilePath: True` to have no effect on the first re-deploy attempt. Resolved by clearing pending operations and re-running `pulumi up`.

## User Setup Required

None - no external service configuration required beyond the GCP Secret Manager value set in Task 2.

## Next Phase Readiness

- Temporal is fully operational in-cluster: schema migrated, all server components Running, UI accessible
- `TEMPORAL_HOST` secret resolves to `temporal-frontend.temporal.svc.cluster.local:7233`
- Application runtime (phase 04) can now connect to Temporal via the in-cluster service DNS name using the `TEMPORAL_HOST` secret
- No blockers

---
*Phase: 03-temporal-in-cluster*
*Completed: 2026-04-05*
