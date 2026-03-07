from datetime import date

import structlog
from braintrust import init_logger, wrap_openai
from openai import APIStatusError, AsyncOpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from src.extraction.constants import GPT_MODEL
from src.extraction.prompts import SYSTEM_PROMPT
from src.extraction.schemas import ExtractionResult

_bt_logger = init_logger(project="vici")  # module-level singleton

log = structlog.get_logger()


class ExtractionService:
    def __init__(self, settings):
        self._client = wrap_openai(
            AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)
        )
        self._settings = settings

    async def process(self, sms_text: str, phone_hash: str) -> ExtractionResult:
        user_message = f"Today is {date.today().isoformat()}. Message: {sms_text}"
        result = await self._call_with_retry(user_message)
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
        )
        return completion.choices[0].message.parsed
