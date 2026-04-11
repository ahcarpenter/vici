---
status: awaiting_human_verify
trigger: "CD Dev workflow fails with blanket 403 Permission Denied on ALL GCP resources after fixing the pulumi-gcp provider panic"
created: 2026-04-06T00:00:00Z
updated: 2026-04-06T00:00:00Z
---

## Current Focus

hypothesis: CONFIRMED — ci_push_sa missing deployer IAM roles
test: Code fix applied in cd.py; bootstrap gcloud commands needed before Pulumi can self-manage
expecting: After bootstrap + push, pulumi up succeeds with no 403s
next_action: User must run gcloud bootstrap commands, then push commit to trigger CD

## Symptoms

expected: `pulumi up --refresh` succeeds in the CD Dev GitHub Actions workflow, deploying GKE infrastructure to GCP project `vici-app-dev`
actual: Every GCP resource refresh fails with 403 Permission Denied. Errors include secretmanager.secrets.get, iam.serviceAccounts.get, iam.workloadIdentityPools.get, compute.regions.list denied.
errors: |
  gcp:iam:WorkloadIdentityPool github-wif-pool: Permission 'iam.workloadIdentityPools.get' denied
  gcp:serviceaccount:Account temporal-gsa: Permission 'iam.serviceAccounts.get' denied
  gcp:secretmanager:Secret sm-twilio-auth-token: Permission 'secretmanager.secrets.get' denied
  gcp:artifactregistry:Repository vici-registry: Permission denied
  gcp:sql:DatabaseInstance temporal-db-dev: Permission denied
  ALL GCP resources fail — not just one type.
reproduction: Push to main -> CD Dev workflow runs -> pulumi up --refresh fails on all GCP resources
started: After fixing __pulumi_raw_state_delta panic (commit edf7c40); the 403s were previously masked by the provider crash

## Eliminated

## Evidence

- timestamp: 2026-04-06
  checked: cd.py — IAM roles bound to ci_push_sa
  found: Only roles/storage.objectAdmin (Pulumi state bucket) and roles/container.developer (GKE deploy)
  implication: Missing permissions for secretmanager, iam, compute, sql, servicenetworking, artifactregistry admin

- timestamp: 2026-04-06
  checked: registry.py — IAM roles bound to ci_push_sa
  found: Only roles/artifactregistry.writer on the single registry resource
  implication: Can push images but cannot manage (create/delete) the registry resource itself

- timestamp: 2026-04-06
  checked: identity.py, iam.py — any other ci_push_sa bindings
  found: None — no other IAM bindings reference ci_push_sa
  implication: Confirms ci_push_sa has exactly 3 roles total, all too narrow for infrastructure management

- timestamp: 2026-04-06
  checked: Full list of GCP resource types in Pulumi program
  found: container.Cluster, sql.DatabaseInstance, sql.Database, secretmanager.Secret, secretmanager.SecretVersion, serviceaccount.Account, serviceaccount.IAMBinding, iam.WorkloadIdentityPool, iam.WorkloadIdentityPoolProvider, projects.IAMMember, compute.GlobalAddress, servicenetworking.Connection, artifactregistry.Repository, artifactregistry.RepositoryIamMember
  implication: CI SA needs permissions spanning container, sql, secretmanager, iam, compute, servicenetworking, artifactregistry — a broad deployer role set

## Resolution

root_cause: The CI service account (vici-ci-push / ci_push_sa) is used by GitHub Actions as the Pulumi deployer but only has 3 narrow IAM roles: artifactregistry.writer, storage.objectAdmin, and container.developer. It completely lacks permissions for secretmanager, iam, compute, sql, and servicenetworking — all required to manage the infrastructure resources defined in the Pulumi program. Every GCP API call returns 403 because the SA has no grants for those services.
fix: Replaced the 2 narrow IAM bindings (storage.objectAdmin, container.developer) in cd.py with a comprehensive _CI_DEPLOYER_ROLES list of 10 project-level roles covering every GCP service in the Pulumi program. Chicken-and-egg: these roles must be bootstrapped via gcloud before Pulumi can self-manage them.
verification: awaiting human bootstrap + CI run
files_changed: ["infra/components/cd.py"]
