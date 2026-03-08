"""Application-level Prometheus metric singletons.

All metrics are registered at module-import time. Import this module once at
startup (or lazily inside functions) — never instantiate metrics inside
classes or conditionals to avoid duplicate registration errors.
"""

from prometheus_client import Counter, Histogram, Gauge

gpt_calls_total = Counter(
    "gpt_calls_total",
    "Total GPT API calls",
    ["classification_result"],
)

gpt_call_duration_seconds = Histogram(
    "gpt_call_duration_seconds",
    "GPT API call latency in seconds",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

gpt_input_tokens_total = Counter(
    "gpt_input_tokens_total",
    "Total GPT input tokens consumed",
)

gpt_output_tokens_total = Counter(
    "gpt_output_tokens_total",
    "Total GPT output tokens consumed",
)

pinecone_sync_queue_depth = Gauge(
    "pinecone_sync_queue_depth",
    "Number of rows in pinecone_sync_queue with status=pending",
)

inngest_queue_depth = Gauge(
    "inngest_queue_depth",
    "Stub gauge — Inngest dev server exposes no public metrics API",
)
# inngest_queue_depth always reads 0; placeholder for future instrumentation

pipeline_failures_total = Counter(
    "pipeline_failures_total",
    "Total number of process-message Inngest function permanent failures",
    ["function"],
)
