# Quick Task 260405-wjc: Fix Pulumi Pending Operations & Temporal DNS

## Summary

Fixed three cascading infrastructure issues preventing vici-app from running on GKE:

1. **Temporal DNS mismatch** — Helm chart auto-generated service names with hash prefix (`temporal-5b5cac0f-frontend`) but GCP secret expected `temporal-frontend`. Fixed by adding `fullnameOverride: "temporal"` to Helm values.

2. **WorkflowAlreadyStartedError crash** — `start_cron_if_needed` caught both `WorkflowAlreadyStartedError` and `RPCError` in same except clause, then accessed `.status` which doesn't exist on `WorkflowAlreadyStartedError`. Fixed by splitting into separate except clauses.

3. **Pulumi pending operations** — 5 stuck "creating" operations blocked all deployments. Resolved by exporting state, removing pending ops, and re-importing.

## Additional fixes applied during deploy

- `temporal-host` → `temporal-address` in secrets.py and app.py (name mismatch)
- `imagePullPolicy: Always` added to vici-app container (mutable `dev` tag)
- cert-manager `leaderElection.namespace` added to fix Helm install
- Temporal `default` namespace registered via admintools

## Result

- vici-app pod: **2/2 Ready, 0 restarts**
- ClusterIP Service: created (`34.118.238.211`)
- GKE Ingress: created, load balancer IP `34.120.195.235`
- Health check: `curl http://34.120.195.235/health` → `{"status":"ok"}`

## Commits

| Hash | Description |
|------|-------------|
| 9610ec2 | Add fullnameOverride to Temporal Helm release |
| 755b0dc | Fix WorkflowAlreadyStartedError exception handling |
| d0a29ab | Fix infra: temporal-host→temporal-address, imagePullPolicy, cert-manager |
