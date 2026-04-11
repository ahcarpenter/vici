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

from config import ENV, PROJECT_ID

state_bucket = gcp.storage.Bucket(
    "pulumi-state-bucket",
    name=f"vici-app-pulumi-state-{ENV}",
    project=PROJECT_ID,
    location="US",
    opts=ResourceOptions(
        protect=True,
        retain_on_delete=True,
    ),
)
