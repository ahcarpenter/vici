# Plan 01-01 Summary — Pulumi Project Bootstrap

## Status: Complete

## Files Created
- `infra/Pulumi.yaml` — Project definition with GCS backend default (dev)
- `infra/Pulumi.dev.yaml` — Dev stack config
- `infra/Pulumi.staging.yaml` — Staging stack config
- `infra/Pulumi.prod.yaml` — Prod stack config
- `infra/requirements.txt` — Pinned Pulumi Python dependencies
- `infra/config.py` — Typed config constants
- `infra/components/__init__.py` — Components package marker
- `infra/__main__.py` — Entry point stub
- `infra/.gitignore` — Excludes .venv/

## GCP Projects
| Environment | Project ID |
|-------------|-----------|
| dev | `vici-app-dev` |
| staging | `vici-app-staging` |
| prod | `vici-app-prod` |

## GCS State Buckets
| Environment | Bucket |
|-------------|--------|
| dev | `gs://vici-app-pulumi-state-dev` |
| staging | `gs://vici-app-pulumi-state-staging` |
| prod | `gs://vici-app-pulumi-state-prod` |

All buckets: us-central1, uniform access, versioning enabled.

## Pulumi Stacks
All three stacks (dev, staging, prod) initialized against their respective GCS backends.

## PULUMI_CONFIG_PASSPHRASE
Currently set to `"changeme"` — must be replaced with a strong passphrase before running `pulumi up`. Store the real value as GitHub Actions secret `PULUMI_CONFIG_PASSPHRASE`.

## Deviations
- Bucket names use `vici-app-pulumi-state-{env}` instead of `vici-pulumi-state-{env}` — original names were globally reserved by prior deletions.
- Python venv created at `infra/.venv/` (gitignored) for local dependency isolation.
