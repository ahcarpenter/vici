class ExtractionParseError(Exception):
    """GPT returned a response that could not be parsed into an ExtractionResult.

    Domain-level failure — infrastructure layers (e.g. Temporal activities)
    decide retry semantics.
    """
