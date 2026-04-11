"""Static assertions for Phase 5.1 CD Pulumi infrastructure.

These tests parse the Pulumi Python source files directly (via AST and text
search) to verify that IMAGE_TAG config support is correctly implemented in
infra/config.py and consumed in infra/components/app.py.

Tests in this file will FAIL until Task 2 adds IMAGE_TAG to config.py and
updates app.py (RED state). After Task 2 they should all pass (GREEN).
"""

import ast
import pathlib

import pytest

INFRA_DIR = pathlib.Path(__file__).resolve().parents[2] / "infra"
COMPONENTS_DIR = INFRA_DIR / "components"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_source(path: pathlib.Path) -> str:
    assert path.exists(), f"Expected {path} to exist"
    return path.read_text()


def _parse_module_assignments(source: str) -> dict[str, ast.expr]:
    """Return a dict of top-level assignment targets to their value nodes."""
    tree = ast.parse(source)
    assignments: dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                assignments[node.target.id] = node.value
    return assignments


# ---------------------------------------------------------------------------
# TestImageTagConfig: config.py must export IMAGE_TAG with ENV fallback
# ---------------------------------------------------------------------------


class TestImageTagConfig:
    """Verify config.py exports IMAGE_TAG from cfg.get('imageTag') with ENV fallback."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.source = _read_source(INFRA_DIR / "config.py")

    def test_config_exports_image_tag(self) -> None:
        """config.py must have a module-level assignment to IMAGE_TAG."""
        assignments = _parse_module_assignments(self.source)
        assert "IMAGE_TAG" in assignments, (
            f"config.py must have a module-level IMAGE_TAG assignment. "
            f"Found assignments: {list(assignments.keys())}"
        )

    def test_config_image_tag_has_env_fallback(self) -> None:
        """IMAGE_TAG must be defined as cfg.get('imageTag') or ENV."""
        assert (
            'cfg.get("imageTag") or ENV' in self.source
            or "cfg.get('imageTag') or ENV" in self.source
        ), "config.py IMAGE_TAG must be defined as: cfg.get('imageTag') or ENV"


# ---------------------------------------------------------------------------
# TestAppUsesImageTag: app.py must import and use IMAGE_TAG (not ENV) for image
# ---------------------------------------------------------------------------


class TestAppUsesImageTag:
    """Verify app.py imports IMAGE_TAG from config and uses it as the image tag."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.source = _read_source(COMPONENTS_DIR / "app.py")

    def test_app_imports_image_tag(self) -> None:
        """app.py must import IMAGE_TAG from config."""
        lines = self.source.splitlines()
        import_lines = [line for line in lines if line.startswith("from config import")]
        assert import_lines, "app.py must have a 'from config import ...' line"
        combined = " ".join(import_lines)
        assert "IMAGE_TAG" in combined, (
            f"app.py 'from config import' line must include IMAGE_TAG. "
            f"Found import lines: {import_lines}"
        )

    def test_app_image_uses_image_tag_not_env(self) -> None:
        """The container image tag line must use IMAGE_TAG, not ENV."""
        lines = self.source.splitlines()
        image_tag_lines = [
            line for line in lines if "registry_url" in line and "/vici:" in line
        ]
        assert image_tag_lines, (
            "app.py must have a line referencing registry_url and '/vici:' "
            "(the container image definition)"
        )
        image_line = image_tag_lines[0]
        assert "IMAGE_TAG" in image_line, (
            f"Container image line must use IMAGE_TAG, not ENV. Found: {image_line!r}"
        )
        # Ensure it does NOT still use bare ENV as the tag
        assert not image_line.rstrip().endswith(", ENV)"), (
            f"Container image line must not end with ', ENV)'. Found: {image_line!r}"
        )
