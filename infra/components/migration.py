import time

import pulumi
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.database import app_db_instance
from components.namespaces import k8s_provider, namespaces
from components.registry import registry_url
from components.secrets import external_secrets
from config import ENV

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_AUTH_PROXY_IMAGE = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.1"
_AUTH_PROXY_RUN_AS_USER = 65532
_SOCKET_MOUNT_PATH = "/cloudsql"
_VOLUME_NAME = "cloudsql-socket"
_JOB_BACKOFF_LIMIT = 0  # Fail fast, no retries (D-12)
_JOB_TTL_SECONDS = 300  # Clean up after 5 minutes
_PROXY_HEALTH_PORT = 9801

# ---------------------------------------------------------------------------
# Alembic migration Job with Cloud SQL Auth Proxy native sidecar
# ---------------------------------------------------------------------------

_DEPLOY_TIMESTAMP = str(int(time.time()))

migration_job = k8s.batch.v1.Job(
    "alembic-migration",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name=f"alembic-migration-{ENV}",
        namespace="vici",
        annotations={"deploy-timestamp": _DEPLOY_TIMESTAMP},
    ),
    spec=k8s.batch.v1.JobSpecArgs(
        backoff_limit=_JOB_BACKOFF_LIMIT,
        ttl_seconds_after_finished=_JOB_TTL_SECONDS,
        template=k8s.core.v1.PodTemplateSpecArgs(
            spec=k8s.core.v1.PodSpecArgs(
                service_account_name="vici-app",
                restart_policy="Never",
                volumes=[
                    k8s.core.v1.VolumeArgs(
                        name=_VOLUME_NAME,
                        empty_dir=k8s.core.v1.EmptyDirVolumeSourceArgs(),
                    ),
                ],
                init_containers=[
                    k8s.core.v1.ContainerArgs(
                        name="cloud-sql-proxy",
                        image=_AUTH_PROXY_IMAGE,
                        restart_policy="Always",  # Native sidecar (K8s 1.28+)
                        args=[
                            "--structured-logs",
                            "--private-ip",
                            "--health-check",
                            f"--http-port={_PROXY_HEALTH_PORT}",
                            "--http-address=0.0.0.0",
                            pulumi.Output.concat(
                                "--unix-socket=",
                                _SOCKET_MOUNT_PATH,
                            ),
                            app_db_instance.connection_name,
                        ],
                        # K8s gates main container start on sidecar startup
                        # probe passing — no shell wait loop needed.
                        startup_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(
                                path="/startup",
                                port=_PROXY_HEALTH_PORT,
                            ),
                            period_seconds=2,
                            failure_threshold=60,  # 2s * 60 = 120s budget
                        ),
                        security_context=k8s.core.v1.SecurityContextArgs(
                            run_as_non_root=True,
                            run_as_user=_AUTH_PROXY_RUN_AS_USER,
                        ),
                        resources=k8s.core.v1.ResourceRequirementsArgs(
                            requests={"cpu": "100m", "memory": "128Mi"},
                            limits={"cpu": "200m", "memory": "256Mi"},
                        ),
                        volume_mounts=[
                            k8s.core.v1.VolumeMountArgs(
                                name=_VOLUME_NAME,
                                mount_path=_SOCKET_MOUNT_PATH,
                            ),
                        ],
                    ),
                ],
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="alembic-migration",
                        image=pulumi.Output.concat(registry_url, "/vici:", ENV),
                        image_pull_policy="Always",
                        command=["uv", "run", "alembic", "upgrade", "head"],
                        resources=k8s.core.v1.ResourceRequirementsArgs(
                            requests={"cpu": "100m", "memory": "256Mi"},
                            limits={"cpu": "500m", "memory": "512Mi"},
                        ),
                        env_from=[
                            k8s.core.v1.EnvFromSourceArgs(
                                secret_ref=k8s.core.v1.SecretEnvSourceArgs(
                                    name="database-url",
                                ),
                            ),
                        ],
                        volume_mounts=[
                            k8s.core.v1.VolumeMountArgs(
                                name=_VOLUME_NAME,
                                mount_path=_SOCKET_MOUNT_PATH,
                            ),
                        ],
                    ),
                ],
            ),
        ),
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        delete_before_replace=True,
        depends_on=[
            app_db_instance,
            external_secrets["database-url"],
            namespaces["vici"],
        ],
    ),
)

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

pulumi.export("migration_job_name", migration_job.metadata.apply(lambda m: m.name))
