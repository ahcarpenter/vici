---
status: awaiting_human_verify
trigger: "pulumi-gcp-provider-panic: GCP provider v9.18.0 panics with __pulumi_raw_state_delta error on sm-twilio-auth-token"
created: 2026-04-06T00:00:00Z
updated: 2026-04-06T00:00:00Z
---

## Current Focus

hypothesis: __pulumi_raw_state_delta stored in state file causes provider panic even during refresh (Read method panics before reconciliation can occur); must strip deltas from state before invoking provider
test: added pre-step in cd-base.yml that runs `pulumi stack export`, strips `__pulumi_raw_state_delta` from all resource outputs via Python, then `pulumi stack import`s the cleaned state — all state-only ops, no provider invoked
expecting: cleaned state allows provider Read to succeed; refresh + up proceed normally
next_action: awaiting CI run verification

## Symptoms

expected: `pulumi up` succeeds in CI deploy-dev workflow
actual: GCP provider v9.18.0 panics with state corruption error on sm-twilio-auth-token
errors: |
  gcp:secretmanager:Secret sm-twilio-auth-token error: Bridged provider panic (provider=gcp v=9.18.0 resourceURN=...): fatal: error An assertion has failed: Failed to recover raw state. source error: Data integrity error: "__pulumi_raw_state_delta" does not apply cleanly to the resource state
  pulumi:pulumi:Stack vici-infra-dev running error: Detected that pulumi-resource-gcp exited prematurely.
  Also: failed to get regions list: failed to list regions: googleapi: Error 403: Required 'compute.regions.list' permission
reproduction: Push to main, observe CD Dev workflow
started: After fixing ModuleNotFoundError in prior debug session

## Eliminated

- hypothesis: refresh: true reconciles state before update
  reason: provider panics in Read method during refresh itself; 3 secrets fail with __pulumi_raw_state_delta assertion, then provider process crashes causing all remaining resources to fail with EOF/connection refused

## Evidence

- timestamp: 2026-04-06
  checked: infra/uv.lock for pinned pulumi-gcp version
  found: pulumi-gcp==9.18.0 locked
  implication: confirms the version in the error message matches what CI installs

- timestamp: 2026-04-06
  checked: pulumi-terraform-bridge issues (#1667, #3225) for __pulumi_raw_state_delta bugs
  found: known class of bugs where bridged provider state deltas fail to apply when internal state representation diverges from cloud reality (schema-aware transformations distort RawState)
  implication: root cause is stale/corrupted state in Pulumi's state file; the stored delta no longer matches the actual cloud resource

- timestamp: 2026-04-06
  checked: pulumi/actions@v6 documentation for refresh support
  found: v6 supports `refresh: true` input which passes --refresh flag to pulumi up/preview, causing state to be reconciled with cloud before the update
  implication: adding refresh: true to cd-base.yml will fix the state mismatch automatically in CI

- timestamp: 2026-04-06
  checked: infra/components/secrets.py for sm-twilio-auth-token resource
  found: resource created in loop over _SECRET_DEFINITIONS, first entry is ("twilio-auth-token", "vici", "twilio-auth-token"), resource name is f"sm-{_slug}" = "sm-twilio-auth-token"
  implication: the failing resource is a standard gcp.secretmanager.Secret; nothing unusual about the resource definition itself

## Resolution

root_cause: Pulumi's stored state for gcp:secretmanager:Secret sm-twilio-auth-token has a __pulumi_raw_state_delta that no longer applies cleanly to the resource state. This is a known class of pulumi-terraform-bridge bugs where the internal state representation diverges from cloud reality, causing the GCP provider to panic when trying to recover raw state during `pulumi up`.
fix: Added `refresh: true` to the pulumi/actions@v6 step in .github/workflows/cd-base.yml. This causes `pulumi up` to run with the --refresh flag, which re-reads actual cloud state and reconciles the stored state before applying changes — fixing the delta mismatch automatically without manual `pulumi state` commands.
verification: awaiting CI run
files_changed: [".github/workflows/cd-base.yml"]
