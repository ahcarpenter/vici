---
phase: quick-260405-sqz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-CONTEXT.md
  - .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-01-PLAN.md
  - .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-02-PLAN.md
  - .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-RESEARCH.md
  - .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-DISCUSSION-LOG.md
autonomous: true
requirements: []

must_haves:
  truths:
    - "No planning artifact in Phase 5 references getvici.ai in any hostname, subdomain, or stub value"
    - "No planning artifact references nip.io as a fallback since real DNS is now available"
    - "All stub hostnames now read dev.usevici.com, staging.usevici.com, and usevici.com"
    - "ACME email contact in 05-02-PLAN.md reads ops@usevici.com"
    - "CONTEXT.md D-01 and D-02 are updated to reflect real DNS and usevici.com scheme"
    - "CONTEXT.md deferred section no longer mentions getvici.ai custom domain activation as future work"
  artifacts:
    - path: ".planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-CONTEXT.md"
      provides: "Updated context with usevici.com decisions"
    - path: ".planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-01-PLAN.md"
      provides: "Updated plan with usevici.com stack config values"
    - path: ".planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-02-PLAN.md"
      provides: "Updated plan with usevici.com ACME email and hostname"
    - path: ".planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-RESEARCH.md"
      provides: "Updated research with usevici.com throughout"
    - path: ".planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-DISCUSSION-LOG.md"
      provides: "Updated discussion log with usevici.com references"
  key_links: []
---

<objective>
Update all Phase 5 planning artifacts to replace the stub domain `getvici.ai` with the purchased domain `usevici.com`, and remove `nip.io` fallback references since real DNS is now available.

Purpose: The domain `usevici.com` was purchased on Squarespace. The `getvici.ai` stub and `nip.io` fallback patterns are no longer needed. Phase 5 plans and research should reflect the real domain from the start so that when execution begins, hostnames, ACME emails, and stack config values are correct.

Output: Five updated planning artifacts with all getvici.ai occurrences replaced by usevici.com equivalents and nip.io fallback language removed or updated.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/workstreams/gks-refactor/STATE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Update 05-CONTEXT.md and 05-DISCUSSION-LOG.md</name>
  <files>
    .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-CONTEXT.md
    .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-DISCUSSION-LOG.md
  </files>
  <action>
Read both files before editing. Apply the following replacements using the Edit tool with replace_all=true.

**05-CONTEXT.md changes:**

1. D-01 update — replace the decision text to reflect that real DNS is now available:
   - Old: `Use GKE auto-assigned IPs for v1 (no custom domain purchase required)`
   - New: `Use real DNS with purchased domain usevici.com (purchased on Squarespace)`

2. D-02 update — replace the stub domain scheme description:
   - Old: `Stub out a \`getvici.ai\` subdomain scheme in Pulumi stack configs (\`dev.getvici.ai\`, \`staging.getvici.ai\`, \`getvici.ai\`) so switching to custom domains later is a config change only`
   - New: `Use \`usevici.com\` subdomain scheme in Pulumi stack configs (\`dev.usevici.com\`, \`staging.usevici.com\`, \`usevici.com\`). Domain purchased on Squarespace; DNS configuration required before Phase 5 execution.`

3. Task 2 action stub values — replace all three hostname stubs:
   - Old: `vici-infra:app_hostname: dev.getvici.ai`
   - New: `vici-infra:app_hostname: dev.usevici.com`

   - Old: `vici-infra:app_hostname: staging.getvici.ai`
   - New: `vici-infra:app_hostname: staging.usevici.com`

   - Old: `vici-infra:app_hostname: getvici.ai`
   - New: `vici-infra:app_hostname: usevici.com`

4. Task 2 action note — remove the nip.io fallback note:
   - Old: `Note: The \`app_hostname\` values are the D-02 stubs. When using auto-assigned IPs (D-01), the operator will update \`app_hostname\` to \`<ip>.nip.io\` after the first \`pulumi up\` allocates a GKE Ingress IP. The getvici.ai values are the target state for when custom DNS is configured.`
   - New: `Note: The \`app_hostname\` values use the purchased usevici.com domain. DNS must be configured in Squarespace to point each subdomain to the GKE Ingress IP after the first \`pulumi up\` allocates it.`

5. Deferred section — update the custom domain activation line:
   - Old: `Custom domain activation (getvici.ai) — stubbed in config, activate when DNS is ready`
   - New: `Custom domain activation (usevici.com) — DNS configuration in Squarespace required before Phase 5 execution. Point dev.usevici.com, staging.usevici.com, and usevici.com to GKE Ingress IPs after first pulumi up.`

6. Specifics section — update the getvici.ai stub mention:
   - Old: `getvici.ai subdomain scheme stubbed in Pulumi stack configs as commented-out or defaulted values — ready to activate when DNS is configured`
   - New: `usevici.com subdomain scheme in Pulumi stack configs — DNS must be configured in Squarespace pointing subdomains to GKE Ingress IPs after first pulumi up`

**05-DISCUSSION-LOG.md changes:**

1. User's choice in Hostname section:
   - Old: `User wants the cheapest path for v1 but with the getvici.ai domain pre-configured so switching is a config change.`
   - New: `User purchased usevici.com on Squarespace. Domain is now real; DNS configuration in Squarespace required before Phase 5 execution.`

2. Discussion table row (the stub option row) — update the description of selected option:
   - Old: `Use auto-assigned IPs, but stub out a getvici.ai subdomain scheme in config for future activation.`
   - New: `Use purchased domain usevici.com with subdomains per env. DNS configuration in Squarespace required.`

3. Deferred section — update getvici.ai mention:
   - Old: `Custom domain activation (getvici.ai) — stubbed, activate when DNS ready`
   - New: `Custom domain DNS configuration (usevici.com) — purchased on Squarespace, configure DNS to point to GKE Ingress IPs after first pulumi up`
  </action>
  <verify>
    <automated>grep -r "getvici\.ai" /Users/ahcarpenter/workspace/vici/.planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-CONTEXT.md /Users/ahcarpenter/workspace/vici/.planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-DISCUSSION-LOG.md && echo "FAIL: getvici.ai still present" || echo "PASS: no getvici.ai references"</automated>
  </verify>
  <done>
    05-CONTEXT.md and 05-DISCUSSION-LOG.md contain no getvici.ai references. Hostname stubs read dev.usevici.com, staging.usevici.com, usevici.com. nip.io fallback language replaced with Squarespace DNS instructions.
  </done>
</task>

<task type="auto">
  <name>Task 2: Update 05-01-PLAN.md</name>
  <files>
    .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-01-PLAN.md
  </files>
  <action>
Read the file before editing. Apply the following replacements using the Edit tool with replace_all=true where the same string appears multiple times.

**Hostname stub values in Task 2 action block (3 occurrences):**
- Old: `vici-infra:app_hostname: dev.getvici.ai`
- New: `vici-infra:app_hostname: dev.usevici.com`

- Old: `vici-infra:app_hostname: staging.getvici.ai`
- New: `vici-infra:app_hostname: staging.usevici.com`

- Old: `vici-infra:app_hostname: getvici.ai`
- New: `vici-infra:app_hostname: usevici.com`

**Acceptance criteria lines (3 occurrences matching the above):**
- Old: `infra/Pulumi.dev.yaml contains \`vici-infra:app_hostname: dev.getvici.ai\``
- New: `infra/Pulumi.dev.yaml contains \`vici-infra:app_hostname: dev.usevici.com\``

- Old: `infra/Pulumi.staging.yaml contains \`vici-infra:app_hostname: staging.getvici.ai\``
- New: `infra/Pulumi.staging.yaml contains \`vici-infra:app_hostname: staging.usevici.com\``

- Old: `infra/Pulumi.prod.yaml contains \`vici-infra:app_hostname: getvici.ai\``
- New: `infra/Pulumi.prod.yaml contains \`vici-infra:app_hostname: usevici.com\``

**Remove the nip.io fallback note in Task 2 action (1 occurrence):**
- Old: `Note: The \`app_hostname\` values are the D-02 stubs. When using auto-assigned IPs (D-01), the operator will update \`app_hostname\` to \`<ip>.nip.io\` after the first \`pulumi up\` allocates a GKE Ingress IP. The getvici.ai values are the target state for when custom DNS is configured.`
- New: `Note: The \`app_hostname\` values use the purchased usevici.com domain. DNS must be configured in Squarespace to point each subdomain to the GKE Ingress IP after the first \`pulumi up\` allocates it.`

**Per D-02 reference in Task 2 action:**
- Old: `Per D-02 (stub getvici.ai subdomains) and D-01 (auto-assigned IPs for v1), add config keys`
- New: `Per D-02 (usevici.com subdomain scheme) and D-01 (real purchased domain), add config keys`

**Interface comment in context block (1 occurrence):**
- Old: `APP_HOSTNAME: str = cfg.require("app_hostname")  # e.g., "dev.getvici.ai"`
- New: `APP_HOSTNAME: str = cfg.require("app_hostname")  # e.g., "dev.usevici.com"`
  </action>
  <verify>
    <automated>grep -r "getvici\.ai\|nip\.io" /Users/ahcarpenter/workspace/vici/.planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-01-PLAN.md && echo "FAIL: old domain still present" || echo "PASS: no old domain references"</automated>
  </verify>
  <done>
    05-01-PLAN.md contains no getvici.ai or nip.io references. Stack config action and acceptance criteria all use usevici.com subdomains. nip.io fallback note replaced with Squarespace DNS instructions.
  </done>
</task>

<task type="auto">
  <name>Task 3: Update 05-02-PLAN.md and 05-RESEARCH.md</name>
  <files>
    .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-02-PLAN.md
    .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-RESEARCH.md
  </files>
  <action>
Read both files before editing. Apply the following replacements using the Edit tool.

**05-02-PLAN.md changes:**

1. ACME email constant (appears twice — staging Issuer and prod Issuer code blocks):
   - Old: `_ACME_EMAIL = "ops@getvici.ai"`
   - New: `_ACME_EMAIL = "ops@usevici.com"`
   Use replace_all=true since both occurrences should change.

2. nip.io reference in Task 2 action note (WEBHOOK_BASE_URL SecretVersion section):
   - Old: `When the operator updates \`app_hostname\` to the actual IP-based hostname (e.g., \`<ip>.nip.io\` per D-01), re-running \`pulumi up\` will update this secret version automatically.`
   - New: `When the operator updates DNS in Squarespace to point app_hostname to the GKE Ingress IP, re-running \`pulumi up\` will update this secret version automatically.`

3. Interface comment:
   - Old: `APP_HOSTNAME: str = cfg.require("app_hostname")  # e.g., "dev.getvici.ai"`
   - New: `APP_HOSTNAME: str = cfg.require("app_hostname")  # e.g., "dev.usevici.com"`

**05-RESEARCH.md changes (read file in sections if needed — it is large):**

Apply all of the following replacements using replace_all=true:

1. D-02 locked decision description (user_constraints section):
   - Old: `D-02: Stub out a \`getvici.ai\` subdomain scheme in Pulumi stack configs (\`dev.getvici.ai\`, \`staging.getvici.ai\`, \`getvici.ai\`) so switching to custom domains later is a config change only`
   - New: `D-02: Use \`usevici.com\` subdomain scheme in Pulumi stack configs (\`dev.usevici.com\`, \`staging.usevici.com\`, \`usevici.com\`). Domain purchased on Squarespace.`

2. Deferred ideas in user_constraints:
   - Old: `Custom domain activation (getvici.ai) — stubbed in config, activate when DNS is ready`
   - New: `Custom domain DNS configuration (usevici.com) — purchased on Squarespace, configure DNS to point subdomains to GKE Ingress IPs after first pulumi up`

3. ACME email in code sample (appears twice — staging and prod Issuer):
   - Old: `"email": "ops@getvici.ai",`
   - New: `"email": "ops@usevici.com",`
   Use replace_all=true.

4. Stack config example with nip.io fallback comment:
   - Old: `vici-infra:app_hostname: dev.getvici.ai      # Or <ip>.nip.io for v1`
   - New: `vici-infra:app_hostname: dev.usevici.com`

5. Assumption row A2 about nip.io in the assumptions table:
   - Old: `| A2 | \`nip.io\` is a viable v1 hostname for Let's Encrypt TLS with auto-assigned GKE IP | Pitfall 6 | If nip.io rate-limits or is blocked by Let's Encrypt, TLS won't work with auto-assigned IPs until real DNS is configured |`
   - New: `| A2 | \`usevici.com\` DNS is configured in Squarespace to point to GKE Ingress IPs | - | DNS must be configured after first \`pulumi up\` allocates the Ingress IP |`

6. Open question about v1 TLS hostname (already resolved, update to reflect real DNS):
   - Old: `1. **\`app_hostname\` value for v1 TLS** — RESOLVED: Plan 01 Task 2 stubs \`getvici.ai\` subdomains per D-02. For v1 with auto-assigned IPs (D-01), operator updates \`app_hostname\` to \`<ip>.nip.io\` after first \`pulumi up\` and re-runs. The \`gcp.secretmanager.SecretVersion\` for \`WEBHOOK_BASE_URL\` in Plan 02 uses \`APP_HOSTNAME\`, so re-running \`pulumi up\` after updating the hostname automatically updates the secret value.`
   - New: `1. **\`app_hostname\` value for TLS** — RESOLVED: Plan 01 Task 2 sets \`usevici.com\` subdomains per D-02. After first \`pulumi up\` allocates the GKE Ingress IP, operator configures DNS in Squarespace (dev.usevici.com → IP, staging.usevici.com → IP, usevici.com → IP). The \`gcp.secretmanager.SecretVersion\` for \`WEBHOOK_BASE_URL\` in Plan 02 uses \`APP_HOSTNAME\`, so re-running \`pulumi up\` after DNS propagates requires no code changes.`

7. Confidence note about nip.io at the end of the file:
   - Old: `- \`nip.io\` as interim hostname for Let's Encrypt with auto-assigned IPs — based on common community practice, not officially documented by cert-manager or GKE`
   - New: `- \`usevici.com\` DNS records configured in Squarespace — standard A record configuration pointing subdomains to GKE Ingress IPs`
  </action>
  <verify>
    <automated>grep -r "getvici\.ai\|nip\.io" /Users/ahcarpenter/workspace/vici/.planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-02-PLAN.md /Users/ahcarpenter/workspace/vici/.planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-RESEARCH.md && echo "FAIL: old domain still present" || echo "PASS: no old domain references"</automated>
  </verify>
  <done>
    05-02-PLAN.md and 05-RESEARCH.md contain no getvici.ai or nip.io references. ACME email reads ops@usevici.com. All hostname examples, stack config stubs, assumption rows, and open questions reflect usevici.com with Squarespace DNS instructions.
  </done>
</task>

</tasks>

<verification>
Run across all five files to confirm no old domain references remain:

```bash
grep -r "getvici\.ai\|nip\.io" \
  .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-CONTEXT.md \
  .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-01-PLAN.md \
  .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-02-PLAN.md \
  .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-RESEARCH.md \
  .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-DISCUSSION-LOG.md \
  && echo "FAIL" || echo "PASS"
```

Expected: PASS (no matches).

Spot-check correct replacements:
```bash
grep "usevici\.com" \
  .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-01-PLAN.md
# Should show: dev.usevici.com, staging.usevici.com, usevici.com entries

grep "_ACME_EMAIL" \
  .planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-02-PLAN.md
# Should show: ops@usevici.com
```
</verification>

<success_criteria>
- Zero occurrences of `getvici.ai` across all five Phase 5 planning artifacts
- Zero occurrences of `nip.io` across all five Phase 5 planning artifacts
- Hostname stubs read `dev.usevici.com`, `staging.usevici.com`, `usevici.com`
- ACME contact email in 05-02-PLAN.md reads `ops@usevici.com`
- nip.io fallback language replaced with Squarespace DNS configuration instructions
- D-01 and D-02 in CONTEXT.md reflect real purchased domain, not stubs
</success_criteria>

<output>
After completion, create `.planning/quick/260405-sqz-update-domain-references-from-getvici-ai/260405-sqz-SUMMARY.md`
</output>
