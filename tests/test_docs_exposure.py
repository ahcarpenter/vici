"""
Tests for F-07: API docs must be hidden in production (AGENTS.md convention).

Verifies `_docs_app_configs` builds the correct FastAPI(...) kwargs and, with
those kwargs applied at construction time, the /openapi.json, /docs, and
/redoc routes are actually absent in production. Setting those attributes
after __init__ does not unmount the routes, so this test has to construct
a real FastAPI with the kwargs.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.main import SHOW_DOCS_ENVIRONMENT, _docs_app_configs


class TestShowDocsEnvironmentConstant:
    def test_permitted_envs(self):
        assert SHOW_DOCS_ENVIRONMENT == ("local", "development", "staging")

    def test_production_excluded(self):
        assert "production" not in SHOW_DOCS_ENVIRONMENT


class TestDocsAppConfigsInProduction:
    def test_returns_none_kwargs_for_production(self):
        assert _docs_app_configs("production") == {
            "openapi_url": None,
            "docs_url": None,
            "redoc_url": None,
        }

    @pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
    def test_endpoint_returns_404_when_app_built_for_production(self, path):
        app = FastAPI(**_docs_app_configs("production"))
        client = TestClient(app)
        response = client.get(path)
        assert response.status_code == 404


class TestDocsAppConfigsInNonProductionEnvironments:
    @pytest.mark.parametrize("env", ["local", "development", "staging"])
    def test_returns_empty_kwargs(self, env):
        assert _docs_app_configs(env) == {}

    @pytest.mark.parametrize("env", ["local", "development", "staging"])
    def test_openapi_json_reachable(self, env):
        app = FastAPI(**_docs_app_configs(env))
        client = TestClient(app)
        response = client.get("/openapi.json")
        assert response.status_code == 200

    @pytest.mark.parametrize("env", ["local", "development", "staging"])
    def test_docs_reachable(self, env):
        app = FastAPI(**_docs_app_configs(env))
        client = TestClient(app)
        response = client.get("/docs")
        assert response.status_code == 200
