---
status: awaiting_human_verify
trigger: "pulumi-sdk-not-installed: ModuleNotFoundError: No module named 'pulumi' in CI deploy-dev"
created: 2026-04-06T00:00:00Z
updated: 2026-04-06T00:00:00Z
---

## Current Focus

hypothesis: CI runs `uv sync --frozen` but infra/ has no pyproject.toml or uv.lock — deps never install
test: Check for pyproject.toml and uv.lock in infra/
expecting: Files missing confirms hypothesis
next_action: Create pyproject.toml for infra/, generate uv.lock, update CI to create .venv Pulumi expects

## Symptoms

expected: `pulumi up` succeeds during deploy-dev CI step with Python SDK available
actual: Pulumi fails with `ModuleNotFoundError: No module named 'pulumi'`
errors: |
  pulumi:pulumi:Stack vici-infra-dev  Traceback (most recent call last):
      File "/usr/local/bin/pulumi-language-python-exec", line 17, in <module>
        import pulumi
    ModuleNotFoundError: No module named 'pulumi'
reproduction: Run deploy-dev step in GitHub Actions CI
started: Current CI run

## Eliminated

## Evidence

- timestamp: 2026-04-06T00:00:00Z
  checked: infra/ directory contents
  found: Only requirements.txt exists — no pyproject.toml or uv.lock
  implication: `uv sync --frozen` in cd-base.yml has nothing to sync; no deps installed

- timestamp: 2026-04-06T00:00:00Z
  checked: Pulumi.yaml runtime config
  found: virtualenv set to `.venv` — Pulumi expects deps in infra/.venv
  implication: CI must create .venv with pulumi packages for Pulumi to find them

- timestamp: 2026-04-06T00:00:00Z
  checked: cd-base.yml step "Install Pulumi dependencies"
  found: `cd infra && uv sync --frozen` — requires pyproject.toml + uv.lock
  implication: This is the direct cause — command is a no-op or error without project files

## Resolution

root_cause: The CI workflow (cd-base.yml) runs `uv sync --frozen` in the infra/ directory, but infra/ only has a requirements.txt — no pyproject.toml or uv.lock. The `uv sync` command requires these files to know what to install. Without them, no Python packages are installed, so Pulumi's Python runtime can't import the `pulumi` module.
fix: Created infra/pyproject.toml with pulumi deps matching requirements.txt, generated uv.lock via `uv lock`, added .venv/ to .gitignore. No CI workflow changes needed — existing `uv sync --frozen` now finds the project files.
verification: Local — `uv sync --frozen` creates .venv with pulumi importable. Awaiting CI run confirmation.
files_changed: [infra/pyproject.toml, infra/uv.lock, .gitignore]
