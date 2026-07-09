import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.job_log import JobLog, LogLevel


class LogService:
    # ==============================================================
    # ASYNC methods
    # ==============================================================

    async def async_get_logs_for_job(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[JobLog], int]:
        stmt = (
            select(JobLog)
            .where(JobLog.job_id == job_id)
            .order_by(JobLog.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        logs = list(result.scalars().all())

        count_stmt = (
            select(func.count())
            .select_from(JobLog)
            .where(JobLog.job_id == job_id)
        )
        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()

        return logs, total

    async def async_get_recent_errors(
        self, db: AsyncSession, skip: int = 0, limit: int = 50
    ) -> list[JobLog]:
        stmt = (
            select(JobLog)
            .where(JobLog.level == LogLevel.ERROR)
            .order_by(JobLog.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ==============================================================
    # SYNC methods — used by Celery workers 
    # ==============================================================

    def add_log(
        self,
        db: Session,
        job_id: uuid.UUID,
        message: str,
        level: LogLevel = LogLevel.INFO,
    ) -> JobLog:
        log_entry = JobLog(
            job_id=job_id,
            message=message,
            level=level,
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry


log_service = LogService()