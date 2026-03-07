import json
from unittest.mock import patch

from httpx import AsyncClient
from sqlmodel import select
from twilio.request_validator import RequestValidator

from src.sms.models import AuditLog, Message
from src.users.models import User

VALID_FORM = {
    "MessageSid": "SM_test_001",
    "From": "+15005550006",
    "Body": "Test message",
    "AccountSid": "AC_test",
}

HEADERS = {"X-Twilio-Signature": "valid_sig"}


async def test_invalid_signature(client: AsyncClient):
    with patch(
        "twilio.request_validator.RequestValidator.validate",
        return_value=False,
    ):
        response = await client.post(
            "/webhook/sms",
            data=VALID_FORM,
            headers={"X-Twilio-Signature": "bad_sig"},
        )
    assert response.status_code == 403


async def test_valid_signature(client: AsyncClient, mock_twilio_validator):
    response = await client.post("/webhook/sms", data=VALID_FORM, headers=HEADERS)
    assert response.status_code == 200
    assert "text/xml" in response.headers["content-type"]
    assert "<Response" in response.text


async def test_valid_signature_real(client: AsyncClient):
    token = "test_twilio_auth_token"
    url = "http://localhost:8000/webhook/sms"
    sig = RequestValidator(token).compute_signature(url, VALID_FORM)
    response = await client.post(
        "/webhook/sms",
        data=VALID_FORM,
        headers={"X-Twilio-Signature": sig},
    )
    assert response.status_code == 200


async def test_idempotency(
    client: AsyncClient,
    mock_twilio_validator,
    async_session,
):
    form = {**VALID_FORM, "MessageSid": "SM_idem_001"}
    await client.post("/webhook/sms", data=form, headers=HEADERS)
    response = await client.post("/webhook/sms", data=form, headers=HEADERS)
    assert response.status_code == 200
    result = await async_session.execute(
        select(Message).where(Message.message_sid == "SM_idem_001")
    )
    rows = result.all()
    assert len(rows) == 1  # only one row, not two


async def test_rate_limit(client: AsyncClient, mock_twilio_validator):
    phone = "+15005550007"
    for i in range(5):
        form = {**VALID_FORM, "MessageSid": f"SM_rl_{i:03d}", "From": phone}
        await client.post("/webhook/sms", data=form, headers=HEADERS)
    # 6th message should be rate-limited
    form = {**VALID_FORM, "MessageSid": "SM_rl_005", "From": phone}
    response = await client.post("/webhook/sms", data=form, headers=HEADERS)
    assert response.status_code == 200
    assert "<Response" in response.text  # empty TwiML, not 429


async def test_audit_row_created(
    client: AsyncClient,
    mock_twilio_validator,
    async_session,
):
    form = {**VALID_FORM, "MessageSid": "SM_audit_001"}
    await client.post("/webhook/sms", data=form, headers=HEADERS)
    result = await async_session.execute(
        select(AuditLog).where(AuditLog.message_sid == "SM_audit_001")
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.event == "received"
    # SEC-04: detail must contain raw Twilio payload as JSON
    assert row.detail is not None
    detail = json.loads(row.detail)
    assert detail["MessageSid"] == "SM_audit_001"


async def test_phone_auto_register(
    client: AsyncClient,
    mock_twilio_validator,
    async_session,
):
    phone = "+15005550008"
    form = {**VALID_FORM, "MessageSid": "SM_phone_001", "From": phone}
    await client.post("/webhook/sms", data=form, headers=HEADERS)
    from src.sms.service import hash_phone
    ph = hash_phone(phone)
    result = await async_session.execute(
        select(User).where(User.phone_hash == ph)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.id is not None  # integer PK


async def test_phone_created_at(
    client: AsyncClient,
    mock_twilio_validator,
    async_session,
):
    phone = "+15005550009"
    form = {**VALID_FORM, "MessageSid": "SM_phone_002", "From": phone}
    await client.post("/webhook/sms", data=form, headers=HEADERS)
    from src.sms.service import hash_phone
    ph = hash_phone(phone)
    result = await async_session.execute(
        select(User).where(User.phone_hash == ph)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.created_at is not None


async def test_inngest_event_emitted(
    client: AsyncClient,
    mock_twilio_validator,
    mock_inngest_client,
):
    form = {**VALID_FORM, "MessageSid": "SM_inngest_001"}
    response = await client.post("/webhook/sms", data=form, headers=HEADERS)
    assert response.status_code == 200
    mock_inngest_client.assert_called_once()
    # Verify the event passed to send() has the right name and data
    call_args = mock_inngest_client.call_args
    event = call_args.args[0]  # first positional arg to send()
    assert event.name == "message.received"
    assert event.data["message_sid"] == "SM_inngest_001"
