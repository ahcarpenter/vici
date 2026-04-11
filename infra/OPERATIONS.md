# Vici GKE Infrastructure Operations

Operational procedures for the Vici GKE Autopilot infrastructure managed by Pulumi.

## Table of Contents

1. [Cold-Start Ordering](#cold-start-ordering)
2. [Secret Rotation](#secret-rotation)
3. [Cluster Upgrade](#cluster-upgrade)
4. [Protected Resource Teardown](#protected-resource-teardown)

---

## Cold-Start Ordering

A cold-start provisions infrastructure from scratch (new environment or full rebuild).

### Prerequisites

- GCP project with billing enabled
- `gcloud` CLI authenticated with project owner
- `pulumi` CLI installed and logged in to GCS backend
- GCS state bucket created: `vici-app-pulumi-state-{env}`
- GCP Secret Manager secrets populated (see Secret Inventory below)

### Provisioning Order

Pulumi resolves dependencies automatically via `depends_on`. A single `pulumi up` provisions
everything. However, for debugging or partial deploys, the dependency chain is:

1. **GKE Cluster** (`cluster.py`) - no dependencies
2. **Namespaces** (`namespaces.py`) - depends on cluster
3. **IAM / Identity** (`identity.py`, `iam.py`) - depends on cluster
4. **VPC Peering + Cloud SQL** (`database.py`) - depends on cluster network
5. **Artifact Registry** (`registry.py`) - depends on CI SA from identity
6. **ESO Helm Release** (`secrets.py`) - depends on namespaces
7. **SecretStores + ExternalSecrets** (`secrets.py`) - depends on ESO release + namespaces
8. **OpenSearch** (`opensearch.py`) - depends on observability namespace
9. **Temporal Schema Migration** (`temporal.py`) - depends on Cloud SQL + ESO secrets
10. **Temporal Helm Release** (`temporal.py`) - depends on schema migration + OpenSearch
11. **Alembic Migration** (`migration.py`) - depends on Cloud SQL + ESO secrets
12. **App Deployment + HPA** (`app.py`) - depends on migration + ESO secrets
13. **cert-manager** (`certmanager.py`) - depends on cert-manager namespace
14. **Ingress** (`ingress.py`) - depends on app service + cert-manager
15. **Observability** (`jaeger.py`, `prometheus.py`) - depends on observability namespace + OpenSearch
16. **NetworkPolicies** (`network_policy.py`) - depends on namespaces
17. **PDBs** (`pdb.py`) - depends on namespaces (staging/prod only)

### First-Time Setup Commands

```bash
# 1. Select stack
cd infra
pulumi stack select dev  # or staging, prod

# 2. Import GCS state bucket (one-time per stack)
pulumi import gcp:storage/bucket:Bucket pulumi-state-bucket vici-app-pulumi-state-{env}

# 3. Provision everything
pulumi up

# 4. Verify
pulumi stack output
kubectl get pods -A
```

### Secret Inventory

These GCP Secret Manager secrets must be populated before `pulumi up`:

| Secret ID | Format | Source |
|-----------|--------|--------|
| `{env}-twilio-auth-token` | string | Twilio Console |
| `{env}-twilio-account-sid` | string | Twilio Console |
| `{env}-twilio-from-number` | string | Twilio Console |
| `{env}-openai-api-key` | string | OpenAI Dashboard |
| `{env}-pinecone-api-key` | string | Pinecone Console |
| `{env}-pinecone-index-host` | URL | Pinecone Console |
| `{env}-braintrust-api-key` | string | Braintrust Dashboard |
| `{env}-database-url` | `postgresql+asyncpg:///vici?host=/cloudsql/{connection_name}` | Derived from Cloud SQL |
| `{env}-temporal-address` | `temporal-frontend.temporal.svc.cluster.local:7233` | Static |
| `{env}-otel-exporter-otlp-endpoint` | `http://jaeger-collector.observability.svc.cluster.local:4317` | Static |
| `{env}-webhook-base-url` | `https://{app_hostname}` | Derived from DNS |
| `{env}-temporal-db-password` | string | Generated during Cloud SQL setup |

---

## Secret Rotation

### Rotating an Application Secret (e.g., Twilio, OpenAI)

1. Generate or obtain the new secret value from the provider's dashboard.
2. Update the GCP Secret Manager secret:
   ```bash
   echo -n "NEW_VALUE" | gcloud secrets versions add {env}-{secret-slug} --data-file=-
   ```
3. ESO automatically syncs within 1 hour (`refreshInterval: 1h`). To force immediate sync:
   ```bash
   kubectl annotate externalsecret {k8s-secret-name} -n {namespace} \
     force-sync=$(date +%s) --overwrite
   ```
4. Restart affected pods to pick up the new secret value:
   ```bash
   kubectl rollout restart deployment/vici-app -n vici
   ```

### Rotating Temporal DB Password

1. Update the Cloud SQL user password:
   ```bash
   gcloud sql users set-password temporal --instance=vici-temporal-{env} \
     --password=NEW_PASSWORD
   ```
2. Update GCP Secret Manager:
   ```bash
   echo -n "NEW_PASSWORD" | gcloud secrets versions add {env}-temporal-db-password --data-file=-
   ```
3. Force ESO sync:
   ```bash
   kubectl annotate externalsecret temporal-db-credentials -n temporal \
     force-sync=$(date +%s) --overwrite
   ```
4. Restart Temporal server pods:
   ```bash
   kubectl rollout restart deployment/temporal-frontend -n temporal
   kubectl rollout restart deployment/temporal-history -n temporal
   kubectl rollout restart deployment/temporal-matching -n temporal
   kubectl rollout restart deployment/temporal-worker -n temporal
   ```

### Verifying Secret Sync

```bash
# Check ExternalSecret status
kubectl get externalsecret -A

# All should show STATUS=SecretSynced, READY=True
# If READY=False, check ESO controller logs:
kubectl logs -n external-secrets -l app.kubernetes.io/name=external-secrets
```

---

## Cluster Upgrade

GKE Autopilot manages node versions automatically via the release channel. The cluster resource
uses:
- `REGULAR` channel for dev and staging
- `STABLE` channel for prod

### Pre-Upgrade Checklist

1. Verify PDBs are in place (staging/prod):
   ```bash
   kubectl get pdb -A
   # Should show vici-app, temporal-frontend, temporal-history with ALLOWED DISRUPTIONS >= 0
   ```
2. Verify current cluster version:
   ```bash
   gcloud container clusters describe vici-{env} \
     --region=us-central1 --format="value(currentMasterVersion)"
   ```
3. Check for deprecated API usage:
   ```bash
   kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis
   ```

### During Upgrade

GKE Autopilot handles node upgrades automatically. PDBs ensure at least 1 replica of critical
workloads remains available during node drain.

Monitor progress:
```bash
# Watch node versions
kubectl get nodes -o wide

# Watch pod disruptions
kubectl get events -A --field-selector reason=Evicted --sort-by='.lastTimestamp'
```

### Post-Upgrade Verification

```bash
# 1. All pods running
kubectl get pods -A | grep -v Running | grep -v Completed

# 2. Health check
curl -sf https://{app_hostname}/health

# 3. Temporal connectivity
kubectl exec -n vici deploy/vici-app -- \
  curl -sf temporal-frontend.temporal.svc.cluster.local:7233

# 4. Pulumi state matches
cd infra && pulumi preview --stack {env}
# Should show no changes
```

---

## Protected Resource Teardown

The following resources have `protect=True` in Pulumi:
- GKE cluster (`cluster.py`)
- Cloud SQL app instance (`database.py`)
- Cloud SQL Temporal instance (`database.py`)
- Artifact Registry (`registry.py`)
- GCS state bucket (`state_bucket.py`)

### To Tear Down a Protected Environment

This is intentionally friction-heavy. The protection exists to prevent accidental deletion.

1. **Edit each protected resource** — set `protect=False` in the `ResourceOptions`:
   ```python
   opts=ResourceOptions(protect=False, ...)
   ```

2. **Apply the protection removal:**
   ```bash
   pulumi up --stack {env}
   ```

3. **Now destroy is allowed:**
   ```bash
   pulumi destroy --stack {env}
   ```

4. **EXCEPTION: GCS state bucket** — Do NOT destroy the state bucket via `pulumi destroy`.
   The bucket IS the Pulumi backend. Destroying it mid-operation would corrupt state. Instead:
   - Remove the bucket from Pulumi state:
     ```bash
     pulumi state delete urn:...state-bucket...
     ```
   - Delete the bucket manually via `gsutil` after all Pulumi operations are complete:
     ```bash
     gsutil rm -r gs://vici-app-pulumi-state-{env}
     ```
