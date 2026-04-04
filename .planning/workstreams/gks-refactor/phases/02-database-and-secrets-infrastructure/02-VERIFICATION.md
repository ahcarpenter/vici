---
phase: 02-database-and-secrets-infrastructure
verified: 2026-04-04T17:00:00Z
status: human_needed
score: 12/12 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 0/12
  gaps_closed:
    - "App Cloud SQL PG16 instance exists with private IP in the GKE VPC"
    - "Temporal Cloud SQL PG16 instance with temporal and temporal_visibility databases"
    - "VPC peering for servicenetworking established before Cloud SQL instances"
    - "vici-app GSA has cloudsql.client and secretmanager.secretAccessor IAM roles"
    - "temporal-app GSA exists with cloudsql.client role and WIF binding"
    - "vici-app KSA in vici namespace has WIF annotation"
    - "All 11 SECRETS-01 secrets exist as GCP Secret Manager resources"
    - "ESO Helm release installed in external-secrets namespace"
    - "vici, temporal, observability namespaces each have a namespace-scoped SecretStore"
    - "ExternalSecret CRs defined for every secret in each namespace"
    - "Migration Job has Auth Proxy as native sidecar initContainer"
    - "Cloud SQL connection names exported for downstream consumption"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Cloud SQL instances reachable via Auth Proxy from vici namespace"
    expected: "A test pod in the vici namespace can open a connection to the app Cloud SQL instance through the Auth Proxy socket at /cloudsql"
    why_human: "Requires a live cluster with pulumi up applied; cannot verify network reachability from static code analysis"
  - test: "Cloud SQL instances reachable from temporal namespace"
    expected: "A test pod in the temporal namespace can connect to the temporal Cloud SQL instance"
    why_human: "Requires a live cluster; network connectivity cannot be verified from code alone"
  - test: "ExternalSecret resources reach Ready=True after pulumi up"
    expected: "kubectl get externalsecret -A shows all ExternalSecrets with Ready=True"
    why_human: "Requires ESO running in a live cluster with valid GCP credentials and populated Secret Manager secrets"
  - test: "Alembic migration Job completes successfully"
    expected: "Migration Job pod exits 0 and all schema tables exist in the app database"
    why_human: "Requires a running cluster, populated database-url secret, and a built application image"
---

# Phase 02: Database and Secrets Infrastructure Verification Report

**Phase Goal:** Application secrets are synced from GCP Secret Manager to Kubernetes Secrets via ESO, Cloud SQL instances are reachable from pods via Auth Proxy, and Alembic migrations run successfully
**Verified:** 2026-04-04T17:00:00Z
**Status:** human_needed
**Re-verification:** Yes — after gap closure (previous score 0/12, all files were missing)

## Goal Achievement

All four implementation files now exist on disk with substantive, wired implementations. All 12 previously-failed truths now pass static verification. Four success criteria require live cluster validation and cannot be verified from code alone.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | App Cloud SQL PG16 instance exists with private IP in GKE VPC | ✓ VERIFIED | `database.py` defines `app_db_instance` with `ipv4_enabled=False`, `private_network=cluster.network`, depends on `vpc_peering_connection` |
| 2 | Temporal Cloud SQL PG16 instance with temporal and temporal_visibility databases | ✓ VERIFIED | `database.py` defines `temporal_db_instance` plus `temporal_database` and `temporal_visibility_database` Database resources |
| 3 | VPC peering for servicenetworking established before Cloud SQL instances | ✓ VERIFIED | `global_address` → `vpc_peering_connection` → both instances via `ResourceOptions(depends_on=[vpc_peering_connection])` |
| 4 | vici-app GSA has cloudsql.client and secretmanager.secretAccessor IAM roles | ✓ VERIFIED | `iam.py` defines `app_gsa_cloudsql_client` (roles/cloudsql.client) and `app_gsa_secret_accessor` (roles/secretmanager.secretAccessor) bound to `app_gsa.email` |
| 5 | temporal-app GSA exists with cloudsql.client role and WIF binding | ✓ VERIFIED | `iam.py` defines `temporal_gsa` (serviceaccount.Account), `temporal_wi_binding` (IAMBinding for roles/iam.workloadIdentityUser), and `temporal_gsa_cloudsql_client` (IAMMember for roles/cloudsql.client) |
| 6 | vici-app KSA in vici namespace has WIF annotation | ✓ VERIFIED | `iam.py` defines `vici_app_ksa` with `annotations={"iam.gke.io/gcp-service-account": app_gsa.email}` in namespace vici |
| 7 | All 11 SECRETS-01 secrets exist as GCP Secret Manager resources | ✓ VERIFIED | `secrets.py` defines `_SECRET_DEFINITIONS` with 11 tuples; loop creates one `gcp.secretmanager.Secret` per slug using `ENV/slug` format |
| 8 | ESO Helm release installed in external-secrets namespace | ✓ VERIFIED | `secrets.py` defines `eso_release` as `k8s.helm.v3.Release` for chart `external-secrets` v0.10.7 from `https://charts.external-secrets.io` in namespace `external-secrets` |
| 9 | vici, temporal, observability namespaces each have a namespace-scoped SecretStore | ✓ VERIFIED | `secrets.py` loops over `_SECRETSTORE_NAMESPACES = ["vici", "temporal", "observability"]`, creating a `SecretStore` CR named `gcp-secret-manager` in each with WIF auth via the namespace-specific KSA |
| 10 | ExternalSecret CRs defined for every secret in each namespace | ✓ VERIFIED | `secrets.py` loops over all 11 `_SECRET_DEFINITIONS` tuples, creating an `ExternalSecret` CR per secret with `secretStoreRef`, `target`, and `data[].remoteRef` fields; depends on the namespace's SecretStore and the GCP secret |
| 11 | Migration Job has Auth Proxy as native sidecar initContainer | ✓ VERIFIED | `migration.py` defines a `k8s.batch.v1.Job` with an initContainer `cloud-sql-proxy` using `restart_policy="Always"` (K8s 1.28 native sidecar pattern), sharing the cloudsql-socket emptyDir volume with the main alembic container |
| 12 | Cloud SQL connection names exported for downstream consumption | ✓ VERIFIED | `database.py` exports `app_db_connection_name` and `temporal_db_connection_name` via `pulumi.export` |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `infra/components/database.py` | Cloud SQL instances, VPC peering, connection name exports | ✓ VERIFIED | 126 lines; GlobalAddress, servicenetworking.Connection, two DatabaseInstance, three Database, two pulumi.export |
| `infra/components/iam.py` | IAM role bindings for both GSAs, KSA annotations | ✓ VERIFIED | 92 lines; temporal GSA, WIF binding, two app IAMMember, one temporal IAMMember, two KSA resources |
| `infra/components/secrets.py` | ESO Helm, Secret Manager secrets, SecretStores, ExternalSecrets | ✓ VERIFIED | 161 lines; 11 SM secrets, ESO release, observability KSA, 3 SecretStores, 11 ExternalSecrets |
| `infra/components/migration.py` | Alembic migration Job with auth proxy native sidecar | ✓ VERIFIED | 108 lines; Job with initContainer restart_policy=Always, volume sharing, envFrom secret ref |
| `infra/__main__.py` | Imports all four phase 02 components | ✓ VERIFIED | Lines 14-17 import database, iam, secrets, migration with noqa F401 guards |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `database.py` | `cluster.py` | `cluster.network` for VPC self-link | ✓ WIRED | `from components.cluster import cluster`; used in GlobalAddress, vpc_peering_connection, both instance ip_configuration |
| `iam.py` | `identity.py` | `app_gsa` reference | ✓ WIRED | `from components.identity import app_gsa`; used in IAMMember member fields and KSA annotation |
| `migration.py` | `database.py` | `app_db_instance.connection_name` | ✓ WIRED | `from components.database import app_db_instance`; used as arg in cloud-sql-proxy initContainer args and in depends_on |
| `migration.py` | `secrets.py` | `external_secrets["database-url"]` depends_on | ✓ WIRED | `from components.secrets import external_secrets`; referenced in ResourceOptions depends_on |
| `secrets.py` | `namespaces.py` | `k8s_provider` and `namespaces` dict | ✓ WIRED | `from components.namespaces import k8s_provider, namespaces`; used in all k8s resource opts and namespace depends_on |
| `__main__.py` | `components.database` | import registration | ✓ WIRED | Line 14 imports `app_db_instance, temporal_db_instance` |
| `__main__.py` | `components.iam` | import registration | ✓ WIRED | Line 15 imports `temporal_gsa, vici_app_ksa, temporal_app_ksa` |
| `__main__.py` | `components.secrets` | import registration | ✓ WIRED | Line 16 imports `eso_release, secret_stores, external_secrets` |
| `__main__.py` | `components.migration` | import registration | ✓ WIRED | Line 17 imports `migration_job` |

### Data-Flow Trace (Level 4)

Not applicable — phase 02 delivers Pulumi IaC definitions (cloud resource declarations), not components that render runtime data. The relevant data flows (secrets from GCP SM to K8s Secrets, DB connections from Auth Proxy to app) are live-cluster behaviors covered in Human Verification.

### Behavioral Spot-Checks

Step 7b: SKIPPED — Pulumi programs require `pulumi up` against a live GCP project and GKE cluster. No runnable static entry point exists for offline verification.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| DB-01 | App Cloud SQL PG16 instance | ✓ SATISFIED | `app_db_instance` in database.py |
| DB-02 | App-prod REGIONAL HA, others ZONAL | ✓ SATISFIED | `_HA_TYPE` dict in database.py keyed by env |
| DB-03 | vici-app KSA WIF annotation | ✓ SATISFIED | `vici_app_ksa` with annotation in iam.py |
| DB-04 | Alembic migration Job | ✓ SATISFIED | `migration_job` in migration.py |
| DB-05 | Temporal dedicated Cloud SQL instance | ✓ SATISFIED | `temporal_db_instance` with temporal + temporal_visibility databases |
| SECRETS-01 | GCP Secret Manager resources for all secrets | ✓ SATISFIED | 11 `gcp.secretmanager.Secret` resources in secrets.py |
| SECRETS-02 | ESO Helm release installed | ✓ SATISFIED | `eso_release` Helm release in secrets.py |
| SECRETS-03 | Namespace-scoped SecretStores | ✓ SATISFIED | 3 SecretStore CRs looped over `_SECRETSTORE_NAMESPACES` |
| SECRETS-04 | ExternalSecret CRs for all secrets | ✓ SATISFIED | 11 ExternalSecret CRs looped over `_SECRET_DEFINITIONS` |
| SECRETS-05 | vici-app GSA has secretmanager.secretAccessor | ✓ SATISFIED | `app_gsa_secret_accessor` IAMMember in iam.py |

### Anti-Patterns Found

None — no TODO/FIXME comments, placeholder returns, or stub patterns found in any of the four implementation files.

### Human Verification Required

The following four success criteria from the ROADMAP cannot be verified from static code analysis. They require `pulumi up` applied against a live GCP project and GKE cluster.

#### 1. vici namespace Auth Proxy connectivity

**Test:** Deploy a debug pod to the `vici` namespace with a Cloud SQL Auth Proxy sidecar. Attempt `psql $DATABASE_URL` where DATABASE_URL uses the unix socket path.
**Expected:** psql connects successfully to the app Cloud SQL instance
**Why human:** Network reachability from pod to Cloud SQL private IP, WIF token issuance, and Auth Proxy socket creation cannot be verified from code alone

#### 2. temporal namespace Auth Proxy connectivity

**Test:** Deploy a debug pod to the `temporal` namespace and attempt a psql connection to the temporal Cloud SQL instance via Auth Proxy socket.
**Expected:** Connection succeeds; temporal and temporal_visibility databases are accessible
**Why human:** Same as above — requires live cluster and GCP IAM to be functional

#### 3. ExternalSecret Ready=True state

**Test:** After `pulumi up`, run `kubectl get externalsecret -A`.
**Expected:** All 11 ExternalSecret resources show `READY=True` and `AGE` reflects recent sync
**Why human:** Requires ESO pods running, GCP SM secrets populated with actual values, and WIF credentials valid. GCP SM secrets are created as empty resources by Pulumi — secret *values* must be populated separately before ESO can sync them.

#### 4. Alembic migration Job completion

**Test:** After `pulumi up`, check the migration Job: `kubectl get job alembic-migration-dev -n vici` and `kubectl logs -l job-name=alembic-migration-dev -n vici`.
**Expected:** Job shows `COMPLETIONS: 1/1`; logs show `Running upgrade` steps with no errors
**Why human:** Requires a built application image pushed to Artifact Registry, the `database-url` secret populated in GCP SM, and the full auth chain (WIF → Auth Proxy → Cloud SQL) to be functional

### Gaps Summary

All 12 code-level gaps from the previous verification are closed. The four human verification items above represent live-cluster integration checks that are inherent to infrastructure code — they cannot be resolved by further static changes. The Pulumi program is complete and correct as written.

---

_Verified: 2026-04-04T17:00:00Z_
_Verifier: Claude (gsd-verifier)_
