import pulumi
import pulumi_gcp as gcp
from pulumi import ResourceOptions

from components.cluster import cluster
from config import ENV, PROJECT_ID, REGION

# -- Constants (no magic numbers) ------------------------------------------

_DB_TIER = "db-g1-small"  # D-01
_DB_VERSION = "POSTGRES_16"
_DB_STORAGE_GB = 10  # D-04
_DISK_TYPE = "PD_SSD"
_PEERING_IP_PREFIX_LENGTH = 16

# D-02, D-05: app-prod uses REGIONAL HA; all temporal instances are ZONAL.
_HA_TYPE: dict[str, str] = {
    "app-dev": "ZONAL",
    "app-staging": "ZONAL",
    "app-prod": "REGIONAL",
    "temporal-dev": "ZONAL",
    "temporal-staging": "ZONAL",
    "temporal-prod": "ZONAL",
}

# D-03: backups disabled in dev to reduce cost.
_BACKUPS_ENABLED: dict[str, bool] = {
    "dev": False,
    "staging": True,
    "prod": True,
}

# -- VPC Peering (prerequisite for private IP) --------------------------------

# Allocate a private IP range inside the VPC that servicenetworking will use.
global_address = gcp.compute.GlobalAddress(
    "cloudsql-private-ip-range",
    project=PROJECT_ID,
    purpose="VPC_PEERING",
    address_type="INTERNAL",
    prefix_length=_PEERING_IP_PREFIX_LENGTH,
    network=cluster.network,
)

# Establish the peering connection so Cloud SQL can use private IP.
vpc_peering_connection = gcp.servicenetworking.Connection(
    "cloudsql-vpc-peering",
    network=cluster.network,
    service="servicenetworking.googleapis.com",
    reserved_peering_ranges=[global_address.name],
    opts=ResourceOptions(depends_on=[global_address]),
)

# -- App Cloud SQL Instance (DB-01) -------------------------------------------

app_db_instance = gcp.sql.DatabaseInstance(
    f"vici-app-db-{ENV}",
    name=f"vici-app-{ENV}",
    database_version=_DB_VERSION,
    region=REGION,
    project=PROJECT_ID,
    settings=gcp.sql.DatabaseInstanceSettingsArgs(
        tier=_DB_TIER,
        availability_type=_HA_TYPE[f"app-{ENV}"],
        disk_size=_DB_STORAGE_GB,
        disk_type=_DISK_TYPE,
        ip_configuration=gcp.sql.DatabaseInstanceSettingsIpConfigurationArgs(
            ipv4_enabled=False,
            private_network=cluster.network,
            enable_private_path_for_google_cloud_services=True,
        ),
        backup_configuration=gcp.sql.DatabaseInstanceSettingsBackupConfigurationArgs(
            enabled=_BACKUPS_ENABLED[ENV],
        ),
    ),
    opts=ResourceOptions(depends_on=[vpc_peering_connection], protect=True),
)

app_database = gcp.sql.Database(
    f"vici-app-database-{ENV}",
    name="vici",
    instance=app_db_instance.name,
)

# -- Temporal Cloud SQL Instance (DB-02) --------------------------------------

temporal_db_instance = gcp.sql.DatabaseInstance(
    f"temporal-db-{ENV}",
    name=f"vici-temporal-{ENV}",
    database_version=_DB_VERSION,
    region=REGION,
    project=PROJECT_ID,
    settings=gcp.sql.DatabaseInstanceSettingsArgs(
        tier=_DB_TIER,
        availability_type=_HA_TYPE[f"temporal-{ENV}"],
        disk_size=_DB_STORAGE_GB,
        disk_type=_DISK_TYPE,
        ip_configuration=gcp.sql.DatabaseInstanceSettingsIpConfigurationArgs(
            ipv4_enabled=False,
            private_network=cluster.network,
            enable_private_path_for_google_cloud_services=True,
        ),
        backup_configuration=gcp.sql.DatabaseInstanceSettingsBackupConfigurationArgs(
            enabled=_BACKUPS_ENABLED[ENV],
        ),
    ),
    opts=ResourceOptions(depends_on=[vpc_peering_connection], protect=True),
)

temporal_database = gcp.sql.Database(
    f"temporal-database-{ENV}",
    name="temporal",
    instance=temporal_db_instance.name,
)

temporal_visibility_database = gcp.sql.Database(
    f"temporal-visibility-database-{ENV}",
    name="temporal_visibility",
    instance=temporal_db_instance.name,
)

# -- Exports ------------------------------------------------------------------

pulumi.export("app_db_connection_name", app_db_instance.connection_name)
pulumi.export("temporal_db_connection_name", temporal_db_instance.connection_name)
