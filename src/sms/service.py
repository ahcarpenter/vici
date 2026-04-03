import hashlib

from temporalio.client import Client


def hash_phone(e164_number: str) -> str:
    """SHA-256 hash of E.164 phone number. Twilio From is already E.164."""
    return hashlib.sha256(e164_number.encode()).hexdigest()


async def emit_message_received_event(
    client: Client,
    message_sid: str,
    from_number: str,
    body: str,
) -> None:
    """Fire-and-forget: start ProcessMessageWorkflow in Temporal."""
    from src.temporal.worker import TASK_QUEUE
    from src.temporal.workflows import ProcessMessageWorkflow

    await client.start_workflow(
        ProcessMessageWorkflow.run,
        args=[message_sid, from_number, body],
        id=f"process-message-{message_sid}",
        task_queue=TASK_QUEUE,
    )
