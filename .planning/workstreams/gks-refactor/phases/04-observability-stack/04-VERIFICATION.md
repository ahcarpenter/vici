---
phase: 04-observability-stack
verified: 2026-04-05T00:00:00Z
status: human_needed
score: 4/4 infrastructure truths verified; runtime behavior requires human verification
human_verification:
  - test: "Jaeger UI shows traces from the OTel collector endpoint"
    expected: "After deploying and sending a test request, Jaeger UI at jaeger-query.observability.svc.cluster.local:16686 shows traces received from jaeger-collector.observability.svc.cluster.local:4317"
    why_human: "Requires a live cluster, deployed pods, and a trace-emitting client — cannot verify from source alone"
  - test: "Prometheus scrapes FastAPI /metrics via ServiceMonitor"
    expected: "Prometheus targets page shows fastapi-metrics ServiceMonitor in the vici namespace as UP (once Phase 5 app is deployed)"
    why_human: "Requires running Prometheus and FastAPI app in cluster; ServiceMonitor CR is correctly defined in code but scrape success depends on runtime"
  - test: "Grafana is accessible and dashboards are pre-provisioned"
    expected: "Grafana UI shows FastAPI and Temporal dashboards loaded via sidecar; Jaeger datasource is listed"
    why_human: "Requires running Grafana pod and sidecar discovery — cannot be verified without live cluster"
  - test: "OTEL_EXPORTER_OTLP_ENDPOINT secret resolves to in-cluster Jaeger collector"
    expected: "kubectl get secret otel-exporter-otlp-endpoint -n vici shows value http://jaeger-collector.observability.svc.cluster.local:4317"
    why_human: "Requires ESO to be running and GCP Secret Manager to be populated with the correct value; ExternalSecret CR is correctly defined in code but sync requires a live cluster"
  - test: "Temporal dashboard is the real Grafana.com dashboard (not placeholder)"
    expected: "grafana/provisioning/dashboards/temporal.json exists and contains a non-placeholder Temporal SDK dashboard"
    why_human: "File is not present in the repo — it is downloaded at pulumi up runtime. Operator must confirm the download succeeded and temporal.json is cached to disk after first pulumi up"
---

# Phase 04: Observability Stack Verification Report

**Phase Goal:** All application and infrastructure metrics, traces, and dashboards are operational so the first real request through the app generates observable telemetry
**Verified:** 2026-04-05
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Jaeger UI shows traces from the OTel collector endpoint (`jaeger-collector.observability.svc.cluster.local:4317`) | ? HUMAN | Infrastructure code verified; runtime behavior requires live cluster |
| 2 | Prometheus is scraping the FastAPI `/metrics` endpoint via ServiceMonitor | ? HUMAN | ServiceMonitor CR correctly defined; scrape success requires running app + cluster |
| 3 | Grafana is accessible and the existing FastAPI and Temporal dashboards are pre-provisioned | ? HUMAN | ConfigMaps and sidecar config verified; dashboard visibility requires running cluster |
| 4 | `OTEL_EXPORTER_OTLP_ENDPOINT` secret resolves to the in-cluster Jaeger collector | ? HUMAN | ExternalSecret CR targets correct namespace and key; sync requires live ESO + GCP Secret Manager |

**Score:** 0/4 truths can be confirmed without a live cluster, but all underlying infrastructure code is verified correct.

### Infrastructure Must-Haves (from Plan frontmatter)

All infrastructure must-haves from Plans 01, 02, and 03 are VERIFIED in the codebase:

**Plan 01 (Jaeger):**

| Must-Have | Status | Evidence |
|-----------|--------|----------|
| Jaeger collector accepts OTLP on ports 4317/4318 in observability namespace | VERIFIED | `infra/components/jaeger.py` lines 27-29, 200-211 — ports defined with correct names |
| Jaeger query serves UI on port 16686 in observability namespace | VERIFIED | `infra/components/jaeger.py` line 29, 291-295 |
| Both Jaeger components connect to existing in-cluster OpenSearch | VERIFIED | Both configs use `f"http://{OPENSEARCH_SERVICE_HOST}:9200"` (lines 64, 127) |

**Plan 02 (Prometheus/Grafana):**

| Must-Have | Status | Evidence |
|-----------|--------|----------|
| Prometheus running in observability namespace, discovers all ServiceMonitors | VERIFIED | `serviceMonitorSelectorNilUsesHelmValues: False` at line 119 |
| Grafana running with Prometheus default datasource and Jaeger additional datasource | VERIFIED | `additionalDataSources` with `type: jaeger` at lines 142-151 |
| FastAPI dashboard JSON provisioned via sidecar ConfigMap | VERIFIED | `fastapi_dashboard_configmap` with label `grafana_dashboard: "1"` at lines 165-177 |
| Temporal workflow dashboard JSON provisioned via sidecar ConfigMap | VERIFIED | `temporal_dashboard_configmap` with label `grafana_dashboard: "1"` at lines 183-195; download-or-placeholder logic at lines 47-90 |
| ServiceMonitor for FastAPI /metrics created and ready for Phase 5 | VERIFIED | `fastapi_service_monitor` CRD in `vici` namespace, targets `app=vici`, port `http`, path `/metrics`, interval `30s` at lines 203-219 |

**Plan 03 (Wiring + OTEL Secret):**

| Must-Have | Status | Evidence |
|-----------|--------|----------|
| All observability components registered in Pulumi entry point | VERIFIED | `infra/__main__.py` lines 20-21 import both jaeger and prometheus components |
| OTEL_EXPORTER_OTLP_ENDPOINT secret synced to vici namespace | VERIFIED | `infra/components/secrets.py` line 29 — tuple targets `"vici"` namespace |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `infra/components/jaeger.py` | Jaeger v2 collector and query Deployments, Services, ConfigMaps | VERIFIED | 416 lines; 2 ConfigMaps, 2 Deployments, 2 Services, 2 exports; syntax valid |
| `infra/components/prometheus.py` | kube-prometheus-stack Helm release, dashboard ConfigMaps, ServiceMonitor | VERIFIED | 231 lines; Helm release, 2 dashboard ConfigMaps, ServiceMonitor, 2 exports; syntax valid |
| `infra/__main__.py` | Observability component registration | VERIFIED | Lines 20-21 contain both import lines with `# noqa: F401` |
| `infra/components/secrets.py` | OTEL ExternalSecret targeting vici namespace | VERIFIED | Line 29 — `("otel-exporter-otlp-endpoint", "vici", "otel-exporter-otlp-endpoint")` |
| `grafana/provisioning/dashboards/temporal.json` | Temporal dashboard JSON cached on disk | MISSING | File not present; will be downloaded at first `pulumi up` runtime; placeholder activates on network failure |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `infra/__main__.py` | `infra/components/jaeger.py` | `from components.jaeger import` | WIRED | Line 20 of `__main__.py` |
| `infra/__main__.py` | `infra/components/prometheus.py` | `from components.prometheus import` | WIRED | Line 21 of `__main__.py` |
| `infra/components/jaeger.py` | `infra/components/opensearch.py` | `depends_on=opensearch_index_template_job` | WIRED | Lines 261, 347 — both Deployments depend on `opensearch_index_template_job` |
| `infra/components/prometheus.py` | `grafana/provisioning/dashboards/fastapi.json` | File read at module load time | WIRED | Lines 40-41 — `open(_FASTAPI_DASHBOARD_PATH)` |
| `infra/components/prometheus.py` | Grafana sidecar | `grafana_dashboard: "1"` label on both ConfigMaps | WIRED | Lines 169, 188 — labels match sidecar config in Helm values at line 138-140 |
| `infra/components/secrets.py` | `otel-exporter-otlp-endpoint` in `vici` namespace | ExternalSecret CR loop | WIRED | Line 29 tuple, loop at lines 133-154 |

---

### Data-Flow Trace (Level 4)

Not applicable — this phase produces Pulumi infrastructure definitions (IaC), not runtime data-rendering components. There are no React/UI components or API routes in scope.

---

### Behavioral Spot-Checks

Step 7b: SKIPPED — all artifacts are Pulumi Python modules defining Kubernetes resources. They cannot be executed independently; deployment requires `pulumi up` against a live cluster. Syntax validation was performed instead.

```
python3 -c "import ast; ast.parse(open('infra/components/jaeger.py').read())"     → PASS
python3 -c "import ast; ast.parse(open('infra/components/prometheus.py').read())" → PASS
python3 -c "import ast; ast.parse(open('infra/__main__.py').read())"              → PASS
python3 -c "import ast; ast.parse(open('infra/components/secrets.py').read())"    → PASS
```

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| OBS-01 | Pre-condition (Phase 3) | OpenSearch deployed in `observability` namespace | NOT IN SCOPE | OBS-01 is a Phase 3 deliverable. Plans explicitly treat it as a pre-condition check only (04-01-PLAN.md Task 0). Traceability table mapping OBS-01 to Phase 4 in REQUIREMENTS.md appears to be an error in that table — the actual requirement is fulfilled by Phase 3 OpenSearch deployment. |
| OBS-02 | 04-01 | Jaeger v2 deployed in `observability` namespace connected to in-cluster OpenSearch | VERIFIED (infra) | `infra/components/jaeger.py` — full implementation present |
| OBS-03 | 04-02 | kube-prometheus-stack deployed; Prometheus scrapes FastAPI `/metrics` via ServiceMonitor | VERIFIED (infra) | `infra/components/prometheus.py` — Helm release + ServiceMonitor |
| OBS-04 | 04-02 | Grafana provisioned with FastAPI and Temporal dashboards | VERIFIED (infra) | Both dashboard ConfigMaps with sidecar label present in `prometheus.py` |
| OBS-05 | 04-03 | `OTEL_EXPORTER_OTLP_ENDPOINT` secret points to in-cluster Jaeger collector | VERIFIED (infra) | ExternalSecret in `vici` namespace defined in `secrets.py` line 29 |

**Note on OBS-01:** The REQUIREMENTS.md traceability table lists OBS-01 under Phase 4, but both the ROADMAP.md Phase 4 requirements list (`OBS-01, OBS-02, OBS-03, OBS-04, OBS-05`) and the 04-01-PLAN.md explicitly scope OBS-01 as a Phase 3 pre-condition that is checked but not implemented in Phase 4. The OpenSearch deployment itself lives in `infra/components/opensearch.py` (Phase 3 work). This verification treats OBS-01 as delivered by Phase 3 and out of scope for Phase 4 gap analysis.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `infra/components/prometheus.py` | 65-87 | Temporal dashboard placeholder activates if grafana.com unreachable at `pulumi up` time | WARNING | Grafana would show a stub "TODO" panel instead of real Temporal metrics; dashboard can be replaced post-deploy by downloading the JSON manually |

**Assessment:** The placeholder is guarded by a try/except and only activates on network failure. The plan explicitly specified this fallback as acceptable. However, the file `grafana/provisioning/dashboards/temporal.json` is not pre-cached in the repo, meaning every fresh checkout requires a network fetch at `pulumi up` time. This is an operational risk but not a blocker for infrastructure correctness.

---

### Human Verification Required

The following items cannot be verified programmatically — they require a live cluster deployment:

#### 1. Jaeger Trace Collection and UI

**Test:** Run `kubectl port-forward svc/jaeger-query 16686:16686 -n observability` and open `http://localhost:16686`. Send a test OTLP trace to `jaeger-collector.observability.svc.cluster.local:4317` from within the cluster (or via port-forward on 4317). Verify the trace appears in the Jaeger UI.
**Expected:** At least one trace visible in Jaeger UI from the test service.
**Why human:** Requires running pods in a live cluster, network connectivity, and a trace producer.

#### 2. Prometheus ServiceMonitor Scrape Success

**Test:** After Phase 5 app deployment, run `kubectl port-forward svc/kube-prometheus-stack-prometheus 9090:9090 -n observability` and navigate to `http://localhost:9090/targets`. Verify the `fastapi-metrics` target in the `vici` namespace shows state=UP.
**Expected:** fastapi-metrics ServiceMonitor target shows UP with non-zero successful scrape count.
**Why human:** Requires Phase 5 FastAPI app to be deployed and exposing `/metrics`; runtime-only.

#### 3. Grafana Dashboard Provisioning

**Test:** Run `kubectl port-forward svc/kube-prometheus-stack-grafana 3000:80 -n observability`. Navigate to `http://localhost:3000/dashboards`. Verify both "FastAPI" and "Temporal Workflows" dashboards are visible and render panels (not blank/erroring).
**Expected:** Both dashboards visible and panels populated (Temporal panels may show no data until workloads run, but should not error).
**Why human:** Requires running Grafana + sidecar discovery in cluster.

#### 4. OTEL_EXPORTER_OTLP_ENDPOINT Secret Sync

**Test:** After `pulumi up` with ESO running and GCP Secret Manager populated, run `kubectl get secret otel-exporter-otlp-endpoint -n vici -o jsonpath='{.data.OTEL_EXPORTER_OTLP_ENDPOINT}' | base64 -d`.
**Expected:** Outputs `http://jaeger-collector.observability.svc.cluster.local:4317`.
**Why human:** Requires ESO running, GCP IAM Workload Identity bound, and GCP Secret Manager secret version populated by the operator.

#### 5. Temporal Dashboard Cached (Not Placeholder)

**Test:** After first `pulumi up` with network access, verify `grafana/provisioning/dashboards/temporal.json` exists on disk and contains actual Temporal SDK metrics panels (not the placeholder "TODO" text panel).
**Expected:** `cat grafana/provisioning/dashboards/temporal.json` outputs a valid Grafana dashboard JSON with Temporal-specific panel titles.
**Why human:** File is downloaded at runtime; source-only analysis cannot confirm download success.

---

### Gaps Summary

No blocking gaps were identified. All infrastructure code for OBS-02 through OBS-05 is present, syntactically valid, substantively implemented (not stubs), and wired into the Pulumi entry point.

The phase goal — "all application and infrastructure metrics, traces, and dashboards are operational" — is fully supported by the infrastructure code. Whether it is *actually* operational depends on `pulumi up` succeeding against a live cluster, which is inherently a runtime concern. Five human verification items capture the runtime behaviors that cannot be confirmed from source analysis alone.

The one notable operational risk is the absence of a pre-cached `temporal.json` in the repository. If `pulumi up` is run without internet access, Grafana will display a placeholder dashboard for Temporal rather than the real SDK metrics dashboard. This is accepted behavior per the plan design but should be confirmed as working after first deploy.

---

_Verified: 2026-04-05_
_Verifier: Claude (gsd-verifier)_
