from datetime import timedelta

TASK_QUEUE: str = "vici-queue"  # overridable via env — wired through Settings
CRON_SCHEDULE_PINECONE_SYNC: str = "*/5 * * * *"
WORKFLOW_PINECONE_SYNC_ID: str = "sync-pinecone-queue-cron"

# ProcessMessageWorkflow retry policy
PROCESS_MSG_RETRY_MAX_ATTEMPTS: int = 4
PROCESS_MSG_RETRY_INITIAL_INTERVAL: timedelta = timedelta(seconds=1)
PROCESS_MSG_RETRY_BACKOFF_COEFFICIENT: float = 2.0
PROCESS_MSG_RETRY_MAX_INTERVAL: timedelta = timedelta(minutes=5)

# Activity start_to_close timeouts
PROCESS_MSG_ACTIVITY_TIMEOUT: timedelta = timedelta(seconds=60)
FAILURE_ACTIVITY_TIMEOUT: timedelta = timedelta(seconds=10)
PINECONE_SYNC_ACTIVITY_TIMEOUT: timedelta = timedelta(seconds=120)

# Worker shutdown timeout
WORKER_SHUTDOWN_TIMEOUT_SECONDS: float = 10.0
