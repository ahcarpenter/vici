import pulumi

cfg = pulumi.Config()
gcp_cfg = pulumi.Config("gcp")

# "dev" | "staging" | "prod"
ENV: str = cfg.require("env")

# "vici-dev" | "vici-staging" | "vici-prod"
CLUSTER_NAME: str = cfg.require("cluster_name")

REGISTRY_NAME: str = cfg.require("registry_name")
PROJECT_ID: str = gcp_cfg.require("project")
REGION: str = gcp_cfg.get("region") or "us-central1"

# "dev.usevici.com" | "staging.usevici.com" | "usevici.com"
APP_HOSTNAME: str = cfg.require("app_hostname")

# GitHub organization or user owning the repo.
GITHUB_ORG: str = cfg.require("github_org")

# CI passes --config vici-infra:imageTag=<sha>; local fallback to ENV.
IMAGE_TAG: str = cfg.get("imageTag") or ENV
