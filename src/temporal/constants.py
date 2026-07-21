from datetime import timedelta

WORKFLOW_PINECONE_SYNC_ID: str = "sync-pinecone-queue-cron"
WORKFLOW_RATE_LIMIT_PURGE_ID: str = "purge-rate-limit-cron"
CRON_SCHEDULE_RATE_LIMIT_PURGE: str = "0 * * * *"  # hourly

# ProcessMessageWorkflow retry policy
PROCESS_MSG_RETRY_MAX_ATTEMPTS: int = 4
PROCESS_MSG_RETRY_INITIAL_INTERVAL: timedelta = timedelta(seconds=1)
PROCESS_MSG_RETRY_BACKOFF_COEFFICIENT: float = 2.0
PROCESS_MSG_RETRY_MAX_INTERVAL: timedelta = timedelta(minutes=5)

# Activity start_to_close timeouts
PROCESS_MSG_ACTIVITY_TIMEOUT: timedelta = timedelta(seconds=60)
FAILURE_ACTIVITY_TIMEOUT: timedelta = timedelta(seconds=10)
PINECONE_SYNC_ACTIVITY_TIMEOUT: timedelta = timedelta(seconds=120)
RATE_LIMIT_PURGE_ACTIVITY_TIMEOUT: timedelta = timedelta(seconds=60)

# Worker shutdown timeout
WORKER_SHUTDOWN_TIMEOUT_SECONDS: float = 10.0
