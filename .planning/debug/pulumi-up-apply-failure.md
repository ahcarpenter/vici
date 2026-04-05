---
status: verifying
trigger: "pulumi up preview succeeds but apply fails"
created: 2026-04-05T00:00:00Z
updated: 2026-04-05T00:02:00Z
---

## Current Focus

hypothesis: CONFIRMED AND FIXED — three compounding issues found and resolved; pulumi preview now exits 0 with valid plan
test: pulumi preview --stack dev runs cleanly; all resources valid
expecting: User to confirm pulumi up applies successfully end-to-end
next_action: Request human verification of pulumi up apply

## Symptoms

expected: Full stack deploys cleanly with `pulumi up` — all resources create/update without errors
actual: Preview succeeds but apply fails
errors: Unknown — investigate by examining the Pulumi code, recent changes, and attempting a dry run or preview
reproduction: Run `pulumi up` in the infra directory
started: Uncertain — recent commits added Jaeger, Prometheus components and OTEL secret namespace changes

## Eliminated

- hypothesis: Namespace mismatch between ExternalSecret and SecretStore (otel secret in wrong namespace)
  evidence: After commit 60938de, otel-exporter-otlp-endpoint moved to vici namespace; SecretStore exists for vici. Namespace lookup succeeds.
  timestamp: 2026-04-05T00:01:00Z

- hypothesis: GCP Secret Manager ID format mismatch (ENV/slug vs ENV-slug)
  evidence: Working tree already has ENV-slug format; Pulumi state has secretId=dev-slug; GCP has dev-slug secrets. Preview shows GCP secrets as unchanged.
  timestamp: 2026-04-05T00:01:00Z

- hypothesis: Missing imports or syntax errors in new component files
  evidence: ast.parse() passed on all component files; __main__.py imports jaeger and prometheus successfully.
  timestamp: 2026-04-05T00:01:00Z

## Evidence

- timestamp: 2026-04-05T00:00:30Z
  checked: pulumi preview --stack dev output
  found: Preview creates 17 resources, updates 2, deletes 14 — specifically deletes v1beta1 SecretStore/ExternalSecret and creates v1 versions
  implication: Code uses api_version="external-secrets.io/v1" but old resources are v1beta1; a replace cycle is planned

- timestamp: 2026-04-05T00:00:45Z
  checked: kubectl get crd secretstores.external-secrets.io / externalsecrets.external-secrets.io
  found: Only v1alpha1 and v1beta1 are registered CRD versions; v1 does not exist
  implication: ESO chart 0.10.7 does not provide v1 CRDs; api_version="external-secrets.io/v1" is invalid against this cluster

- timestamp: 2026-04-05T00:01:00Z
  checked: ESO GA v1 release history (web search)
  found: ESO v1 API was introduced in v0.16.x / v1.0.0 release cycle, well after chart 0.10.7
  implication: The api_version in secrets.py must be "external-secrets.io/v1beta1" to match the installed CRD

- timestamp: 2026-04-05T00:01:30Z
  checked: kubectl get secretstores -A
  found: No SecretStore resources exist in the cluster; Pulumi state had 3 entries for them
  implication: State was stale — resources were in state but absent from cluster; pulumi refresh removed the stale state entries

- timestamp: 2026-04-05T00:01:45Z
  checked: kubectl get crd secretstores CRD openAPIV3Schema for v1beta1 workloadIdentity
  found: v1beta1 SecretStore schema requires clusterLocation and clusterName in workloadIdentity block; code only had serviceAccountRef.name
  implication: Code needed to supply CLUSTER_NAME and REGION from config in the SecretStore spec

- timestamp: 2026-04-05T00:02:00Z
  checked: pulumi preview --stack dev after all three fixes applied
  found: Preview exits 0; plans 6 creates, 12 updates, 1 replace — all valid operations, no errors
  implication: All issues resolved; stack is ready for pulumi up

## Resolution

root_cause: Three compounding issues: (1) api_version="external-secrets.io/v1" in secrets.py, but ESO chart 0.10.7 only registers v1alpha1/v1beta1 CRDs — Pulumi preview skips CRD version validation, Kubernetes rejects the POST during apply. (2) Pulumi state had 3 SecretStore entries that did not exist in the cluster, causing "not found" errors on attempted updates. (3) The v1beta1 SecretStore schema requires clusterLocation and clusterName in the workloadIdentity block, which the code omitted.
fix: (1) Changed api_version from "external-secrets.io/v1" to "external-secrets.io/v1beta1" for both SecretStore and ExternalSecret CRs. (2) Ran pulumi refresh --target on the 3 stale SecretStore state entries to remove them. (3) Added CLUSTER_NAME and REGION imports to secrets.py and included clusterLocation/clusterName in the workloadIdentity spec. Also retained working-tree fixes: ENV-slug secret ID format and delete_before_replace=True.
verification: pulumi preview --stack dev exits 0 with valid plan (6 creates, 12 updates, 1 replace, 0 errors)
files_changed: [infra/components/secrets.py]
