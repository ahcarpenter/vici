import hashlib

import inngest as inngest_module
from opentelemetry.propagate import inject as otel_inject


def hash_phone(e164_number: str) -> str:
    """SHA-256 hash of E.164 phone number. Twilio From is already E.164."""
    return hashlib.sha256(e164_number.encode()).hexdigest()


async def emit_message_received_event(
    client: inngest_module.Inngest,
    message_sid: str,
    from_number: str,
    body: str,
) -> None:
    """
    Fire-and-forget: emit message.received event to Inngest.
    Injects W3C traceparent so the Inngest function can continue the trace.
    """
    carrier: dict = {}
    otel_inject(carrier)  # {"traceparent": "00-<trace_id>-<span_id>-01"} or {}

    await client.send(
        inngest_module.Event(
            name="message.received",
            data={
                "message_sid": message_sid,
                "from_number": from_number,
                "body": body,
                "otel": carrier,
            },
        )
    )
