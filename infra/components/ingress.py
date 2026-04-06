import pulumi
import pulumi_gcp as gcp
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.app import app_service
from components.certmanager import certmanager_release
from components.namespaces import k8s_provider, namespaces
from config import APP_HOSTNAME, ENV, PROJECT_ID

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_ACME_STAGING_SERVER = "https://acme-staging-v02.api.letsencrypt.org/directory"
_ACME_PROD_SERVER = "https://acme-v02.api.letsencrypt.org/directory"
_ACME_EMAIL = "ops@usevici.com"
_TLS_SECRET_NAME = "vici-tls"
_APP_SERVICE_NAME = "vici-app"
_APP_SERVICE_PORT = "http"
_INGRESS_CLASS = "gce"
_WEBHOOK_SECRET_ID = "webhook-base-url"

# ---------------------------------------------------------------------------
# Staging Issuer (D-13 namespace-scoped, D-14 staging first)
# ---------------------------------------------------------------------------

staging_issuer = k8s.apiextensions.CustomResource(
    "letsencrypt-staging",
    api_version="cert-manager.io/v1",
    kind="Issuer",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="letsencrypt-staging",
        namespace="vici",
    ),
    spec={
        "acme": {
            "server": _ACME_STAGING_SERVER,
            "email": _ACME_EMAIL,
            "privateKeySecretRef": {"name": "letsencrypt-staging-key"},
            "solvers": [{"http01": {"ingress": {"class": _INGRESS_CLASS}}}],
        }
    },
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[certmanager_release, namespaces["vici"]],
    ),
)

# ---------------------------------------------------------------------------
# Production Issuer (coexists with staging per D-14)
# ---------------------------------------------------------------------------

prod_issuer = k8s.apiextensions.CustomResource(
    "letsencrypt-prod",
    api_version="cert-manager.io/v1",
    kind="Issuer",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="letsencrypt-prod",
        namespace="vici",
    ),
    spec={
        "acme": {
            "server": _ACME_PROD_SERVER,
            "email": _ACME_EMAIL,
            "privateKeySecretRef": {"name": "letsencrypt-prod-key"},
            "solvers": [{"http01": {"ingress": {"class": _INGRESS_CLASS}}}],
        }
    },
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[certmanager_release, namespaces["vici"]],
    ),
)

# ---------------------------------------------------------------------------
# Placeholder TLS Secret (breaks chicken-and-egg per Pitfall 1 in RESEARCH.md)
# GKE Ingress requires the TLS secret to exist before cert-manager can populate it.
# ---------------------------------------------------------------------------

tls_secret_placeholder = k8s.core.v1.Secret(
    "vici-tls-placeholder",
    metadata=k8s.meta.v1.ObjectMetaArgs(name=_TLS_SECRET_NAME, namespace="vici"),
    type="kubernetes.io/tls",
    string_data={"tls.crt": "", "tls.key": ""},
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["vici"]]),
)

# ---------------------------------------------------------------------------
# GKE Ingress (APP-04, D-03)
# Uses annotation-based ingress class (NOT ingressClassName -- not reliable on GKE)
# HTTP allowed for ACME HTTP-01 challenge
# Annotated with staging issuer by default (switch to prod post-verify per D-14)
# depends_on app_service ensures backend Service exists before Ingress references it
# ---------------------------------------------------------------------------

vici_ingress = k8s.networking.v1.Ingress(
    "vici-ingress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="vici-ingress",
        namespace="vici",
        annotations={
            "kubernetes.io/ingress.class": _INGRESS_CLASS,
            "kubernetes.io/ingress.allow-http": "true",
            "cert-manager.io/issuer": "letsencrypt-staging",
        },
    ),
    spec=k8s.networking.v1.IngressSpecArgs(
        tls=[
            k8s.networking.v1.IngressTLSArgs(
                secret_name=_TLS_SECRET_NAME,
                hosts=[APP_HOSTNAME],
            )
        ],
        rules=[
            k8s.networking.v1.IngressRuleArgs(
                host=APP_HOSTNAME,
                http=k8s.networking.v1.HTTPIngressRuleValueArgs(
                    paths=[
                        k8s.networking.v1.HTTPIngressPathArgs(
                            path="/",
                            path_type="Prefix",
                            backend=k8s.networking.v1.IngressBackendArgs(
                                service=k8s.networking.v1.IngressServiceBackendArgs(
                                    name=_APP_SERVICE_NAME,
                                    port=k8s.networking.v1.ServiceBackendPortArgs(
                                        name=_APP_SERVICE_PORT
                                    ),
                                ),
                            ),
                        )
                    ],
                ),
            )
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider,
        depends_on=[tls_secret_placeholder, staging_issuer, prod_issuer, app_service],
    ),
)

# ---------------------------------------------------------------------------
# WEBHOOK_BASE_URL SecretVersion (APP-06)
# Writes the app hostname to GCP Secret Manager so the ExternalSecret-generated
# K8s Secret webhook-base-url has the correct value for Twilio signature validation.
# The Secret resource was created in Phase 2 (secrets.py).
# depends_on vici_ingress ensures the Ingress is provisioned before writing the value.
# ---------------------------------------------------------------------------

webhook_base_url_version = gcp.secretmanager.SecretVersion(
    "webhook-base-url-version",
    secret=f"projects/{PROJECT_ID}/secrets/{ENV}-{_WEBHOOK_SECRET_ID}",
    secret_data=pulumi.Output.concat("https://", APP_HOSTNAME),
    opts=ResourceOptions(depends_on=[vici_ingress]),
)

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

pulumi.export("ingress_name", vici_ingress.metadata.apply(lambda m: m.name))
pulumi.export("webhook_base_url", pulumi.Output.concat("https://", APP_HOSTNAME))
