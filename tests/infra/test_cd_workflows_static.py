"""Static assertions for Phase 5.1 CD workflow files.

These tests parse the GitHub Actions YAML files directly (via yaml.safe_load)
to verify that workflow definitions satisfy CD-01 through CD-05 requirements
without requiring a live GitHub Actions run.

Tests in CD-01 through CD-04 and TestCDBaseStructure will FAIL until Plan 02
rewrites the workflow files. TestCD05CIUnchanged passes immediately (ci.yml
already has no GCP steps).
"""

import pathlib

import pytest
import yaml

WORKFLOWS_DIR = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_workflow(filename: str) -> dict:
    path = WORKFLOWS_DIR / filename
    assert path.exists(), f"Expected workflow file {path} to exist"
    return yaml.safe_load(path.read_text())


def _all_steps(workflow: dict, job_name: str) -> list[dict]:
    """Return all steps for a given job name."""
    jobs = workflow.get("jobs", {})
    job = jobs.get(job_name, {})
    return job.get("steps", [])


# ---------------------------------------------------------------------------
# CD-01: Dev auto-deploy on push to main
# ---------------------------------------------------------------------------


class TestCD01DevAutoDeployOnMain:
    """Verify cd-dev.yml triggers on push to main and calls cd-base.yml with up."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.workflow = _load_workflow("cd-dev.yml")

    def test_cd_dev_triggers_on_push_to_main(self) -> None:
        on = self.workflow.get("on", {})
        branches = on.get("push", {}).get("branches", [])
        assert "main" in branches, (
            f"cd-dev.yml must trigger on push to 'main', found branches: {branches}"
        )

    def test_cd_dev_calls_cd_base_with_up(self) -> None:
        jobs = self.workflow.get("jobs", {})
        assert jobs, "cd-dev.yml must define at least one job"
        job = next(iter(jobs.values()))
        uses = job.get("uses", "")
        assert uses == "./.github/workflows/cd-base.yml", (
            f"cd-dev.yml job must use ./.github/workflows/cd-base.yml, got: {uses}"
        )
        with_args = job.get("with", {})
        assert with_args.get("command") == "up", (
            f"cd-dev.yml must pass command: up, got: {with_args.get('command')}"
        )
        assert with_args.get("stack") == "dev", (
            f"cd-dev.yml must pass stack: dev, got: {with_args.get('stack')}"
        )


# ---------------------------------------------------------------------------
# CD-02: Staging manual dispatch only
# ---------------------------------------------------------------------------


class TestCD02StagingManualDispatchOnly:
    """Verify cd-staging.yml only triggers on workflow_dispatch (no pull_request)."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.workflow = _load_workflow("cd-staging.yml")

    def test_cd_staging_triggers_on_workflow_dispatch_only(self) -> None:
        on = self.workflow.get("on", {})
        assert "workflow_dispatch" in on, (
            "cd-staging.yml must have workflow_dispatch trigger"
        )
        assert "pull_request" not in on, (
            "cd-staging.yml must NOT have pull_request trigger (D-05: manual dispatch only)"
        )

    def test_cd_staging_calls_cd_base_with_up(self) -> None:
        jobs = self.workflow.get("jobs", {})
        assert jobs, "cd-staging.yml must define at least one job"
        job = next(iter(jobs.values()))
        uses = job.get("uses", "")
        assert uses == "./.github/workflows/cd-base.yml", (
            f"cd-staging.yml job must use ./.github/workflows/cd-base.yml, got: {uses}"
        )
        with_args = job.get("with", {})
        assert with_args.get("command") == "up", (
            f"cd-staging.yml must pass command: up, got: {with_args.get('command')}"
        )
        assert with_args.get("stack") == "staging", (
            f"cd-staging.yml must pass stack: staging, got: {with_args.get('stack')}"
        )


# ---------------------------------------------------------------------------
# CD-03: Prod environment approval gate
# ---------------------------------------------------------------------------


class TestCD03ProdEnvironmentApproval:
    """Verify cd-prod.yml triggers on workflow_dispatch and passes environment: prod."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.workflow = _load_workflow("cd-prod.yml")

    def test_cd_prod_triggers_on_workflow_dispatch(self) -> None:
        on = self.workflow.get("on", {})
        assert "workflow_dispatch" in on, (
            "cd-prod.yml must have workflow_dispatch trigger"
        )

    def test_cd_prod_passes_environment_prod(self) -> None:
        jobs = self.workflow.get("jobs", {})
        assert jobs, "cd-prod.yml must define at least one job"
        job = next(iter(jobs.values()))
        with_args = job.get("with", {})
        assert with_args.get("environment") == "prod", (
            f"cd-prod.yml must pass with.environment: prod, got: {with_args.get('environment')}"
        )


# ---------------------------------------------------------------------------
# CD-04: Workload Identity Federation auth (no static keys)
# ---------------------------------------------------------------------------


class TestCD04WIFAuth:
    """Verify cd-base.yml uses WIF auth in both jobs with no static credential steps."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.workflow = _load_workflow("cd-base.yml")

    def test_cd_base_build_job_uses_wif_auth(self) -> None:
        steps = _all_steps(self.workflow, "build")
        uses_values = [s.get("uses", "") for s in steps]
        assert any("google-github-actions/auth@v3" in u for u in uses_values), (
            f"cd-base.yml build job must have a step using google-github-actions/auth@v3, "
            f"found: {uses_values}"
        )

    def test_cd_base_deploy_job_uses_wif_auth(self) -> None:
        steps = _all_steps(self.workflow, "deploy")
        uses_values = [s.get("uses", "") for s in steps]
        assert any("google-github-actions/auth@v3" in u for u in uses_values), (
            f"cd-base.yml deploy job must have a step using google-github-actions/auth@v3, "
            f"found: {uses_values}"
        )

    def test_cd_base_no_static_key_steps(self) -> None:
        """Neither build nor deploy job may reference static service account keys."""
        for job_name in ("build", "deploy"):
            steps = _all_steps(self.workflow, job_name)
            for step in steps:
                run_text = step.get("run", "") or ""
                env_text = str(step.get("env", "") or "")
                full_text = run_text + env_text
                assert "GOOGLE_APPLICATION_CREDENTIALS" not in full_text, (
                    f"cd-base.yml {job_name} job must not use "
                    f"GOOGLE_APPLICATION_CREDENTIALS (static key)"
                )
                assert "gcloud auth activate-service-account" not in full_text, (
                    f"cd-base.yml {job_name} job must not use "
                    f"gcloud auth activate-service-account (static key)"
                )

    def test_cd_base_has_id_token_write_permission(self) -> None:
        """Both build and deploy jobs must have permissions.id-token: write (WIF requirement)."""
        jobs = self.workflow.get("jobs", {})
        for job_name in ("build", "deploy"):
            job = jobs.get(job_name, {})
            permissions = job.get("permissions", {})
            id_token_perm = permissions.get("id-token", "")
            assert id_token_perm == "write", (
                f"cd-base.yml {job_name} job must have permissions.id-token: write, "
                f"got: {id_token_perm!r}"
            )


# ---------------------------------------------------------------------------
# CD-05: CI workflow unchanged (no GCP steps)
# ---------------------------------------------------------------------------


class TestCD05CIUnchanged:
    """Verify ci.yml has no GCP auth steps (CD-05: CI must be independent of GCP)."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.workflow = _load_workflow("ci.yml")

    def test_ci_yml_has_no_gcp_auth_steps(self) -> None:
        """ci.yml must not contain any google-github-actions steps or gcloud calls."""
        jobs = self.workflow.get("jobs", {})
        for job_name, job in jobs.items():
            steps = job.get("steps", [])
            for step in steps:
                uses = step.get("uses", "") or ""
                run = step.get("run", "") or ""
                assert "google-github-actions" not in uses, (
                    f"ci.yml job '{job_name}' step uses google-github-actions: {uses!r}"
                )
                assert "gcloud" not in run, (
                    f"ci.yml job '{job_name}' step run contains gcloud: {run!r}"
                )


# ---------------------------------------------------------------------------
# TestCDBaseStructure: Structural invariants for cd-base.yml
# ---------------------------------------------------------------------------


class TestCDBaseStructure:
    """Verify the structural shape of cd-base.yml per D-01 through D-08."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.workflow = _load_workflow("cd-base.yml")

    def test_cd_base_has_two_jobs(self) -> None:
        jobs = self.workflow.get("jobs", {})
        job_keys = list(jobs.keys())
        assert set(job_keys) == {"build", "deploy"}, (
            f"cd-base.yml must have exactly two jobs: build and deploy, got: {job_keys}"
        )

    def test_cd_base_deploy_needs_build(self) -> None:
        deploy_job = self.workflow.get("jobs", {}).get("deploy", {})
        needs = deploy_job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        assert "build" in needs, (
            f"cd-base.yml deploy job must list 'build' in needs, got: {needs}"
        )

    def test_cd_base_build_outputs_sha(self) -> None:
        build_job = self.workflow.get("jobs", {}).get("build", {})
        outputs = build_job.get("outputs", {})
        assert "sha" in outputs, (
            f"cd-base.yml build job must define outputs.sha, got outputs: {outputs}"
        )

    def test_cd_base_uses_docker_buildx_cache(self) -> None:
        steps = _all_steps(self.workflow, "build")
        buildx_steps = [
            s for s in steps if "docker/build-push-action" in (s.get("uses", "") or "")
        ]
        assert buildx_steps, (
            "cd-base.yml build job must have a docker/build-push-action step"
        )
        step_with = buildx_steps[0].get("with", {})
        cache_from = step_with.get("cache-from", "")
        assert "type=gha" in str(cache_from), (
            f"docker/build-push-action must use cache-from: type=gha, got: {cache_from!r}"
        )

    def test_cd_base_build_only_pushes_on_up(self) -> None:
        steps = _all_steps(self.workflow, "build")
        buildx_steps = [
            s for s in steps if "docker/build-push-action" in (s.get("uses", "") or "")
        ]
        assert buildx_steps, "cd-base.yml build job must have a docker/build-push-action step"
        step_if = buildx_steps[0].get("if", "") or ""
        assert "inputs.command == 'up'" in step_if or 'inputs.command == "up"' in step_if, (
            f"docker/build-push-action must have if: inputs.command == 'up', got: {step_if!r}"
        )

    def test_cd_base_has_gcp_project_input(self) -> None:
        inputs = (
            self.workflow.get("on", {})
            .get("workflow_call", {})
            .get("inputs", {})
        )
        assert "gcp_project" in inputs, (
            f"cd-base.yml workflow_call inputs must include gcp_project, got: {list(inputs.keys())}"
        )
        assert inputs["gcp_project"].get("required") is True, (
            "cd-base.yml gcp_project input must be required: true"
        )

    def test_cd_base_health_check_on_dev_up(self) -> None:
        steps = _all_steps(self.workflow, "deploy")
        health_steps = [
            s for s in steps
            if s.get("if") and "inputs.stack == 'dev'" in (s.get("if", "") or "")
            and "inputs.command == 'up'" in (s.get("if", "") or "")
        ]
        assert health_steps, (
            "cd-base.yml deploy job must have a step with "
            "if: inputs.stack == 'dev' and inputs.command == 'up'"
        )
        run_text = health_steps[0].get("run", "") or ""
        assert "curl" in run_text, (
            f"Health check step must use curl, got run: {run_text!r}"
        )
        assert "/health" in run_text, (
            f"Health check step must target /health endpoint, got run: {run_text!r}"
        )

    def test_cd_base_uses_pulumi_config_map_for_image_tag(self) -> None:
        steps = _all_steps(self.workflow, "deploy")
        pulumi_steps = [
            s for s in steps if "pulumi/actions" in (s.get("uses", "") or "")
        ]
        assert pulumi_steps, (
            "cd-base.yml deploy job must have a pulumi/actions step"
        )
        step_with = pulumi_steps[0].get("with", {})
        config_map = str(step_with.get("config-map", "") or "")
        assert "imageTag" in config_map, (
            f"pulumi/actions step must pass config-map containing imageTag, "
            f"got: {config_map!r}"
        )
