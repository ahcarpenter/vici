import os

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

# IN-06: fail loud when running in CI without an explicit imageTag.
# The `cfg.get("imageTag") or ENV` fallback below is a local-dev
# convenience so `pulumi up` works without `--config vici-infra:imageTag=<sha>`.
# In CI that fallback can mask a broken config-map passthrough: the
# deploy would silently roll out `<registry>/vici:dev`, which may or
# may not exist, far from the real root cause. Detecting CI via
# `GITHUB_ACTIONS` surfaces the misconfiguration at stack-load time.
_IS_GITHUB_ACTIONS: bool = os.environ.get("GITHUB_ACTIONS") == "true"
if cfg.get("imageTag") is None and _IS_GITHUB_ACTIONS:
    raise pulumi.RunError(
        "vici-infra:imageTag is required in CI — "
        "check cd-base.yml config-map passthrough"
    )

# CI passes --config vici-infra:imageTag=<sha>; local fallback to ENV.
IMAGE_TAG: str = cfg.get("imageTag") or ENV
