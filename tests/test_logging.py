import pytest


@pytest.mark.skip(reason="implemented in plan 03")
async def test_trace_id_in_log(client):
    """Structured log output contains 'trace_id' key."""
    pass
