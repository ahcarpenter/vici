import pulumi

cfg = pulumi.Config()
gcp_cfg = pulumi.Config("gcp")

ENV: str = cfg.require("env")                    # "dev" | "staging" | "prod"
CLUSTER_NAME: str = cfg.require("cluster_name")  # "vici-dev" | "vici-staging" | "vici-prod"
REGISTRY_NAME: str = cfg.require("registry_name")
PROJECT_ID: str = gcp_cfg.require("project")
REGION: str = gcp_cfg.get("region") or "us-central1"
APP_HOSTNAME: str = cfg.require("app_hostname")  # "dev.usevici.com" | "staging.usevici.com" | "usevici.com"
GITHUB_ORG: str = cfg.require("github_org")      # GitHub organization or user owning the repo
