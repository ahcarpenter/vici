"""Outbound SMS sending via Twilio.

Single home for the send-with-span idiom so every caller traces sends the
same way and never leaks a raw phone number into span attributes.
"""

import asyncio

from opentelemetry import trace as otel_trace
from twilio.rest import Client as TwilioClient

from src.observability import (
    OTEL_ATTR_MESSAGING_DESTINATION,
    OTEL_ATTR_MESSAGING_SYSTEM,
)
from src.sms.service import hash_phone

tracer = otel_trace.get_tracer(__name__)


async def send_sms(
    twilio_client: TwilioClient, *, to: str, from_number: str, body: str
) -> None:
    """Send one SMS. Raises on failure — callers decide how to degrade.

    The synchronous Twilio client is offloaded to a thread.
    """
    with tracer.start_as_current_span("twilio.send_sms") as span:
        span.set_attribute(OTEL_ATTR_MESSAGING_SYSTEM, "twilio")
        span.set_attribute(OTEL_ATTR_MESSAGING_DESTINATION, hash_phone(to))
        await asyncio.to_thread(
            twilio_client.messages.create,
            to=to,
            from_=from_number,
            body=body,
        )
