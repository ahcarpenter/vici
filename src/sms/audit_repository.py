from sqlalchemy.ext.asyncio import AsyncSession

from src.sms.models import AuditLog


class AuditLogRepository:
    @staticmethod
    async def write(
        session: AsyncSession,
        message_sid: str,
        event: str,
        detail: str | None = None,
        message_id: int | None = None,
    ) -> None:
        """Insert an audit_log row. Flush-only — caller owns the transaction."""
        row = AuditLog(
            message_sid=message_sid,
            event=event,
            detail=detail,
            message_id=message_id,
        )
        session.add(row)
        await session.flush()
