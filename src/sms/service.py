import hashlib
import hmac
from collections.abc import Mapping

from src.config import get_settings


def hash_phone(e164_number: str) -> str:
    """HMAC-SHA256 pseudonym of an E.164 phone number. Twilio From is already E.164.

    Keyed with ``PHONE_HASH_PEPPER`` — the E.164 space is small enough that an
    unkeyed hash is trivially reversible by enumeration. The pepper is required
    in production (see ``Settings``); an empty pepper degrades to a plain keyed
    hash for local development.
    """
    if not e164_number:
        raise ValueError(
            f"hash_phone: e164_number must be a non-empty string, got {e164_number!r}"
        )
    pepper = get_settings().sms.phone_hash_pepper
    return hmac.new(pepper.encode(), e164_number.encode(), hashlib.sha256).hexdigest()


def scrub_phone_fields(form: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of *form* with E.164 numbers replaced by their hashes.

    Only ``From`` and ``To`` are scrubbed; all other fields are passed through
    unchanged.  Values that are absent or empty are left as-is.
    """
    _PHONE_FIELDS = {"From", "To"}
    return {
        k: (hash_phone(v) if k in _PHONE_FIELDS and v else v) for k, v in form.items()
    }
