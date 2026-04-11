---
phase: 06-infra-best-practice-audit-and-edge-case-hardening
reviewed: 2026-04-11T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - tests/infra/test_phase6_static.py
  - infra/components/cluster.py
  - infra/components/database.py
  - infra/components/registry.py
  - infra/components/state_bucket.py
  - infra/components/network_policy.py
  - infra/components/secrets.py
  - infra/components/temporal.py
  - infra/components/pdb.py
  - infra/components/migration.py
  - infra/components/opensearch.py
  - infra/__main__.py
  - infra/Pulumi.dev.yaml
  - infra/OPERATIONS.md
findings:
  critical: 1
  warning: 4
  info: 6
  total: 11
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-04-11
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 6 delivers the five success criteria well overall: `protect=True` is applied
consistently across stateful GCP resources, NetworkPolicies implement a solid
default-deny + explicit-allow pattern across all five namespaces, Temporal DB
credentials flow from Secret Manager through ESO using `existingSecret`,
PDBs are env-conditional, and the OPERATIONS.md runbook covers the required
sections. Resource limits, security contexts, and `depends_on` wiring on the
Job and Helm resources are in good shape.

The review surfaced one critical correctness bug in `secrets.py` where the
`temporal-db-password` entry is processed twice (once by the generic loop, once
by the explicit override), producing two Pulumi-managed ExternalSecret resources
that both target the same Kubernetes object. This will fail at `pulumi up`.
Other findings are lower-severity: a PDB configuration that will block
voluntary disruptions if staging runs single-replica workloads, a couple of
DRY/consistency smells, and documentation/style issues.

No security vulnerabilities were found. No hardcoded secrets, no privileged
containers, no unsafe shell expansions. The `encryptionsalt` value in
`Pulumi.dev.yaml` is a Pulumi passphrase salt (not sensitive on its own) and is
safe to commit.

## Critical Issues

### CR-01: Duplicate ExternalSecret for `temporal-db-credentials` causes `pulumi up` conflict

**File:** `infra/components/secrets.py:137-190`
**Issue:** `temporal-db-password` is included in `_SECRET_DEFINITIONS` (line 31),
so the generic loop at lines 137-158 creates an `ExternalSecret` named
`temporal-db-credentials` in the `temporal` namespace with `secretKey=TEMPORAL_DB_PASSWORD`
and `target.name=temporal-db-credentials` (creationPolicy: Owner). Lines 167-190
then create a **second** Pulumi resource (`ext-secret-temporal-db-credentials`)
with the **same** K8s `metadata.name` (`temporal-db-credentials`), same namespace
(`temporal`), and same target secret name, but with `secretKey=password`.

Both Pulumi resources will attempt to create/own the same Kubernetes object.
Outcomes:
  1. `pulumi up` will fail with "resource already exists" on whichever is
     applied second (Pulumi only keeps deterministic ordering between the two
     resources via `depends_on`; here there is no ordering, so Pulumi may create
     them in parallel and either could fail).
  2. Even if creation somehow succeeded, ESO would see two owning ExternalSecrets
     for the same K8s Secret and flap the target's data between
     `{TEMPORAL_DB_PASSWORD: …}` and `{password: …}` every reconcile loop.
  3. The Temporal Helm chart expects `secretKey=password`, so the generic-loop
     variant is also functionally wrong even if it were the only one.

Additionally, `external_secrets["temporal-db-password"]` is assigned once at
line 138 and then overwritten at line 167 — but the first Pulumi resource is
**not** deleted from Pulumi state by the dict overwrite, only the Python handle
is lost. Both remain registered.

**Fix:** Skip `temporal-db-password` inside the generic loop and only create the
explicit override:

```python
# secrets.py
_GENERIC_SECRET_DEFINITIONS = [
    entry for entry in _SECRET_DEFINITIONS if entry[0] != "temporal-db-password"
]

external_secrets: dict[str, k8s.apiextensions.CustomResource] = {}
for _slug, _ns, _k8s_name in _GENERIC_SECRET_DEFINITIONS:
    external_secrets[_slug] = k8s.apiextensions.CustomResource(
        f"ext-secret-{_slug}",
        ...
    )

# Then create the custom temporal-db-credentials ExternalSecret exactly once.
external_secrets["temporal-db-password"] = k8s.apiextensions.CustomResource(
    "ext-secret-temporal-db-credentials",
    ...
)
```

Note that the Secret Manager secret in `sm_secrets["temporal-db-password"]` still
needs to be created by the upstream loop — keep that loop over the full
`_SECRET_DEFINITIONS` list; only the ExternalSecret loop should exclude it.

## Warnings

### WR-01: PDB with `min_available=1` will block node upgrades for single-replica staging workloads

**File:** `infra/components/pdb.py:14-42`
**Issue:** All three PDBs are created with `min_available=1` in staging and prod.
The module docstring explains why dev is skipped ("minAvailable=1 would block
node upgrades entirely"), but that exact failure mode applies to any
staging/prod workload that runs with `replicas=1`. GKE Autopilot performs
voluntary disruptions (node replacements, version upgrades) that will be blocked
indefinitely if the PDB forbids evicting the only replica.

The `vici-app` HPA and the Temporal chart both default to `replicas=1` in
lower-cost environments. If staging runs with a single replica of any of
`vici-app`, `temporal-frontend`, or `temporal-history`, upgrades will stall
silently on that workload.

**Fix:** Either (a) ensure staging deployments always run `replicas >= 2` (e.g.,
by gating HPA minReplicas and Temporal chart values) and document it, or
(b) switch staging PDBs to `max_unavailable=1` and reserve `min_available` for
prod. The simplest change:

```python
# pdb.py
_PDB_DEFINITIONS: list[tuple[str, str, str, dict[str, str], str, int]] = [
    ("vici-app-pdb", "vici-app", "vici", {"app": "vici"}, "max_unavailable", 1),
    ...
]

if ENV in ("staging", "prod"):
    for name, k8s_name, ns, labels, mode, value in _PDB_DEFINITIONS:
        spec_kwargs = {mode: value, "selector": ...}
        ...
```

Alternatively, document the replica-count requirement in `OPERATIONS.md` under
the cluster upgrade section and add a pre-upgrade check that PDBs are not
blocking.

### WR-02: Unix-socket path mismatch risk between cloud-sql-proxy and DATABASE_URL

**File:** `infra/components/migration.py:50-57, 80-91`
**Issue:** The Auth Proxy is started with `--unix-socket=/cloudsql` (line 54).
In cloud-sql-proxy v2 the `--unix-socket=<dir>` form creates
`/cloudsql/<project>:<region>:<instance>/.s.PGSQL.5432`. The `database-url`
secret is documented in `OPERATIONS.md` as
`postgresql+asyncpg:///vici?host=/cloudsql/{connection_name}`, which relies
on that per-instance subdirectory path.

This works at runtime only when the secret value is kept strictly in sync with
the Cloud SQL instance connection name. There is no programmatic coupling
between `app_db_instance.connection_name` and the manually-populated
`database-url` secret. Any rename of the Cloud SQL instance, env change, or
typo in Secret Manager silently breaks migrations and app startup.

**Fix:** Generate the `database-url` ExternalSecret from the Cloud SQL instance
output rather than a hand-populated Secret Manager value, or at minimum add a
startup probe / pre-migration sanity-check that resolves the socket path before
running `alembic upgrade head`. Alternatively document that rotating the
Cloud SQL connection name requires updating `{env}-database-url` in Secret
Manager, and add that step to `OPERATIONS.md`.

### WR-03: `allow_policies` and `dns_allow_policies` are never imported in `__main__.py`

**File:** `infra/__main__.py:28`, `infra/components/network_policy.py:46-110`
**Issue:** `__main__.py` only imports `default_deny_policies` from
`components.network_policy`. The per-namespace allow policies and DNS allow
policies are registered as a side-effect of the module being imported (Python
executes top-level statements once on first import), so today they are applied.
This is fragile:

  1. Any future refactor that moves the allow rules behind a function / lazy
     init, or that removes the `default_deny_policies` import, will silently drop
     those NetworkPolicies from the stack.
  2. A reader scanning `__main__.py` cannot tell which network policies are
     actually included; the surface-level contract hides the real behavior.
  3. Static tests in `test_phase6_static.py` would pass even if the allow rules
     were inadvertently gated behind `if False:`.

**Fix:** Import all three dicts explicitly to make the contract visible:

```python
# __main__.py
from components.network_policy import (  # noqa: F401
    allow_policies,
    default_deny_policies,
    dns_allow_policies,
)
```

### WR-04: Wildcard ingress on Jaeger UI port 16686 bypasses default-deny in observability

**File:** `infra/components/network_policy.py:302-307`
**Issue:** The `obs-ingress` policy allows port 16686 from any source with no
`from_=` restriction. Combined with the default-deny baseline this is the
*intended* "jaeger UI from any (port-forward access)" behavior noted in the
comment and tagged `T-6-03c: accept`. However, "any" here means any pod in any
namespace, **including** pods outside the cluster that can reach the pod IP
(e.g., via Service of type LoadBalancer). Today there is no LB for Jaeger, but
the policy does not defend against future drift where someone exposes the
service externally. Combined with OpenSearch running with
`plugins.security.disabled: true` and the visibility index reachable on 9200
from any pod in the temporal namespace, an attacker with a foothold in that
namespace could read workflow metadata.

**Fix:** Either tighten the selector to only allow ingress from specific
namespaces (e.g., `kube-system` for port-forward, or a dedicated admin
namespace), or add a code comment + lint guard confirming that no
`Service.type=LoadBalancer` is ever attached to Jaeger. Document the accepted
risk in `OPERATIONS.md` alongside the NetworkPolicy section.

## Info

### IN-01: `test_app_db_has_protect_true` and `test_temporal_db_has_protect_true` are functionally identical

**File:** `tests/infra/test_phase6_static.py:50-66`
**Issue:** Both tests `.count("protect=True") >= 2` on the same source string.
Either one passing guarantees the other. The second is dead code for the static
assertion it claims to be making.

**Fix:** Replace one of them with a regex that verifies `protect=True` appears
within both `app_db_instance` and `temporal_db_instance` resource blocks:

```python
def test_temporal_db_has_protect_true(self) -> None:
    source = _read_source("database.py")
    temporal_block = re.search(
        r"temporal_db_instance\s*=\s*gcp\.sql\.DatabaseInstance\((.*?)\)\s*\n\n",
        source,
        re.DOTALL,
    )
    assert temporal_block and "protect=True" in temporal_block.group(1)
```

### IN-02: Duplicate `_AUTH_PROXY_IMAGE`, `_AUTH_PROXY_RUN_AS_USER`, job TTL, and backoff constants across `migration.py` and `temporal.py`

**File:** `infra/components/migration.py:15-21`, `infra/components/temporal.py:16-22`
**Issue:** Five module-level constants are duplicated verbatim between the two
Job modules (`_AUTH_PROXY_IMAGE`, `_AUTH_PROXY_RUN_AS_USER`,
`_SCHEMA_JOB_BACKOFF_LIMIT`/`_JOB_BACKOFF_LIMIT`,
`_SCHEMA_JOB_TTL_SECONDS`/`_JOB_TTL_SECONDS`). DRY violation per AGENTS.md.
Next Cloud SQL Auth Proxy bump will require two edits.

**Fix:** Move shared constants to a new `components/constants.py` (or
`components/cloudsql.py`) and import from both:

```python
# components/cloudsql.py
AUTH_PROXY_IMAGE = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1"
AUTH_PROXY_RUN_AS_USER = 65532
JOB_BACKOFF_LIMIT = 0
JOB_TTL_SECONDS = 300
```

### IN-03: `_default_deny` and `_dns_allow` map/assignments could be a single loop

**File:** `infra/components/network_policy.py:92-110`
**Issue:** Ten explicit dict assignments (`default_deny_policies["vici"] = ...`,
`default_deny_policies["temporal"] = ...`, etc.) where a single loop over
`_NAMESPACES` would express the same thing. The existing inline comments note
"explicit for static analysis" — but `test_phase6_static.py` only counts
occurrences of the string literals `"default-deny-all"` and
`"allow-dns-egress"`, which still appear once in each helper function. The
loop form would produce identical pattern counts.

**Fix:**

```python
for ns in _NAMESPACES:
    default_deny_policies[ns] = _default_deny(ns)  # default-deny-all
    dns_allow_policies[ns] = _dns_allow(ns)  # allow-dns-egress
```

This halves the line count and removes the risk of forgetting a namespace when
the list changes.

### IN-04: State bucket uses multi-region `US` regardless of env

**File:** `infra/components/state_bucket.py:25`
**Issue:** `location="US"` is hardcoded to the multi-region for all environments.
Dev and staging do not need multi-region durability for their Pulumi state;
single-region would be cheaper and lower latency. Not a bug — noting for
hygiene.

**Fix:** Parameterize by env if desired:

```python
_STATE_BUCKET_LOCATION = {"dev": "us-central1", "staging": "us-central1", "prod": "US"}
state_bucket = gcp.storage.Bucket(
    ...,
    location=_STATE_BUCKET_LOCATION.get(ENV, "US"),
    ...
)
```

### IN-05: `_SECRETSTORE_NAMESPACES` and `_KSA_BY_NAMESPACE` hold parallel data

**File:** `infra/components/secrets.py:35-42`
**Issue:** `_SECRETSTORE_NAMESPACES` lists namespaces and `_KSA_BY_NAMESPACE` maps
the same keys to KSA names. If a namespace is added to one without the other,
the loop at line 100 raises a `KeyError` at plan time. Low risk but a minor
single-source-of-truth improvement:

**Fix:**

```python
_SECRETSTORE_KSA: dict[str, str] = {
    "vici": "vici-app",
    "temporal": "temporal-app",
    "observability": "observability-app",
}

for _ns, _ksa in _SECRETSTORE_KSA.items():
    secret_stores[_ns] = k8s.apiextensions.CustomResource(
        ...,
        spec={..., "serviceAccountRef": {"name": _ksa}, ...},
    )
```

### IN-06: `_TEMPORAL_DB_USER = "temporal"` and DB name `"temporal"` are magic strings

**File:** `infra/components/temporal.py:39, 191`, `infra/components/database.py:112`
**Issue:** The Postgres username/database name `"temporal"` appears in
`temporal.py` as `_TEMPORAL_DB_USER` and in `database.py` as the literal
`name="temporal"` for the `gcp.sql.Database` resource. If the convention is
ever to version or rename this (`temporal_v2`), two files need to change in
lockstep. Same for `"temporal_visibility"`.

**Fix:** Hoist to `config.py` or a new `components/temporal_config.py`:

```python
TEMPORAL_DB_NAME = "temporal"
TEMPORAL_VISIBILITY_DB_NAME = "temporal_visibility"
TEMPORAL_DB_USER = "temporal"
```

Import from both modules.

---

_Reviewed: 2026-04-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
