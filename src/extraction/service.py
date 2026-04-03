import time
from datetime import date

import structlog
from braintrust import init_logger
from openai import APIStatusError, RateLimitError
from opentelemetry import trace as otel_trace
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from temporalio.exceptions import ApplicationError

from src.extraction.constants import GPT_MODEL
from src.extraction.prompts import SYSTEM_PROMPT
from src.extraction.schemas import ExtractionResult
from src.metrics import (
    gpt_call_duration_seconds,
    gpt_calls_total,
    gpt_input_tokens_total,
    gpt_output_tokens_total,
)

tracer = otel_trace.get_tracer(__name__)

_bt_logger = init_logger(project="vici")  # module-level singleton

log = structlog.get_logger()


class ExtractionService:
    def __init__(self, openai_client, settings):
        """Receives a pre-built (and optionally wrapped) AsyncOpenAI client."""
        self._client = openai_client
        self._settings = settings

    @property
    def openai_client(self):
        return self._client

    @property
    def settings(self):
        return self._settings

    async def process(self, sms_text: str, phone_hash: str) -> ExtractionResult:
        """GPT classification only — no DB, no session param."""
        user_message = f"Today is {date.today().isoformat()}. Message: {sms_text}"

        with tracer.start_as_current_span("gpt.classify_and_extract") as span:
            span.set_attribute("gen_ai.system", "openai")
            span.set_attribute(
                "gen_ai.request.model", self._settings.extraction.gpt_model
            )
            t0 = time.perf_counter()
            result, usage = await self._call_with_retry(user_message)
            gpt_call_duration_seconds.observe(time.perf_counter() - t0)

        gpt_calls_total.labels(classification_result=result.message_type).inc()
        if usage:
            gpt_input_tokens_total.inc(usage.prompt_tokens or 0)
            gpt_output_tokens_total.inc(usage.completion_tokens or 0)

        log.info(
            "gpt_classified",
            message_type=result.message_type,
            phone_hash=phone_hash,
        )

        return result

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIStatusError)),
        stop=stop_after_attempt(4),
        wait=wait_random_exponential(multiplier=1, min=1, max=60),
    )
    async def _call_with_retry(self, user_message: str) -> ExtractionResult:
        completion = await self._client.beta.chat.completions.parse(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format=ExtractionResult,
            timeout=30.0,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ApplicationError(
                "GPT returned unparseable response", non_retryable=False
            )
        return parsed, completion.usage
