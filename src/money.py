"""
Money utilities.

The application stores and processes all monetary values as integer cents.
Two conversions exist at the system boundary:

  - dollars_to_cents: called when persisting LLM-extracted dollar amounts
  - cents_to_dollars: called when formatting cents for user-facing SMS replies
"""

CENTS_PER_DOLLAR: int = 100


def dollars_to_cents(dollars: float) -> int:
    """Convert a dollar float to integer cents (rounds to nearest cent)."""
    return int(round(dollars * CENTS_PER_DOLLAR))


def cents_to_dollars(cents: int) -> float:
    """Convert integer cents to a dollar float. Use only at SMS reply boundary."""
    return cents / CENTS_PER_DOLLAR
