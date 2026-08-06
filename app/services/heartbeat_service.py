import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.worker_heartbeat import WorkerHeartbeat, WorkerStatus


HEARTBEAT_INTERVAL_SECONDS = 60
HEARTBEAT_TIMEOUT = timedelta(minutes=2)


class HeartbeatService:

    def _upsert(
        self,
        db: Session,
        worker_name: str,
        *,
        worker_type: str = "general",
        status: WorkerStatus | None = None,
        current_job_id: uuid.UUID | None = None,
        update_type: bool = True,
        update_status: bool = True,
    ) -> WorkerHeartbeat:
        """
        Upsert a heartbeat row for beat() and pulse().

        update_type=False preserves existing worker_type (pulse).
        update_status=False preserves status and current_job_id (pulse).
        """
        existing = (
            db.query(WorkerHeartbeat)
            .filter(WorkerHeartbeat.worker_name == worker_name)
            .first()
        )

        now = datetime.now(timezone.utc)

        if existing:
            existing.last_seen_at = now
            if update_type:
                existing.worker_type = worker_type
            if update_status:
                existing.status = status or WorkerStatus.ONLINE
                existing.current_job_id = current_job_id
            db.commit()
            db.refresh(existing)
            return existing

        heartbeat = WorkerHeartbeat(
            worker_name=worker_name,
            worker_type=worker_type,
            status=status or WorkerStatus.ONLINE,
            last_seen_at=now,
            current_job_id=current_job_id,
        )
        db.add(heartbeat)
        db.commit()
        db.refresh(heartbeat)
        return heartbeat

    def beat(
        self,
        db: Session,
        worker_name: str,
        worker_type: str,
        status: WorkerStatus = WorkerStatus.ONLINE,
        current_job_id: uuid.UUID | None = None,
    ) -> WorkerHeartbeat:
        """State-changing heartbeat: sets status, worker_type, and current_job_id."""
        return self._upsert(
            db, worker_name,
            worker_type=worker_type,
            status=status,
            current_job_id=current_job_id,
            update_type=True,
            update_status=True,
        )

    def pulse(self, db: Session, worker_name: str) -> None:
        """
        Liveness-only ping from the background thread.

        Only refreshes last_seen_at. Preserves status, current_job_id,
        and worker_type so it never overwrites state set by beat().
        """
        self._upsert(
            db, worker_name,
            update_type=False,
            update_status=False,
        )

    def mark_offline(self, db: Session, worker_name: str) -> None:
        """Immediately mark a worker as OFFLINE on graceful shutdown."""
        worker = (
            db.query(WorkerHeartbeat)
            .filter(WorkerHeartbeat.worker_name == worker_name)
            .first()
        )
        if not worker:
            return
        worker.status = WorkerStatus.OFFLINE
        worker.current_job_id = None
        worker.last_seen_at = datetime.now(timezone.utc)
        db.commit()

    def record_completion(
        self, db: Session, worker_name: str, success: bool
    ) -> None:
        """Increment the completed or failed counter after a job finishes."""
        worker = (
            db.query(WorkerHeartbeat)
            .filter(WorkerHeartbeat.worker_name == worker_name)
            .first()
        )
        if not worker:
            return
        if success:
            worker.jobs_completed += 1
        else:
            worker.jobs_failed += 1
        worker.status = WorkerStatus.ONLINE
        worker.current_job_id = None
        worker.last_seen_at = datetime.now(timezone.utc)
        db.commit()

    def get_all_workers(self, db: Session) -> list[WorkerHeartbeat]:
        return db.query(WorkerHeartbeat).all()

    def mark_stale_workers_offline(self, db: Session) -> int:
        """
        Mark workers offline if they have not heartbeated within HEARTBEAT_TIMEOUT.

        Returns the number of workers marked offline.
        """
        cutoff = datetime.now(timezone.utc) - HEARTBEAT_TIMEOUT
        stale_workers = (
            db.query(WorkerHeartbeat)
            .filter(
                WorkerHeartbeat.last_seen_at < cutoff,
                WorkerHeartbeat.status != WorkerStatus.OFFLINE,
            )
            .all()
        )
        for worker in stale_workers:
            worker.status = WorkerStatus.OFFLINE
            worker.current_job_id = None

        if stale_workers:
            db.commit()

        return len(stale_workers)

    async def async_mark_stale_workers_offline(self, db: AsyncSession) -> int:
        """Async variant of mark_stale_workers_offline for FastAPI routes."""
        cutoff = datetime.now(timezone.utc) - HEARTBEAT_TIMEOUT
        stmt = select(WorkerHeartbeat).where(
            WorkerHeartbeat.last_seen_at < cutoff,
            WorkerHeartbeat.status != WorkerStatus.OFFLINE,
        )
        result = await db.execute(stmt)
        stale_workers = list(result.scalars().all())

        for worker in stale_workers:
            worker.status = WorkerStatus.OFFLINE
            worker.current_job_id = None

        if stale_workers:
            await db.commit()

        return len(stale_workers)


heartbeat_service = HeartbeatService()