---
status: investigating
trigger: "Ensure pulumi up works when run locally"
created: 2026-04-09T20:00:00Z
updated: 2026-04-09T20:00:00Z
---

## Current Focus

hypothesis: CONFIRMED -- PULUMI_CONFIG_PASSPHRASE env var doesn't match the passphrase used to encrypt Pulumi.dev.yaml secrets in commit d0612c1. Both state and YAML share the same salt but the current env var passphrase can't decrypt it.
test: Strip encrypted secrets and salt from Pulumi.dev.yaml, re-set secrets with current passphrase
expecting: New salt and ciphertexts matching current passphrase; pulumi preview succeeds
next_action: Re-encrypt stack config with current passphrase using known plaintext values (user=vici, password=need from user or state)

## Symptoms

expected: `pulumi up` completes successfully with no errors
actual: Unknown -- need to run it and observe
errors: Unknown -- need to discover
reproduction: Run `pulumi up` in the infrastructure directory
started: Unknown

## Eliminated

## Evidence

- timestamp: 2026-04-09T20:00:00Z
  checked: Environment setup
  found: Pulumi v3.229.0 installed, PULUMI_CONFIG_PASSPHRASE set, GCS backend accessible (gs://vici-app-pulumi-state-dev), dev stack has 93 resources, GCP auth active (drewwcarpenter@gmail.com)
  implication: Basic prerequisites are met; can proceed to preview

## Resolution

root_cause:
fix:
verification:
files_changed: []
