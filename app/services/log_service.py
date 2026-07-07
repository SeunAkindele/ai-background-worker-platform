import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.job_log import JobLog, LogLevel


class LogService:
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

    def get_logs_for_job(
        self,
        db: Session,
        job_id: uuid.UUID,
        limit: int = 100,
    ) -> tuple[list[JobLog], int]:
        """
        DSA: The query uses the B-tree index on job_id for O(log n) lookup,
        then returns rows ordered by created_at (append-order).
        """
        query = (
            db.query(JobLog)
            .filter(JobLog.job_id == job_id)
            .order_by(JobLog.created_at.asc())
        )
        total = query.count()
        logs = query.limit(limit).all()
        return logs, total

    def get_recent_errors(
        self, db: Session, limit: int = 50
    ) -> list[JobLog]:
        return (
            db.query(JobLog)
            .filter(JobLog.level == LogLevel.ERROR)
            .order_by(JobLog.created_at.desc())
            .limit(limit)
            .all()
        )


log_service = LogService()