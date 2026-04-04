---
created: 2026-04-04T18:10:03.174Z
title: Replace changeme PULUMI_CONFIG_PASSPHRASE before pulumi up
area: general
files:
  - infra/Pulumi.dev.yaml
  - infra/Pulumi.staging.yaml
  - infra/Pulumi.prod.yaml
---

## Problem

During Phase 01 bootstrap, `PULUMI_CONFIG_PASSPHRASE="changeme"` was used to initialize the three Pulumi stacks (dev, staging, prod). This placeholder must be replaced with a strong passphrase before running `pulumi up` in any environment, otherwise secret encryption is weak.

## Solution

1. Choose a strong passphrase and store it securely (e.g. 1Password)
2. Re-initialize or update the stacks with the new passphrase:
   ```bash
   export PULUMI_CONFIG_PASSPHRASE="<real-passphrase>"
   ```
3. Add the passphrase as a GitHub Actions secret named `PULUMI_CONFIG_PASSPHRASE`
4. Update any local shell profiles (~/.zshrc) that may have `changeme` set
