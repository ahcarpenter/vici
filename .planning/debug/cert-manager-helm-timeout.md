---
status: diagnosed
trigger: "pulumi up --stack dev fails with cert-manager Helm release timing out on post-install and vici-app in CrashLoopBackOff. First-time deployment on this stack."
created: 2026-04-05T00:00:00Z
updated: 2026-04-05T00:10:00Z
---

## Current Focus
<!-- OVERWRITE on each update - reflects NOW -->

hypothesis: CONFIRMED - two independent root causes found
test: completed - live cluster evidence confirms both root causes
expecting: n/a - diagnosis complete
next_action: return structured findings

## Symptoms
<!-- Written during gathering, then IMMUTABLE -->

expected: cert-manager Helm release installs cleanly as part of the dev stack
actual: Two resources fail:
  1. cert-manager Helm release times out on post-install ("timed out waiting for the condition")
  2. vici-app Deployment enters CrashLoopBackOff (exit code 3)
  Additionally, there are 3 pending operations from a previous interrupted deployment.
errors:
  - kubernetes:helm.sh/v3:Release (cert-manager): "Helm release cert-manager/cert-manager-d160d62d was created, but failed to initialize completely. failed post-install: 1 error occurred: timed out waiting for the condition"
  - kubernetes:apps/v1:Deployment (vici-app): CrashLoopBackOff, exit code 3, container terminated at 2026-04-06T02:00:13Z
  - Warning: 3 pending operations from previous interrupted deployment (alembic-migration Job, jaeger-query Deployment, jaeger-collector Deployment)
reproduction: Run `pulumi up --stack dev` from infra/ directory
started: First time deploying this stack. Never worked before.

## Eliminated
<!-- APPEND only - prevents re-investigating -->

- hypothesis: cert-manager post-install timeout caused by webhook pod not starting in time (Autopilot node scale-up delay)
  evidence: webhook pod was Ready at 01:52:54; startupapicheck only launched at 01:53:00 - webhook was already up. The real cause is deeper in the cainjector.
  timestamp: 2026-04-05T00:07:00Z

- hypothesis: vici-app crash caused by missing K8s secrets (ExternalSecrets not synced)
  evidence: all 11 ExternalSecrets show STATUS=SecretSynced and READY=True; temporal-host secret exists and contains a value
  timestamp: 2026-04-05T00:07:00Z

- hypothesis: vici-app crash caused by cert-manager not being ready (dependency issue)
  evidence: app crash log shows a Pydantic validation error, not a connection error. The app starts, loads settings, then fails on startup due to missing env var - unrelated to cert-manager
  timestamp: 2026-04-05T00:07:00Z

## Evidence
<!-- APPEND only - facts discovered -->

- timestamp: 2026-04-05T00:02:00Z
  checked: infra/components/certmanager.py
  found: cert-manager v1.20.0 installed via Helm with crds.enabled=true; no extra args for leader election namespace; no override for startupapicheck wait duration
  implication: default leader election namespace (kube-system) is used by both controller and cainjector

- timestamp: 2026-04-05T00:02:00Z
  checked: infra/components/cluster.py
  found: GKE Autopilot cluster (enable_autopilot=True) in us-central1 on REGULAR release channel
  implication: Autopilot enforces GKE Warden security policies that restrict access to kube-system namespace

- timestamp: 2026-04-05T00:04:00Z
  checked: kubectl get pods -n cert-manager
  found: all 3 cert-manager pods (controller, cainjector, webhook) show Running/1/1 Ready
  implication: pods appear healthy from outside but are functionally broken internally

- timestamp: 2026-04-05T00:04:00Z
  checked: kubectl get events -n cert-manager
  found: startupapicheck job failed with BackoffLimitExceeded; ran cmctl check api --wait=1m and exited non-zero
  implication: post-install hook (startupapicheck) failed, causing Helm to report "timed out waiting for the condition"

- timestamp: 2026-04-05T00:05:00Z
  checked: kubectl logs cert-manager-d160d62d-cainjector (live)
  found: continuous errors every ~20s - "leases.coordination.k8s.io is forbidden: User cannot create resource 'leases' in kube-system: GKE Warden authz [denied by managed-namespaces-limitation]"
  implication: cainjector CANNOT acquire leader election lock because Autopilot blocks lease creation in kube-system; cainjector never becomes leader; never injects CA bundle into webhook ValidatingWebhookConfiguration

- timestamp: 2026-04-05T00:05:00Z
  checked: kubectl logs cert-manager-d160d62d controller pod (live)
  found: same kube-system lease creation forbidden error for "kube-system/cert-manager-controller"
  implication: cert-manager controller ALSO cannot acquire leader election; cert-manager is entirely non-functional despite pods showing Running

- timestamp: 2026-04-05T00:05:00Z
  checked: kubectl get validatingwebhookconfiguration cert-manager-d160d62d-webhook -o jsonpath caBundle
  found: CA bundle is empty (0 bytes) - cainjector has never successfully injected it
  implication: confirms cainjector has never functioned; webhook TLS cannot be validated; all cert-manager API calls fail with TLS handshake errors

- timestamp: 2026-04-05T00:06:00Z
  checked: vici-app container previous logs (kubectl logs --previous)
  found: Pydantic ValidationError at startup: "Required credentials are missing or empty: temporal_address, env"
  implication: the app crash is NOT related to cert-manager; it's a separate env var naming mismatch

- timestamp: 2026-04-05T00:06:00Z
  checked: kubectl get secret temporal-host -n vici (decoded)
  found: secret key is TEMPORAL_HOST; contains value "temporal-frontend.temporal.svc.cluster.local:7233"
  implication: the K8s secret key is TEMPORAL_HOST but src/config.py Settings reads field temporal_address (maps to env var TEMPORAL_ADDRESS); the names do not match

- timestamp: 2026-04-05T00:06:00Z
  checked: infra/components/secrets.py - ExternalSecret definition for "temporal-host"
  found: secretKey set to "TEMPORAL_HOST" (derived from slug.upper().replace("-","_") = "TEMPORAL_HOST")
  implication: the ExternalSecret writes the secret under key TEMPORAL_HOST; the app expects TEMPORAL_ADDRESS; this is a permanent mismatch

- timestamp: 2026-04-05T00:07:00Z
  checked: src/config.py Settings model
  found: field declared as `temporal_address: str = ""` and validated in _validate_required_credentials; Pydantic reads env var TEMPORAL_ADDRESS for this field
  implication: the app will always crash on startup until either the secret key or the config field name is aligned

## Resolution

root_cause: |
  TWO independent root causes:

  ROOT CAUSE 1 - cert-manager post-install timeout (GKE Autopilot kube-system restriction):
  cert-manager's controller and cainjector both attempt to create leader election Lease objects
  in the kube-system namespace by default. GKE Autopilot enforces a Warden security policy
  ("managed-namespaces-limitation") that denies creating resources in kube-system for user
  workloads. Both components are permanently stuck in a leader election retry loop every ~20s.
  Because cainjector never acquires the leader lease, it never runs its controller loop, and
  therefore never injects the CA bundle into the cert-manager ValidatingWebhookConfiguration.
  Without the CA bundle, the cert-manager webhook API is not functional (TLS handshake errors).
  The post-install hook (startupapicheck) runs `cmctl check api --wait=1m`, which calls the
  cert-manager webhook API. Since the webhook is non-functional, this check times out after
  1 minute and exits non-zero, causing Helm to report the post-install hook as failed.

  ROOT CAUSE 2 - vici-app CrashLoopBackOff (env var key name mismatch):
  The ExternalSecret for "temporal-host" generates a K8s Secret with key TEMPORAL_HOST
  (derived from the slug via `.upper().replace("-","_")`). The app's Settings model in
  src/config.py declares the field as `temporal_address`, which Pydantic reads from the
  environment variable TEMPORAL_ADDRESS. These names do not match. The app loads the
  TEMPORAL_HOST env var as an unknown/ignored field and sees TEMPORAL_ADDRESS as empty,
  triggering the fail-fast validator: "Required credentials are missing or empty: temporal_address, env".
  Exit code 3 = Python process exit due to unhandled startup exception.
  The "env" field is also missing because there is no K8s secret providing an ENV variable,
  though this may self-resolve if the ExternalSecret slug or env injection is added.

fix: |
  FIX 1 - cert-manager (infra/components/certmanager.py):
  Add extraArgs to both the controller and cainjector to use cert-manager namespace
  for leader election instead of kube-system:
    values={
        "crds": {"enabled": True},
        "extraArgs": ["--leader-election-namespace=cert-manager"],
        "cainjector": {
            "extraArgs": ["--leader-election-namespace=cert-manager"]
        },
    }
  This is the canonical fix for cert-manager on GKE Autopilot documented by cert-manager team.

  FIX 2 - temporal-host secret key mismatch (two options):
  Option A (fix the secret key in infra/components/secrets.py): Override the secretKey
  for temporal-host to emit TEMPORAL_ADDRESS instead of TEMPORAL_HOST. Requires changing
  the per-secret key derivation logic to handle this special case.
  Option B (fix the app config in src/config.py): Rename the Settings field from
  `temporal_address` to `temporal_host` so it reads TEMPORAL_HOST from env.
  This would also require updating all references to settings.temporal_address in src/.
  Option A is lower risk (no app code changes needed); Option B requires tracing all usages.

  FIX 3 - "env" missing from app settings:
  The Settings.env field is also flagged missing. There is no K8s secret providing ENV.
  The app needs an ENV environment variable. Either add it as a plain ConfigMap env var
  in app.py, or add it to the ExternalSecret definitions. Likely a configmap with env: dev
  injected via envFrom or env in the app Deployment.

verification:
  cert-manager: after applying fix, startupapicheck job should complete successfully (exit 0)
    and kubectl get validatingwebhookconfiguration should show a non-empty caBundle.
  vici-app: after fixing temporal-host key or renaming config field, app should start and
    kubectl logs should show "Application startup complete" without ValidationError.

files_changed:
  - infra/components/certmanager.py (add extraArgs for leader-election-namespace)
  - infra/components/secrets.py or src/config.py (resolve TEMPORAL_HOST vs TEMPORAL_ADDRESS mismatch)
  - infra/components/app.py (add ENV env var injection to Deployment)
