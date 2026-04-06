---
phase: quick
plan: 260405-wjc
type: execute
wave: 1
depends_on: []
files_modified:
  - infra/components/temporal.py
autonomous: false
must_haves:
  truths:
    - "Temporal Helm services are named temporal-frontend, temporal-history, etc. matching the DNS in dev-temporal-address secret"
    - "vici-app Deployment can resolve temporal-frontend.temporal.svc.cluster.local:7233"
    - "Pulumi pending operations are cleared and stack is consistent"
  artifacts:
    - path: "infra/components/temporal.py"
      provides: "fullnameOverride in Helm values"
      contains: "fullnameOverride"
  key_links:
    - from: "infra/components/temporal.py"
      to: "Temporal Helm chart service names"
      via: "fullnameOverride value"
      pattern: "fullnameOverride.*temporal"
---

<objective>
Fix Temporal DNS address mismatch that prevents vici-app from connecting to the Temporal frontend service.

Purpose: The Temporal Helm chart auto-generates service names with a release hash prefix (e.g., `temporal-5b5cac0f-frontend`), but the GCP secret `dev-temporal-address` and the Pulumi export both reference `temporal-frontend.temporal.svc.cluster.local:7233`. Adding `fullnameOverride: "temporal"` forces the chart to use `temporal-frontend`, `temporal-history`, etc. -- matching the expected DNS names. After the code fix, the user must manually clear 5 stuck pending operations and run `pulumi up` to apply.

Output: Updated `infra/components/temporal.py` with fullnameOverride, plus runbook for manual infra operations.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@infra/components/temporal.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add fullnameOverride to Temporal Helm values</name>
  <files>infra/components/temporal.py</files>
  <action>
In `infra/components/temporal.py`, add `"fullnameOverride": "temporal"` to the top level of the `values` dict in the `temporal_release` Helm Release (line 129). Place it as the FIRST key in the values dict, before the `"cassandra"` key.

This single addition forces the Temporal Helm chart to generate service names as `temporal-frontend`, `temporal-history`, `temporal-matching`, and `temporal-worker` -- matching the DNS address already stored in the GCP secret `dev-temporal-address` (`temporal-frontend.temporal.svc.cluster.local:7233`).

Do NOT modify the `pulumi.export("temporal_frontend_service", ...)` line -- it already uses the correct name.

Add a comment above the key: `# Override chart release-hash prefix so services are named temporal-{component}`
  </action>
  <verify>
    <automated>cd /Users/ahcarpenter/workspace/vici && grep -n 'fullnameOverride' infra/components/temporal.py | grep -q 'temporal' && echo "PASS: fullnameOverride present" || echo "FAIL: fullnameOverride missing"</automated>
  </verify>
  <done>infra/components/temporal.py contains `"fullnameOverride": "temporal"` in the Helm values dict. No other files changed.</done>
</task>

<task type="checkpoint:human-action" gate="blocking">
  <name>Task 2: Clear pending operations and apply Pulumi changes</name>
  <what-built>The code change in Task 1 adds fullnameOverride to the Temporal Helm chart, which will rename all Temporal services to match the expected DNS names.</what-built>
  <how-to-verify>
Run the following commands manually from the infra directory:

1. Clear stuck pending operations:
   ```
   cd infra && pulumi cancel
   ```
   This removes the 5 stuck "creating" operations (vici-app Deployment x2, alembic-migration Job, jaeger-collector Deployment, jaeger-query Deployment).

2. Preview the changes to confirm fullnameOverride is picked up:
   ```
   pulumi preview
   ```
   Expect to see the Temporal Helm release being updated (services renamed from `temporal-5b5cac0f-*` to `temporal-*`).

3. Apply the changes:
   ```
   pulumi up
   ```
   This will:
   - Recreate Temporal services with correct names (temporal-frontend, temporal-history, etc.)
   - Unblock the vici-app Deployment (DNS now resolves)
   - Allow the Service and Ingress resources to be created

4. Verify DNS resolution from within the cluster:
   ```
   kubectl run -n default dns-test --image=busybox:1.36 --rm -it --restart=Never -- nslookup temporal-frontend.temporal.svc.cluster.local
   ```
   Should resolve to a cluster IP.

5. Verify vici-app pod is running:
   ```
   kubectl get pods -n default -l app=vici-app
   ```
   Pods should be in Running state (not CrashLoopBackOff).
  </how-to-verify>
  <resume-signal>Type "done" after pulumi up succeeds and vici-app pods are running</resume-signal>
</task>

</tasks>

<verification>
- `infra/components/temporal.py` contains `fullnameOverride` set to `"temporal"`
- After manual pulumi up: `kubectl get svc -n temporal` shows `temporal-frontend`, `temporal-history`, `temporal-matching`, `temporal-worker`
- After manual pulumi up: vici-app pods are Running, not CrashLoopBackOff
</verification>

<success_criteria>
- Code change committed: fullnameOverride added to temporal.py
- User has run pulumi cancel + pulumi up successfully
- Temporal services use correct DNS names matching dev-temporal-address secret
- vici-app can connect to Temporal and pods are healthy
</success_criteria>

<output>
After completion, create `.planning/quick/260405-wjc-fix-pulumi-pending-operations-and-resolv/260405-wjc-SUMMARY.md`
</output>
