---
phase: quick-260405-wai
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - infra/components/ingress.py
  - infra/DOMAIN-SETUP.md
autonomous: true
must_haves:
  truths:
    - "pulumi stack output ingress_external_ip returns the GKE-provisioned IP once ingress is healthy"
    - "DOMAIN-SETUP.md documents the exact Squarespace DNS A record configuration"
  artifacts:
    - path: "infra/components/ingress.py"
      provides: "ingress_external_ip export"
      contains: "pulumi.export.*ingress_external_ip"
    - path: "infra/DOMAIN-SETUP.md"
      provides: "Domain association runbook"
---

<objective>
Add a Pulumi stack export for the ingress external IP and create a domain setup runbook.

Purpose: Once the GKE Ingress comes online (after pending operations are resolved separately), the external IP must be easily retrievable via `pulumi stack output` for Squarespace DNS configuration. A runbook documents the exact steps.

Output: Modified ingress.py with IP export, new DOMAIN-SETUP.md in infra/.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@infra/components/ingress.py
@infra/config.py
@infra/__main__.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add ingress external IP Pulumi export</name>
  <files>infra/components/ingress.py</files>
  <action>
At the bottom of infra/components/ingress.py, in the Exports section (after the existing `ingress_name` and `webhook_base_url` exports), add a new export that surfaces the ingress external IP address:

```python
pulumi.export(
    "ingress_external_ip",
    vici_ingress.status.apply(
        lambda s: (s.load_balancer.ingress[0].ip if s and s.load_balancer and s.load_balancer.ingress else "PENDING")
    ),
)
```

This extracts the IP from the Ingress status.loadBalancer.ingress[0].ip field, which GKE populates once the external load balancer is provisioned. Returns "PENDING" if not yet assigned.

Also add an `app_hostname` export so the domain is surfaced alongside the IP:

```python
pulumi.export("app_hostname", APP_HOSTNAME)
```

Do NOT modify any existing exports or resource definitions. Only append new exports.
  </action>
  <verify>
    <automated>cd /Users/ahcarpenter/workspace/vici/infra && python -c "import ast; tree = ast.parse(open('components/ingress.py').read()); exports = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and hasattr(n.func, 'attr') and n.func.attr == 'export']; names = [n.args[0].value for n in exports if n.args and isinstance(n.args[0], ast.Constant)]; assert 'ingress_external_ip' in names, f'Missing ingress_external_ip export, found: {names}'; assert 'app_hostname' in names, f'Missing app_hostname export'; print('OK: exports verified')"</automated>
  </verify>
  <done>ingress.py exports ingress_external_ip (from load balancer status) and app_hostname. Existing exports unchanged.</done>
</task>

<task type="auto">
  <name>Task 2: Create DOMAIN-SETUP.md runbook</name>
  <files>infra/DOMAIN-SETUP.md</files>
  <action>
Create infra/DOMAIN-SETUP.md with the following content documenting the exact steps to associate the Squarespace domain with the GKE deployment:

Sections to include:

1. **Prerequisites** — Pulumi stack is up, ingress is healthy (not in pending state), cert-manager issuers deployed.

2. **Retrieve the Ingress IP** — Run `pulumi stack output ingress_external_ip` from the `infra/` directory. If it returns "PENDING", the ingress is not yet provisioned (check `kubectl get ingress vici-ingress -n vici` for status). Also show `pulumi stack output app_hostname` to confirm the target hostname.

3. **Configure Squarespace DNS** — Step-by-step:
   - Navigate to Squarespace Domains > usevici.com > DNS Settings > Custom Records
   - Add an A record: Host = `dev`, Type = `A`, Data = the IP from step 2, TTL = 300 (5 min, lower for initial propagation; increase to 3600 once stable)
   - If configuring the apex domain (usevici.com for prod), add the A record with Host = `@`
   - Note: Squarespace does not support CNAME at the apex; A records are required

4. **Verify DNS Propagation** — Commands to verify:
   - `dig dev.usevici.com +short` should return the ingress IP
   - `nslookup dev.usevici.com` as an alternative
   - `curl -I https://dev.usevici.com` should return a response (may be 502 initially until app pods are healthy)
   - Propagation typically takes 5-30 minutes

5. **TLS Certificate** — The ingress is annotated with `cert-manager.io/issuer: letsencrypt-staging` by default. After verifying the staging cert works (browser will show untrusted cert warning):
   - Update the annotation in ingress.py to `letsencrypt-prod`
   - Run `pulumi up` to apply
   - Delete the old staging cert: `kubectl delete certificate vici-tls -n vici` (cert-manager will re-issue with prod)
   - Verify: `kubectl get certificate -n vici` shows READY=True

6. **Troubleshooting** — Common issues:
   - Ingress IP shows PENDING: backend service or pods not ready
   - 502 errors: app pods crashing, check `kubectl logs -n vici -l app=vici-app`
   - Certificate not issued: check `kubectl describe certificate vici-tls -n vici` and `kubectl get challenges -n vici`
   - DNS not resolving: TTL cache, wait or flush local DNS cache

Use plain markdown, no emojis. Reference actual Pulumi config values (APP_HOSTNAME from Pulumi.dev.yaml).
  </action>
  <verify>
    <automated>test -f /Users/ahcarpenter/workspace/vici/infra/DOMAIN-SETUP.md && grep -q "pulumi stack output ingress_external_ip" /Users/ahcarpenter/workspace/vici/infra/DOMAIN-SETUP.md && grep -q "Squarespace" /Users/ahcarpenter/workspace/vici/infra/DOMAIN-SETUP.md && grep -q "letsencrypt-prod" /Users/ahcarpenter/workspace/vici/infra/DOMAIN-SETUP.md && echo "OK: DOMAIN-SETUP.md verified"</automated>
  </verify>
  <done>DOMAIN-SETUP.md exists in infra/ with complete step-by-step instructions covering IP retrieval, Squarespace DNS A record configuration, DNS propagation verification, and TLS certificate promotion from staging to prod.</done>
</task>

</tasks>

<verification>
1. `python -c "..."` AST check confirms ingress_external_ip export exists
2. DOMAIN-SETUP.md contains all required sections (IP retrieval, Squarespace config, DNS verification, TLS promotion)
3. No existing ingress.py resources or exports were modified
</verification>

<success_criteria>
- `pulumi stack output ingress_external_ip` will return the load balancer IP once ingress is provisioned (or "PENDING" if not yet ready)
- `pulumi stack output app_hostname` returns the configured hostname
- DOMAIN-SETUP.md provides a complete, actionable runbook for Squarespace DNS configuration
</success_criteria>

<output>
After completion, create `.planning/quick/260405-wai-double-check-that-the-ingress-was-create/260405-wai-SUMMARY.md`
</output>
