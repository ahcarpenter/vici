"""OTel semantic-convention attribute keys shared across layers.

Cross-cutting observability vocabulary — lives at the top level (like
``metrics.py``) so domain modules never import it from each other.
"""

# Messaging namespace
OTEL_ATTR_MESSAGE_ID: str = "messaging.message_id"
OTEL_ATTR_PHONE_HASH: str = "messaging.source.phone_hash"
OTEL_ATTR_MESSAGING_SYSTEM: str = "messaging.system"
OTEL_ATTR_MESSAGING_DESTINATION: str = "messaging.destination.name"

# Database namespace
OTEL_ATTR_DB_SYSTEM: str = "db.system"
OTEL_ATTR_DB_OPERATION: str = "db.operation.name"
OTEL_ATTR_DB_VECTOR_JOB_ID: str = "db.vector.job_id"

# Application-specific attribute keys
OTEL_ATTR_WORK_GOAL_USER_ID: str = "app.work_goal.user_id"
