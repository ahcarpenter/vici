"""GCS state bucket imported as a Pulumi-managed resource for protect=True.

The bucket is the Pulumi backend itself. It was NOT originally created by Pulumi.
To manage it, run the import command once per stack:

    pulumi import gcp:storage/bucket:Bucket pulumi-state-bucket vici-app-pulumi-state-{env}

After import, this module ensures protect=True and retain_on_delete=True so:
  - `pulumi destroy` will refuse to delete the bucket
  - Even if protection is removed, the bucket is retained (not deleted)

WARNING: Never run `pulumi destroy` on a stack whose state bucket is managed
by the program itself — it would destroy the state file mid-operation.
"""

import pulumi_gcp as gcp
from pulumi import ResourceOptions

from config import ENV, PROJECT_ID, REGION

# Use the actual bucket region — GCS normalizes "US" to the bucket's real
# multi-region/regional location. After import, Pulumi sees the actual
# location (e.g. "US-CENTRAL1"), so we must match to avoid a replace diff.
_BUCKET_LOCATION_BY_ENV: dict[str, str] = {
    "dev": REGION.upper(),       # matches actual bucket location
    "staging": REGION.upper(),
    "prod": "US",                # prod uses multi-region for durability
}

state_bucket = gcp.storage.Bucket(
    "pulumi-state-bucket",
    name=f"vici-app-pulumi-state-{ENV}",
    project=PROJECT_ID,
    location=_BUCKET_LOCATION_BY_ENV.get(ENV, "US"),
    uniform_bucket_level_access=True,
    versioning=gcp.storage.BucketVersioningArgs(enabled=True),
    opts=ResourceOptions(
        protect=True,
        retain_on_delete=True,
        ignore_changes=["location"],
    ),
)
