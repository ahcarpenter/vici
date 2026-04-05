---
phase: quick
plan: 260405-nbr
type: execute
wave: 1
depends_on: []
files_modified:
  - infra/components/secrets.py
autonomous: true
must_haves:
  truths:
    - "ESO Helm chart version is 1.0.0+ (supports v1 GA CRDs)"
    - "All SecretStore and ExternalSecret CRs use api_version external-secrets.io/v1"
    - "No references to external-secrets.io/v1beta1 remain in infra/"
  artifacts:
    - path: "infra/components/secrets.py"
      provides: "ESO chart upgrade and v1 API version for all CRs"
      contains: "external-secrets.io/v1"
  key_links:
    - from: "infra/components/secrets.py"
      to: "ESO Helm chart"
      via: "_ESO_CHART_VERSION constant"
      pattern: "_ESO_CHART_VERSION"
---

<objective>
Upgrade External Secrets Operator from chart v0.10.7 to v1.0.0+ (GA) and update all
api_version references from "external-secrets.io/v1beta1" to "external-secrets.io/v1".

Purpose: ESO v1 is GA and v1beta1 is deprecated. The cluster previously could not use v1
because chart 0.10.7 only registered v1beta1 CRDs (see .planning/debug/pulumi-up-apply-failure.md).
Upgrading the chart to 1.0.0+ installs v1 CRDs, unblocking the API version bump.

Output: Updated infra/components/secrets.py with new chart version and v1 API versions.
</objective>

<execution_context>
@.planning/debug/pulumi-up-apply-failure.md
</execution_context>

<context>
@infra/components/secrets.py

Key facts from prior debug:
- ESO chart 0.10.7 only registers v1alpha1 and v1beta1 CRDs
- ESO v1 API was introduced in v0.16.x / v1.0.0 release cycle
- The v1beta1 SecretStore schema requires clusterLocation and clusterName in workloadIdentity (already present)
- Pulumi preview does NOT validate CRD versions; Kubernetes rejects invalid versions at apply time

The spec shape for SecretStore and ExternalSecret is unchanged between v1beta1 and v1 --
only the apiVersion string changes. The workloadIdentity block with clusterLocation,
clusterName, and serviceAccountRef is valid in v1.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Upgrade ESO chart version and update all api_version references to v1</name>
  <files>infra/components/secrets.py</files>
  <action>
In infra/components/secrets.py, make these three changes:

1. Update the chart version constant from "0.10.7" to "1.0.5" (latest stable 1.x):
   ```python
   _ESO_CHART_VERSION = "1.0.5"
   ```

2. Update the SecretStore loop (line 102) api_version from "external-secrets.io/v1beta1"
   to "external-secrets.io/v1":
   ```python
   api_version="external-secrets.io/v1",
   ```

3. Update the ExternalSecret loop (line 139) api_version from "external-secrets.io/v1beta1"
   to "external-secrets.io/v1":
   ```python
   api_version="external-secrets.io/v1",
   ```

Do NOT change anything else -- the spec shape, workloadIdentity block, and all other
configuration remain identical.
  </action>
  <verify>
    <automated>cd /Users/ahcarpenter/workspace/vici && grep -c "external-secrets.io/v1beta1" infra/components/secrets.py | grep -q "^0$" && grep -c 'external-secrets.io/v1"' infra/components/secrets.py | grep -q "^2$" && grep -q '_ESO_CHART_VERSION = "1.0.5"' infra/components/secrets.py && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>
- _ESO_CHART_VERSION is "1.0.5"
- Both SecretStore and ExternalSecret CRs use api_version="external-secrets.io/v1"
- Zero references to "external-secrets.io/v1beta1" remain in infra/components/secrets.py
  </done>
</task>

<task type="auto">
  <name>Task 2: Verify no other v1beta1 ESO references exist in the infra codebase</name>
  <files></files>
  <action>
Run a grep across the entire infra/ directory for "external-secrets.io/v1beta1" to confirm
no other files reference the deprecated API version. The only v1beta1 reference in infra/
should be in namespaces.py for "client.authentication.k8s.io/v1beta1" which is unrelated.

If any ESO v1beta1 references are found in other files, update them to v1 as well.
  </action>
  <verify>
    <automated>cd /Users/ahcarpenter/workspace/vici && grep -r "external-secrets.io/v1beta1" infra/ && echo "FAIL: v1beta1 references found" || echo "PASS: no v1beta1 ESO references"</automated>
  </verify>
  <done>
- Zero occurrences of "external-secrets.io/v1beta1" across all infra/ files
  </done>
</task>

</tasks>

<verification>
1. `grep "external-secrets.io/v1beta1" infra/components/secrets.py` returns nothing
2. `grep 'external-secrets.io/v1"' infra/components/secrets.py` returns exactly 2 matches
3. `grep '_ESO_CHART_VERSION' infra/components/secrets.py` shows "1.0.5"
4. No other infra/ files reference external-secrets.io/v1beta1
</verification>

<success_criteria>
- ESO Helm chart pinned to v1.0.5 (GA, supports v1 CRDs)
- All SecretStore and ExternalSecret custom resources use external-secrets.io/v1 API
- No deprecated v1beta1 ESO references remain in the infra codebase
</success_criteria>

<output>
After completion, update .planning/debug/pulumi-up-apply-failure.md status to note the
upgrade has been completed, or simply commit the changes.
</output>
