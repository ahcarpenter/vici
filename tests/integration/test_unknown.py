"""
Integration test stubs for unknown message type end-to-end flow (implemented in plan 02.1-03).
"""
import pytest


@pytest.mark.skip("stub — implemented in plan 02.1-03")
def test_unknown_message_end_to_end():
    """SMS webhook → extraction → unknown branch → Twilio reply sent."""
    pass
