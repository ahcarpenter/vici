"""Namespace-scoped NetworkPolicies implementing default-deny + explicit allow rules.

Enforces least-privilege network access between namespaces. Without these policies,
any pod can communicate with any other pod in the cluster.

Traffic map (from RESEARCH.md, verified against codebase):
  vici:
    ingress:  port 8000 from kube-system (LB health checks) + observability (Prometheus)
    egress:   port 7233 -> temporal, port 4317 -> observability, port 443 -> 0.0.0.0/0

  temporal:
    ingress:  port 7233 from vici
    egress:   port 9200 -> observability, port 443 -> 0.0.0.0/0 (GCP WIF)

  observability:
    ingress:  port 4317 from vici (OTLP), port 16686 from any (jaeger UI),
              port 9200 from temporal
    egress:   port 9200 intra-namespace, port 7233 -> temporal, port 8000 -> vici

  cert-manager:
    egress:   port 443 -> 0.0.0.0/0 (Let's Encrypt ACME + K8s API)

  external-secrets:
    egress:   port 443 -> 0.0.0.0/0 (GCP Secret Manager API + K8s API)
"""

import pulumi_kubernetes as k8s
from pulumi import ResourceOptions

from components.namespaces import k8s_provider, namespaces

_NAMESPACES = [
    "vici",
    "temporal",
    "observability",
    "cert-manager",
    "external-secrets",
]

# ---------------------------------------------------------------------------
# Default-deny-all and DNS-egress-allow per namespace
# ---------------------------------------------------------------------------

# default_deny_policies: one NetworkPolicy per namespace blocking all ingress + egress.
# Zero-trust baseline; explicit allow rules below open only declared ports.
default_deny_policies: dict[str, k8s.networking.v1.NetworkPolicy] = {}

# dns_allow_policies: one NetworkPolicy per namespace allowing port 53 UDP+TCP egress.
# Without this, kube-dns resolution fails and all service-to-service traffic breaks.
dns_allow_policies: dict[str, k8s.networking.v1.NetworkPolicy] = {}


def _default_deny(ns: str) -> k8s.networking.v1.NetworkPolicy:
    """Return a default-deny-all NetworkPolicy for the given namespace."""
    return k8s.networking.v1.NetworkPolicy(
        f"netpol-default-deny-{ns}",
        metadata=k8s.meta.v1.ObjectMetaArgs(name="default-deny-all", namespace=ns),
        spec=k8s.networking.v1.NetworkPolicySpecArgs(
            pod_selector=k8s.meta.v1.LabelSelectorArgs(),
            policy_types=["Ingress", "Egress"],
        ),
        opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces[ns]]),
    )


def _dns_allow(ns: str) -> k8s.networking.v1.NetworkPolicy:
    """Return an allow-dns-egress NetworkPolicy for the given namespace."""
    return k8s.networking.v1.NetworkPolicy(
        f"netpol-allow-dns-{ns}",
        metadata=k8s.meta.v1.ObjectMetaArgs(name="allow-dns-egress", namespace=ns),
        spec=k8s.networking.v1.NetworkPolicySpecArgs(
            pod_selector=k8s.meta.v1.LabelSelectorArgs(),
            policy_types=["Egress"],
            egress=[
                k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                    ports=[
                        k8s.networking.v1.NetworkPolicyPortArgs(
                            port=53, protocol="UDP"
                        ),
                        k8s.networking.v1.NetworkPolicyPortArgs(
                            port=53, protocol="TCP"
                        ),
                    ],
                )
            ],
        ),
        opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces[ns]]),
    )


# One default-deny-all + allow-dns-egress per namespace (explicit for static analysis)
default_deny_policies["vici"] = _default_deny("vici")  # default-deny-all
default_deny_policies["temporal"] = _default_deny("temporal")  # default-deny-all
default_deny_policies["observability"] = _default_deny(
    "observability"
)  # default-deny-all
default_deny_policies["cert-manager"] = _default_deny(
    "cert-manager"
)  # default-deny-all
default_deny_policies["external-secrets"] = _default_deny(
    "external-secrets"
)  # default-deny-all

dns_allow_policies["vici"] = _dns_allow("vici")  # allow-dns-egress
dns_allow_policies["temporal"] = _dns_allow("temporal")  # allow-dns-egress
dns_allow_policies["observability"] = _dns_allow("observability")  # allow-dns-egress
dns_allow_policies["cert-manager"] = _dns_allow("cert-manager")  # allow-dns-egress
dns_allow_policies["external-secrets"] = _dns_allow(
    "external-secrets"
)  # allow-dns-egress

# ---------------------------------------------------------------------------
# Per-namespace traffic allow rules
# ---------------------------------------------------------------------------

# allow_policies: named allow rules keyed by a descriptive identifier.
allow_policies: dict[str, k8s.networking.v1.NetworkPolicy] = {}

# --- vici namespace ---

# Ingress: GKE LB health checks (kube-system) + Prometheus scrapes (observability)
allow_policies["vici-ingress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-vici-ingress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="allow-ingress-lb-prometheus", namespace="vici"
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(match_labels={"app": "vici"}),
        policy_types=["Ingress"],
        ingress=[
            k8s.networking.v1.NetworkPolicyIngressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=8000, protocol="TCP")
                ],
                from_=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={"kubernetes.io/metadata.name": "kube-system"},
                        ),
                    ),
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={
                                "kubernetes.io/metadata.name": "observability"
                            },
                        ),
                    ),
                ],
            )
        ],
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["vici"]]),
)

# Egress: temporal-frontend:7233, jaeger-collector OTLP:4317, external HTTPS:443
allow_policies["vici-egress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-vici-egress",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="allow-egress-app", namespace="vici"),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(match_labels={"app": "vici"}),
        policy_types=["Egress"],
        egress=[
            # -> temporal-frontend:7233
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=7233, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={"kubernetes.io/metadata.name": "temporal"},
                        ),
                    )
                ],
            ),
            # -> jaeger-collector:4317 OTLP gRPC
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=4317, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={
                                "kubernetes.io/metadata.name": "observability"
                            },
                        ),
                    )
                ],
            ),
            # -> External APIs (GCP Secret Manager, Twilio, OpenAI, Pinecone) over HTTPS
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=443, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        ip_block=k8s.networking.v1.IPBlockArgs(cidr="0.0.0.0/0"),
                    )
                ],
            ),
        ],
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["vici"]]),
)

# --- temporal namespace ---

# Ingress: vici namespace on port 7233 (temporal-frontend)
allow_policies["temporal-ingress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-temporal-ingress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="allow-ingress-frontend", namespace="temporal"
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),
        policy_types=["Ingress"],
        ingress=[
            k8s.networking.v1.NetworkPolicyIngressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=7233, protocol="TCP")
                ],
                from_=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={"kubernetes.io/metadata.name": "vici"},
                        ),
                    )
                ],
            )
        ],
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["temporal"]]),
)

# Egress: opensearch:9200 in observability + HTTPS:443 for GCP Auth Proxy WIF
allow_policies["temporal-egress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-temporal-egress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="allow-egress-temporal", namespace="temporal"
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),
        policy_types=["Egress"],
        egress=[
            # -> opensearch visibility store in observability namespace
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=9200, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={
                                "kubernetes.io/metadata.name": "observability"
                            },
                        ),
                    )
                ],
            ),
            # -> GCP APIs for Auth Proxy WIF token exchange
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=443, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        ip_block=k8s.networking.v1.IPBlockArgs(cidr="0.0.0.0/0"),
                    )
                ],
            ),
        ],
    ),
    opts=ResourceOptions(provider=k8s_provider, depends_on=[namespaces["temporal"]]),
)

# --- observability namespace ---

# Ingress: OTLP from vici:4317, jaeger UI from any:16686, opensearch from temporal:9200
allow_policies["obs-ingress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-obs-ingress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="allow-ingress-obs", namespace="observability"
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),
        policy_types=["Ingress"],
        ingress=[
            # OTLP gRPC from vici pods
            k8s.networking.v1.NetworkPolicyIngressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=4317, protocol="TCP")
                ],
                from_=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={"kubernetes.io/metadata.name": "vici"},
                        ),
                    )
                ],
            ),
            # Jaeger UI from any (port-forward access; T-6-03c: accept)
            k8s.networking.v1.NetworkPolicyIngressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=16686, protocol="TCP")
                ],
            ),
            # OpenSearch from temporal (visibility writes)
            k8s.networking.v1.NetworkPolicyIngressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=9200, protocol="TCP")
                ],
                from_=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={"kubernetes.io/metadata.name": "temporal"},
                        ),
                    )
                ],
            ),
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider, depends_on=[namespaces["observability"]]
    ),
)

# Egress: intra-namespace opensearch:9200, temporal:7233 (Prometheus), vici:8000
allow_policies["obs-egress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-obs-egress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="allow-egress-obs", namespace="observability"
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),
        policy_types=["Egress"],
        egress=[
            # Intra-namespace: jaeger-collector/query -> opensearch
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=9200, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={
                                "kubernetes.io/metadata.name": "observability"
                            },
                        ),
                    )
                ],
            ),
            # Prometheus -> temporal-frontend for metrics scrape
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=7233, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={"kubernetes.io/metadata.name": "temporal"},
                        ),
                    )
                ],
            ),
            # Prometheus -> vici-app for /metrics scrape
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=8000, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        namespace_selector=k8s.meta.v1.LabelSelectorArgs(
                            match_labels={"kubernetes.io/metadata.name": "vici"},
                        ),
                    )
                ],
            ),
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider, depends_on=[namespaces["observability"]]
    ),
)

# --- cert-manager namespace ---

# Ingress: webhook validation + metrics from kube-apiserver.
# Same GKE Autopilot data-plane routing as external-secrets.
# cert-manager webhook listens on 10250, healthz on 6080, metrics on 9402.
allow_policies["certmgr-webhook-ingress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-certmgr-webhook-ingress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="allow-ingress-webhook", namespace="cert-manager"
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),
        policy_types=["Ingress"],
        ingress=[
            k8s.networking.v1.NetworkPolicyIngressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=10250, protocol="TCP"),
                    k8s.networking.v1.NetworkPolicyPortArgs(port=6080, protocol="TCP"),
                    k8s.networking.v1.NetworkPolicyPortArgs(port=9402, protocol="TCP"),
                    k8s.networking.v1.NetworkPolicyPortArgs(port=9403, protocol="TCP"),
                ],
            )
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider, depends_on=[namespaces["cert-manager"]]
    ),
)

# Egress: HTTPS 443 to internet (Let's Encrypt ACME challenges + Kubernetes API)
allow_policies["certmgr-egress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-certmgr-egress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="allow-egress-certmgr", namespace="cert-manager"
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),
        policy_types=["Egress"],
        egress=[
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=443, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        ip_block=k8s.networking.v1.IPBlockArgs(cidr="0.0.0.0/0"),
                    )
                ],
            )
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider, depends_on=[namespaces["cert-manager"]]
    ),
)

# --- external-secrets namespace ---

# Ingress: webhook validation from kube-apiserver.
# GKE Autopilot routes webhook calls through the data plane, which IS
# subject to NetworkPolicy. The ESO webhook pod listens on port 10250
# (not 443 — the Service translates 443 -> 10250). Without this rule,
# ExternalSecret creation fails with webhook timeout.
allow_policies["eso-webhook-ingress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-eso-webhook-ingress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="allow-ingress-webhook", namespace="external-secrets"
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),
        policy_types=["Ingress"],
        ingress=[
            k8s.networking.v1.NetworkPolicyIngressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=10250, protocol="TCP"),
                    k8s.networking.v1.NetworkPolicyPortArgs(port=8080, protocol="TCP"),
                    k8s.networking.v1.NetworkPolicyPortArgs(port=8081, protocol="TCP"),
                ],
            )
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider, depends_on=[namespaces["external-secrets"]]
    ),
)

# Egress: HTTPS 443 to internet (GCP Secret Manager API + Kubernetes API)
allow_policies["eso-egress"] = k8s.networking.v1.NetworkPolicy(
    "netpol-eso-egress",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="allow-egress-eso", namespace="external-secrets"
    ),
    spec=k8s.networking.v1.NetworkPolicySpecArgs(
        pod_selector=k8s.meta.v1.LabelSelectorArgs(),
        policy_types=["Egress"],
        egress=[
            k8s.networking.v1.NetworkPolicyEgressRuleArgs(
                ports=[
                    k8s.networking.v1.NetworkPolicyPortArgs(port=443, protocol="TCP")
                ],
                to=[
                    k8s.networking.v1.NetworkPolicyPeerArgs(
                        ip_block=k8s.networking.v1.IPBlockArgs(cidr="0.0.0.0/0"),
                    )
                ],
            )
        ],
    ),
    opts=ResourceOptions(
        provider=k8s_provider, depends_on=[namespaces["external-secrets"]]
    ),
)
