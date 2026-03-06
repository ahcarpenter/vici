import pytest


async def test_health_endpoint(client):
    """GET /health returns 200 with status field."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")


async def test_metrics_endpoint(client):
    """GET /metrics returns 200, body starts with '# HELP'."""
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "# HELP" in response.text
