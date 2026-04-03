from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from src.config import Settings, get_settings
from src.main import _configure_otel


@pytest.fixture
def mock_app():
    return MagicMock()


def test_configure_otel_uses_always_on_sampler(mock_app):
    with patch("src.main.OTLPSpanExporter"), patch("src.main.FastAPIInstrumentor"), \
         patch("src.main.SQLAlchemyInstrumentor"), patch("src.main.get_engine"):
        provider = _configure_otel(mock_app)
    assert provider.sampler is ALWAYS_ON


def test_configure_otel_resource_has_deployment_environment(mock_app):
    with patch("src.main.OTLPSpanExporter"), patch("src.main.FastAPIInstrumentor"), \
         patch("src.main.SQLAlchemyInstrumentor"), patch("src.main.get_engine"):
        provider = _configure_otel(mock_app)
    attrs = provider.resource.attributes
    assert "deployment.environment" in attrs
    assert "service.version" in attrs


def test_configure_otel_deployment_environment_reflects_env_setting(mock_app):
    with patch("src.main.OTLPSpanExporter"), patch("src.main.FastAPIInstrumentor"), \
         patch("src.main.SQLAlchemyInstrumentor"), patch("src.main.get_engine"):
        provider = _configure_otel(mock_app)
    settings = get_settings()
    expected_env = (
        "development" if settings.env != "production" else "production"
    )
    assert provider.resource.attributes["deployment.environment"] == expected_env


def test_configure_otel_service_version_from_settings(mock_app):
    with patch("src.main.OTLPSpanExporter"), patch("src.main.FastAPIInstrumentor"), \
         patch("src.main.SQLAlchemyInstrumentor"), patch("src.main.get_engine"):
        provider = _configure_otel(mock_app)
    settings = get_settings()
    assert provider.resource.attributes["service.version"] == settings.observability.service_version


def test_observability_settings_service_version_from_git_sha():
    s = Settings(git_sha="abc123")
    assert s.observability.service_version == "abc123"


def test_observability_settings_service_version_defaults_to_dev():
    s = Settings()
    # Without GIT_SHA env var set, defaults to "dev"
    assert s.observability.service_version == "dev"
