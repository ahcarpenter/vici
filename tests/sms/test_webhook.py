import json
from unittest.mock import patch

from httpx import AsyncClient
from sqlmodel import select
from twilio.request_validator import RequestValidator

from src.config import get_settings
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
    with (
        patch("src.sms.dependencies.get_settings") as mock_settings,
        patch(
            "twilio.request_validator.RequestValidator.validate",
            return_value=False,
        ),
    ):
        mock_settings.return_value.env = "production"
        mock_settings.return_value.twilio_auth_token = "test_twilio_auth_token"
        mock_settings.return_value.webhook_base_url = "http://localhost:8000"
        mock_settings.return_value.sms.disable_twilio_signature_validation = False
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
    settings = get_settings()
    token = settings.sms.auth_token
    url = f"{settings.webhook_base_url}/webhook/sms"
    form = {**VALID_FORM, "MessageSid": "SM_real_001", "From": "+15005550010"}
    sig = RequestValidator(token).compute_signature(url, form)
    response = await client.post(
        "/webhook/sms",
        data=form,
        headers={"X-Twilio-Signature": sig},
    )
    assert response.status_code == 200


async def test_idempotency(
    client: AsyncClient,
    mock_twilio_validator,
    async_session,
):
    form = {**VALID_FORM, "MessageSid": "SM_idem_001", "From": "+15005550011"}
    await client.post("/webhook/sms", data=form, headers=HEADERS)
    response = await client.post("/webhook/sms", data=form, headers=HEADERS)
    assert response.status_code == 200
    result = await async_session.execute(
        select(Message).where(Message.message_sid == "SM_idem_001")
    )
    rows = result.all()
    assert len(rows) == 1  # only one row, not two


async def test_rate_limit(client: AsyncClient, mock_twilio_validator):
    phone = "+15005550020"
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
    result = await async_session.execute(select(User).where(User.phone_hash == ph))
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
    result = await async_session.execute(select(User).where(User.phone_hash == ph))
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.created_at is not None


async def test_audit_detail_scrubs_phone_pii(
    client: AsyncClient,
    mock_twilio_validator,
    async_session,
):
    """F-04: audit_log.detail must not contain raw E.164 numbers (GDPR/CCPA)."""
    from src.sms.service import hash_phone

    phone = "+15005550042"
    form = {**VALID_FORM, "MessageSid": "SM_pii_001", "From": phone}
    await client.post("/webhook/sms", data=form, headers=HEADERS)

    result = await async_session.execute(
        select(AuditLog).where(AuditLog.message_sid == "SM_pii_001")
    )
    row = result.scalar_one_or_none()
    assert row is not None
    detail = json.loads(row.detail)

    # Raw E.164 must not appear anywhere in the stored detail
    assert phone not in detail.values(), "Raw phone number found in audit_log.detail"

    # The hashed value must be stored in its place
    assert detail["From"] == hash_phone(phone), (
        "Hashed phone not found in audit_log.detail"
    )


async def test_temporal_workflow_started(
    client: AsyncClient,
    mock_twilio_validator,
    _auto_mock_temporal_client,
):
    form = {**VALID_FORM, "MessageSid": "SM_temporal_001"}
    response = await client.post("/webhook/sms", data=form, headers=HEADERS)
    assert response.status_code == 200
    _auto_mock_temporal_client.start_workflow.assert_called_once()
    call_kwargs = _auto_mock_temporal_client.start_workflow.call_args.kwargs
    assert call_kwargs["id"] == "process-message-SM_temporal_001"
    # Producer and worker must agree on the queue — both read Settings.
    assert call_kwargs["task_queue"] == get_settings().temporal.task_queue


async def test_user_e164_captured_on_first_message(
    client: AsyncClient,
    mock_twilio_validator,
    async_session,
):
    """The webhook stores the sender's raw E.164 so match replies can share it."""
    from src.sms.service import hash_phone

    phone = "+15005550077"
    form = {**VALID_FORM, "MessageSid": "SM_e164_001", "From": phone}
    await client.post("/webhook/sms", data=form, headers=HEADERS)

    result = await async_session.execute(
        select(User).where(User.phone_hash == hash_phone(phone))
    )
    user = result.scalar_one()
    assert user.phone_e164 == phone
