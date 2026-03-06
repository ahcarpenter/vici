import pytest


@pytest.mark.skip(reason="implemented in plan 02")
async def test_invalid_signature(client):
    """POST /webhook/sms with invalid X-Twilio-Signature returns 403."""
    pass


@pytest.mark.skip(reason="implemented in plan 02")
async def test_valid_signature(client, mock_twilio_validator):
    """POST /webhook/sms with valid signature returns 200."""
    pass


@pytest.mark.skip(reason="implemented in plan 02")
async def test_idempotency(client, mock_twilio_validator):
    """Second POST with same MessageSid returns 200 with empty TwiML, no duplicate DB row."""
    pass


@pytest.mark.skip(reason="implemented in plan 02")
async def test_rate_limit(client, mock_twilio_validator):
    """6th message from same phone within 60 seconds returns 200 with empty TwiML body."""
    pass


@pytest.mark.skip(reason="implemented in plan 02")
async def test_audit_row_created(client, mock_twilio_validator, async_session):
    """Valid POST creates row in audit_log table."""
    pass


@pytest.mark.skip(reason="implemented in plan 02")
async def test_phone_auto_register(client, mock_twilio_validator, async_session):
    """First message from phone creates row in phone table."""
    pass


@pytest.mark.skip(reason="implemented in plan 02")
async def test_phone_created_at(client, mock_twilio_validator, async_session):
    """Phone row has non-null created_at timestamp."""
    pass


@pytest.mark.skip(reason="implemented in plan 02")
async def test_inngest_event_emitted(client, mock_twilio_validator, mock_inngest_client):
    """Valid POST calls inngest_client.send with event name 'message.received'."""
    pass
