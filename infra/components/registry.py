import pulumi
import pulumi_gcp as gcp
from pulumi import ResourceOptions

from components.identity import ci_push_sa
from config import PROJECT_ID, REGION, REGISTRY_NAME

# Artifact Registry Docker repository for Vici application images.
# Repository ID becomes part of the push URI:
# us-central1-docker.pkg.dev/<project>/<registry_name>/<image>:<tag>
registry = gcp.artifactregistry.Repository(
    "vici-registry",
    project=PROJECT_ID,
    location=REGION,
    repository_id=REGISTRY_NAME,
    format="DOCKER",
    description="Vici application Docker images",
    opts=ResourceOptions(protect=True),
)

# Grant the CI service account push (writer) access to this repository.
# The CI SA is created in components/identity.py; bound here alongside
# the registry resource it applies to.
registry_push_iam = gcp.artifactregistry.RepositoryIamMember(
    "ci-push-iam",
    project=PROJECT_ID,
    location=REGION,
    repository=registry.repository_id,
    role="roles/artifactregistry.writer",
    member=ci_push_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)

# Full Docker push URI — exported for use in CI pipeline configuration.
# Format: us-central1-docker.pkg.dev/<project>/<repo>
registry_url = pulumi.Output.concat(
    "us-central1-docker.pkg.dev/",
    PROJECT_ID,
    "/",
    registry.repository_id,
)

pulumi.export("registry_url", registry_url)
