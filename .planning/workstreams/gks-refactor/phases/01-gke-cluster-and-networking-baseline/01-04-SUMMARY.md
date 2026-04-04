# Plan 01-04 Summary — Dev Environment Provisioning

## Status: Complete

## Success Criteria

| Criterion | Result |
|-----------|--------|
| `pulumi up --stack dev` exits 0, 13 resources created | ✓ |
| `pulumi preview --stack dev --expect-no-changes` exits 0 | ✓ |
| All 5 namespaces Active | ✓ (vici, temporal, observability, cert-manager, external-secrets) |
| Artifact Registry vici-images exists | ✓ |
| Workload Identity pool set on cluster | ✓ (vici-app-dev.svc.id.goog) |
| All 6 Pulumi stack outputs non-empty | ✓ |

## Resources Created
- **Cluster:** `vici-dev` (GKE Autopilot, us-central1)
- **Endpoint:** `35.194.56.111`
- **Registry:** `us-central1-docker.pkg.dev/vici-app-dev/vici-images`
- **App GSA:** `vici-app@vici-app-dev.iam.gserviceaccount.com`
- **CI Push SA:** `vici-ci-push@vici-app-dev.iam.gserviceaccount.com`

## Issues Encountered
1. **WI binding race condition** — `app-wi-binding` ran in parallel with cluster creation. The WIF pool (`vici-app-dev.svc.id.goog`) only exists after GKE cluster is provisioned. Fixed by adding `depends_on=[cluster]` to `wi_binding` in `identity.py`.
2. **Missing gke-gcloud-auth-plugin** — Installed via `gcloud components install gke-gcloud-auth-plugin`. Required for K8s provider auth.
3. **Pulumi venv not found** — Added `virtualenv: .venv` to `Pulumi.yaml` runtime options.

## Staging and Prod Status
- Pending — stacks initialized, GCS buckets exist, APIs enabled. Run `pulumi up --stack staging/prod` when ready.

## GitHub Actions Secrets Required
| Secret | Value |
|--------|-------|
| `PULUMI_CONFIG_PASSPHRASE` | Set during bootstrap (replace "changeme" with real value) |
| `PULUMI_BACKEND_URL_DEV` | `gs://vici-app-pulumi-state-dev` |
| `PULUMI_BACKEND_URL_STAGING` | `gs://vici-app-pulumi-state-staging` |
| `PULUMI_BACKEND_URL_PROD` | `gs://vici-app-pulumi-state-prod` |
