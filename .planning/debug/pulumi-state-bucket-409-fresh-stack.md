---
status: diagnosed
trigger: "pulumi up --stack dev fails with GCS Error 409 on gcp:storage:Bucket (pulumi-state-bucket) during Phase 05 UAT"
created: 2026-04-11T20:00:00Z
updated: 2026-04-11T20:45:00Z
---

## Current Focus

hypothesis: The user ran `pulumi up --stack dev` from a Phase 06 branch / worktree that contains `infra/components/state_bucket.py`; that module declares the GCS state bucket as a Pulumi-managed resource but the bucket already exists (it IS the Pulumi backend) and has never been imported into stack state, so Pulumi attempts to CREATE it and fails with GCS 409.
test: Audit git history for `state_bucket.py`, check if it exists at HEAD of the Phase 05 UAT branch (306f1c5), check if it is wired into `__main__.py`, and confirm that the import prerequisite is documented but not automated.
expecting: Confirmation that (a) `state_bucket.py` exists on the Phase 06 branch, (b) it is wired into `__main__.py` only on Phase 06, (c) no pre-flight guard or bootstrap script runs `pulumi import` automatically, and (d) the import prerequisite lives only in module docstrings and `OPERATIONS.md` — not in any onboarding README or code path.
next_action: Write ROOT CAUSE FOUND summary and return to caller. Do not apply fixes.

## Symptoms

expected: `pulumi up --stack dev` completes successfully, allowing Phase 5 deployment to proceed end-to-end (31 existing resources unchanged, 2 new resources created cleanly).
actual: |
  gcp:storage:Bucket (pulumi-state-bucket):
      error: googleapi: Error 409: The requested bucket name is not available.
      The bucket namespace is shared by all users of the system.
      Please select a different name and try again., conflict:
      provider=google-beta@9.18.0
  Resources:
      + 2 created
      31 unchanged
      2 errored
  Duration: 14s
errors: "googleapi: Error 409: The requested bucket name is not available. The bucket namespace is shared by all users of the system."
reproduction: |
  1. Checkout a branch that includes infra/components/state_bucket.py AND the __main__.py import of it (Phase 06 work, e.g. gsd/v1.0-milestone tip 09a765c or commit 26b95de onward).
  2. cd infra
  3. pulumi stack select dev (stack has pre-existing state with 31 resources and a live cluster)
  4. Do NOT run `pulumi import gcp:storage/bucket:Bucket pulumi-state-bucket vici-app-pulumi-state-dev`
  5. pulumi up
  Result: GCS 409 because Pulumi has no state record of the bucket and issues a CREATE for a name that is already taken (by the user's own pre-existing backend bucket).
started: "Introduced by commit 64505e7 (feat(06-01): add protect=True to stateful resources and create state_bucket.py) on 2026-04-11 17:42 EDT. Became active on first `pulumi up` after commit 26b95de (feat(06-04): wire network_policy, pdb, and state_bucket into __main__.py) on 2026-04-11 17:58 EDT."

## Eliminated

- hypothesis: "The `dev` stack state was rehydrated/reset, causing Pulumi to forget the bucket was imported."
  evidence: "Not reset — the stack has 31 unchanged resources and live outputs (cluster_endpoint, ingress_external_ip). State is intact. The 409 is because the bucket was never in state to begin with — no prior `pulumi import` was ever run for this resource."
  timestamp: 2026-04-11T20:30:00Z

- hypothesis: "`state_bucket.py` was added to the main Phase 05 branch and broke an already-passing Phase 05 UAT."
  evidence: "Phase 05 UAT branch HEAD is 306f1c5. At that commit, `ls infra/components/` contains NO state_bucket.py, and `git show HEAD:infra/__main__.py` contains no state_bucket import. The file lives exclusively on the Phase 06 line: commit 64505e7 creates it, commit 26b95de wires it into __main__.py. Neither commit is in 306f1c5's ancestry. The operator must have run `pulumi up` from a Phase 06 branch/worktree (gsd/v1.0-milestone, currently at 09a765c) while the UAT file was being updated on the Phase 05 branch."
  timestamp: 2026-04-11T20:35:00Z

## Evidence

- timestamp: 2026-04-11T20:10:00Z
  checked: "`ls infra/components/` in working tree (agent-ab33e9b2 worktree on gsd/v1.0-milestone @ 306f1c5)"
  found: "No state_bucket.py in working tree. Files present: __init__.py, app.py, cd.py, certmanager.py, cluster.py, database.py, iam.py, identity.py, ingress.py, jaeger.py, migration.py, namespaces.py, opensearch.py, prometheus.py, registry.py, secrets.py, temporal.py."
  implication: "The HEAD commit of this worktree does NOT include the file the hypothesis references. The file must live on a different commit lineage."

- timestamp: 2026-04-11T20:12:00Z
  checked: "`git log --all --oneline -- infra/components/state_bucket.py`"
  found: |
    cb90d48 feat(06-02): add per-namespace traffic allow rules to network_policy.py
    d97fff4 feat(06-02): create network_policy.py with default-deny and DNS-allow for all 5 namespaces
    64505e7 feat(06-01): add protect=True to stateful resources and create state_bucket.py
  implication: "state_bucket.py was created in commit 64505e7 (Phase 06-01) and is only touched by commits on the Phase 06 line. It has never been modified since creation — one version exists."

- timestamp: 2026-04-11T20:14:00Z
  checked: "`git show 64505e7 --stat`"
  found: |
    feat(06-01): add protect=True to stateful resources and create state_bucket.py
      infra/components/cluster.py      |  1 +
      infra/components/database.py     |  4 ++--
      infra/components/registry.py     |  2 ++
      infra/components/state_bucket.py | 31 +++++++++++++++++++++++++++++++
      4 files changed, 36 insertions(+), 2 deletions(-)
  implication: "Phase 06-01 added protect=True to already-existing stateful resources (cluster, databases, registry) AND created a new state_bucket.py. The cluster/database/registry changes are benign (protect is state-only), but state_bucket.py introduces a brand-new resource declaration for a bucket that already exists."

- timestamp: 2026-04-11T20:16:00Z
  checked: "Contents of `infra/components/state_bucket.py` (from `git show 64505e7:infra/components/state_bucket.py`)"
  found: |
    state_bucket = gcp.storage.Bucket(
        "pulumi-state-bucket",
        name=f"vici-app-pulumi-state-{ENV}",
        project=PROJECT_ID,
        location="US",
        opts=ResourceOptions(
            protect=True,
            retain_on_delete=True,
        ),
    )
    
    Module docstring explicitly warns:
    "The bucket is the Pulumi backend itself. It was NOT originally created by Pulumi.
    To manage it, run the import command once per stack:
        pulumi import gcp:storage/bucket:Bucket pulumi-state-bucket vici-app-pulumi-state-{env}"
  implication: "Author was fully aware this module requires a one-time `pulumi import` before `pulumi up`. The warning is in the file docstring only — nothing in code enforces it, checks for it, or runs it automatically. An operator who does not read the docstring hits GCS 409."

- timestamp: 2026-04-11T20:18:00Z
  checked: "`git show 26b95de` — the commit that imports state_bucket into __main__.py"
  found: |
    feat(06-04): wire network_policy, pdb, and state_bucket into __main__.py
    
    +from components.network_policy import default_deny_policies  # noqa: F401
    +from components.pdb import pdbs  # noqa: F401
    +from components.state_bucket import state_bucket  # noqa: F401
    
    Date: 2026-04-11 17:58:39 -0400
  implication: "state_bucket.py was created on 2026-04-11 17:42 (commit 64505e7) but was not wired into __main__.py until commit 26b95de on 2026-04-11 17:58 — a 16-minute gap. `pulumi up` only registers the resource AFTER 26b95de is applied. The first `pulumi up` on any stack after 26b95de will hit 409 unless `pulumi import` has been run."

- timestamp: 2026-04-11T20:22:00Z
  checked: "`git show HEAD:infra/__main__.py` at 306f1c5 (Phase 05 UAT branch)"
  found: "No state_bucket, network_policy, or pdb imports. Only the original 18 component imports. Phase 05 UAT HEAD does not import state_bucket.py — the file does not exist at this commit either."
  implication: "The 409 error reported in 05-HUMAN-UAT.md Test 2 could NOT have come from running Phase 05 HEAD (306f1c5). The operator must have been working from a Phase 06 checkout (gsd/v1.0-milestone, currently at 09a765c) at the time they ran `pulumi up --stack dev`. Likely they updated the Phase 05 UAT file to record the issue while the working directory was on a different branch that had Phase 06 changes applied."

- timestamp: 2026-04-11T20:26:00Z
  checked: "`infra/OPERATIONS.md` (Phase 06 tip 09a765c, not present at Phase 05 HEAD)"
  found: |
    ### First-Time Setup Commands
    
    # 1. Select stack
    cd infra
    pulumi stack select dev
    
    # 2. Import GCS state bucket (one-time per stack)
    pulumi import gcp:storage/bucket:Bucket pulumi-state-bucket vici-app-pulumi-state-{env}
    
    # 3. Provision everything
    pulumi up
  implication: "The import step IS documented in OPERATIONS.md (Phase 06 commit 4fe599f). BUT: (1) the file only exists on the Phase 06 branch, (2) it is not referenced from any README or onboarding doc surfaced by the repo root, (3) there is no pre-flight script or Makefile target that executes it, and (4) nothing in the Pulumi program itself checks whether the import has been run."

- timestamp: 2026-04-11T20:30:00Z
  checked: "`git ls-tree HEAD -- infra/` — does OPERATIONS.md exist at Phase 05 UAT HEAD?"
  found: "No OPERATIONS.md at 306f1c5. Files at Phase 05 HEAD infra/: DOMAIN-SETUP.md, Pulumi.{dev,prod,staging}.yaml, Pulumi.yaml, __main__.py, components/, config.py, requirements.txt."
  implication: "Neither the state_bucket.py file nor the OPERATIONS.md documentation exist at the Phase 05 HEAD. The UAT report is recording a symptom observed on a checkout of a DIFFERENT branch than the Phase 05 UAT branch. The operator has effectively reported a Phase 06 regression while running Phase 05 UAT."

- timestamp: 2026-04-11T20:34:00Z
  checked: "Second errored resource in `pulumi up` output (user reported '2 errored' but only captured 1 error line)"
  found: "Cannot determine from evidence provided. The state_bucket resource has no Pulumi dependents, so a cascade is unlikely. The most likely candidates for the second error are: (1) network_policy.py resources also introduced by Phase 06 that could fail if kube-dns selector matching is wrong on Autopilot, (2) pdb.py resources (but dev env skips PDB creation, so not this), or (3) an unrelated flake (e.g., provider throttling) that is orthogonal to the state bucket issue."
  implication: "The prompt asks whether the second error is cascade-related. Based on declared dependencies, no — state_bucket has no downstream. The second resource is more likely to be an independent Phase 06 addition (network_policy most plausible) or an unrelated transient. Investigator cannot confirm without the full `pulumi up` output."

- timestamp: 2026-04-11T20:38:00Z
  checked: "Knowledge base at .planning/debug/knowledge-base.md for prior `pulumi-state-bucket` or `409` entries"
  found: "Two entries exist (pinecone-sync-queue-description-column-missing, sms-webhook-signature-403). Neither matches this symptom. No prior state-bucket 409 entry."
  implication: "This is a new failure mode. Archive this session to knowledge base once resolved so future `pulumi up` on a new stack immediately surfaces the hypothesis."

## Resolution

root_cause: |
  `infra/components/state_bucket.py` (introduced in commit 64505e7, Phase 06-01) declares `vici-app-pulumi-state-{ENV}` as a Pulumi-managed `gcp.storage.Bucket` resource. Commit 26b95de (Phase 06-04) wires it into `infra/__main__.py` as a side-effect import. The declared bucket is the Pulumi backend itself — it already exists and was created out-of-band, NOT by Pulumi — and therefore has no record in stack state. On every first `pulumi up` after 26b95de against any stack (dev, staging, prod), Pulumi sees an unregistered resource and issues a CREATE request, which GCS rejects with `Error 409: The requested bucket name is not available` because the globally-unique bucket name is already owned by the operator's own pre-existing backend bucket.
  
  The prerequisite fix — running `pulumi import gcp:storage/bucket:Bucket pulumi-state-bucket vici-app-pulumi-state-{env}` once per stack — is documented in:
    1. The `state_bucket.py` module docstring (infra/components/state_bucket.py:1-15)
    2. `infra/OPERATIONS.md` (Phase 06 only) under "First-Time Setup Commands"
  
  Neither of these is surfaced by any pre-flight guard, README onboarding step, bootstrap script, Makefile target, or Pulumi-level hook. Any operator running a fresh `pulumi up` on a Phase 06 checkout without having read the module docstring or OPERATIONS.md hits this 409 deterministically.
  
  Secondary confound: The UAT report file (.planning/workstreams/gks-refactor/phases/05-application-deployment-and-ci-cd/05-HUMAN-UAT.md) is on the Phase 05 branch (HEAD 306f1c5) which does NOT contain state_bucket.py at all. The operator must have been running `pulumi up` from a Phase 06 checkout (gsd/v1.0-milestone, currently at 09a765c) while recording the failure as a Phase 05 UAT issue. This is a cross-branch reporting artifact — the bug itself is a Phase 06 regression, not a Phase 05 issue.

fix: "(diagnose-only mode — no fix applied)"
verification: "(diagnose-only mode — not verified)"
files_changed: []

## Suggested Fix Direction (for planner, not applied)

Three tiers of remediation, ranked by robustness:

1. **Refactor state_bucket.py to use `gcp.storage.get_bucket()` (strongest).**
   Replace the `gcp.storage.Bucket(...)` resource declaration with a `gcp.storage.get_bucket(...)` lookup. This makes the module idempotent — it reads the existing bucket, confirms it exists, and attaches no create/update/delete semantics to Pulumi. The `protect=True` / `retain_on_delete=True` goal (prevent `pulumi destroy` from nuking the backend) can be enforced differently: document "never pulumi destroy the state bucket" in OPERATIONS.md and/or add a GCS lifecycle rule with object versioning + bucket-level retention. Downside: loses the Pulumi-level protect guardrail. Upside: zero chance of 409, no import prerequisite, no state drift risk, safe for any operator on any fresh checkout.

2. **Add a bootstrap / pre-flight guard script.** Create `infra/bin/bootstrap-stack.sh` (or a Makefile target `make bootstrap-dev`) that runs `pulumi import` for the state bucket if not already in state. Gate first-run via `pulumi stack export | grep -q pulumi-state-bucket || pulumi import ...`. Document it as the one-command onboarding step in the repo root README. Downside: still requires operators to run the script; human error possible. Upside: preserves `protect=True` and retains the Pulumi-managed posture.

3. **Doc-only fix (weakest).** Add a prominent callout to the repo root `README.md` and `infra/README.md` (create it if missing) with the `pulumi import` command. Duplicate the `OPERATIONS.md` "First-Time Setup Commands" block prominently. Downside: operators still miss it; relies on humans reading docs; UAT proved this failure mode is real.

Recommendation: option 1 (refactor to `get_bucket`) — it removes the failure mode entirely and is consistent with the spirit of "the state bucket is bootstrap infrastructure that predates Pulumi." The `protect` semantics can be preserved via a bucket-level IAM/retention policy documented separately.

Secondary: regardless of which option is chosen, investigate the reported "2 errored" resource in the `pulumi up` output. The user's UAT excerpt captured only one error line. The second resource is NOT cascade-related to state_bucket (no declared dependents), so it is likely either a concurrent Phase 06 addition (most plausibly a `network_policy.py` resource) or an unrelated transient. Request the full `pulumi up` output before planning a fix, to avoid designing for one bug while a second remains hidden.

Tertiary: reconcile the cross-branch reporting artifact. The Phase 05 UAT file at 05-HUMAN-UAT.md records this failure, but the root cause is Phase 06 code that does not exist at Phase 05 HEAD. Either (a) move the UAT gap into the Phase 06 gap-tracking artifacts, or (b) re-run Phase 05 UAT Test 2 against the actual Phase 05 HEAD (306f1c5) to confirm whether Phase 05 itself has any outstanding issues beyond this Phase 06 regression.
