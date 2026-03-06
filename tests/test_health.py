import pytest


async def test_health_endpoint(client):
    """GET /health returns 200 with status field."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")


@pytest.mark.skip(reason="implemented in plan 03")
async def test_metrics_endpoint(client):
    """GET /metrics returns 200, body starts with '# HELP'."""
    pass
