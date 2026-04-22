import hashlib
from collections.abc import Mapping

from temporalio.client import Client


def hash_phone(e164_number: str) -> str:
    """SHA-256 hash of E.164 phone number. Twilio From is already E.164."""
    if not e164_number:
        raise ValueError(
            f"hash_phone: e164_number must be a non-empty string, got {e164_number!r}"
        )
    return hashlib.sha256(e164_number.encode()).hexdigest()


def scrub_phone_fields(form: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of *form* with E.164 numbers replaced by their SHA-256 hashes.

    Only ``From`` and ``To`` are scrubbed; all other fields are passed through
    unchanged.  Values that are absent or empty are left as-is.
    """
    _PHONE_FIELDS = {"From", "To"}
    return {
        k: (hash_phone(v) if k in _PHONE_FIELDS and v else v) for k, v in form.items()
    }


async def emit_message_received_event(
    client: Client,
    message_sid: str,
    from_number: str,
    body: str,
) -> None:
    """Fire-and-forget: start ProcessMessageWorkflow in Temporal."""
    from src.temporal.constants import TASK_QUEUE
    from src.temporal.workflows import ProcessMessageWorkflow

    await client.start_workflow(
        ProcessMessageWorkflow.run,
        args=[message_sid, from_number, body],
        id=f"process-message-{message_sid}",
        task_queue=TASK_QUEUE,
    )
