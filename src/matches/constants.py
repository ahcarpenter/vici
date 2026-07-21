"""Matching policy constants."""

# Semantic candidate retrieval (Pinecone read path)
SEMANTIC_TOP_K: int = 50  # vectors requested per goal; bounds the DP pool
SEMANTIC_MIN_CANDIDATES: int = 5  # below this, fall back to the full scan so
# the worker always sees a full SMS menu (mirrors MAX_JOBS_IN_SMS)
SEMANTIC_SEARCH_TIMEOUT_SECONDS: float = 5.0  # embed+query budget inside the UoW
