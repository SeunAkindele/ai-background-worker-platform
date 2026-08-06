import heapq

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


from app.core.redis_client import redis_client
from app.models.job import Job, JobStatus
from app.models.worker_heartbeat import WorkerHeartbeat, WorkerStatus
from app.schemas.admin_schema import (
    DashboardResponse,
    JobTypeStats,
    TopKJobResponse,
    WorkerHealthResponse,
    WorkerHeartbeatResponse,
)
from app.services.heartbeat_service import heartbeat_service


class AdminService:
    # ==============================================================
    # ASYNC methods — used by FastAPI routes
    # ==============================================================

    async def async_get_dashboard(self, db: AsyncSession) -> DashboardResponse:
        """Aggregate job counts, queue depth, and worker health for the admin dashboard."""
        stmt = (
            select(Job.status, func.count(Job.id))
            .group_by(Job.status)
        )
        result = await db.execute(stmt)
        status_counts = dict(result.all())

        total = sum(status_counts.values())
        pending = status_counts.get(JobStatus.PENDING, 0)
        processing = status_counts.get(JobStatus.PROCESSING, 0)
        completed = status_counts.get(JobStatus.COMPLETED, 0)
        failed = status_counts.get(JobStatus.FAILED, 0)

        avg_seconds = await self._async_avg_processing_time(db)
        slowest = await self._async_slowest_job_types(db, k=5)
        queue_size = self._get_queue_size()
        workers = await self.async_get_worker_health(db)

        return DashboardResponse(
            total_jobs=total,
            pending_jobs=pending,
            processing_jobs=processing,
            completed_jobs=completed,
            failed_jobs=failed,
            avg_processing_seconds=avg_seconds,
            slowest_job_types=slowest,
            queue_size=queue_size,
            workers=workers,
        )

    async def async_get_top_k_slowest_jobs(
        self, db: AsyncSession, skip: int = 0, limit: int = 10
    ) -> list[TopKJobResponse]:
        """Return the slowest completed jobs, paginated."""
        stmt = (
            select(
                Job.id,
                Job.job_type,
                func.extract("epoch", Job.updated_at - Job.created_at).label(
                    "duration_seconds"
                ),
            )
            .where(Job.status == JobStatus.COMPLETED)
        )
        result = await db.execute(stmt)
        completed_jobs = result.all()

        if not completed_jobs:
            return []

        job_tuples = [
            (row.duration_seconds or 0.0, row.id, row.job_type)
            for row in completed_jobs
        ]

        top_k = heapq.nlargest(skip + limit, job_tuples, key=lambda x: x[0])
        page = top_k[skip : skip + limit]

        return [
            TopKJobResponse(
                job_id=job_id,
                job_type=job_type.value,
                duration_seconds=round(duration, 3),
            )
            for duration, job_id, job_type in page
        ]

    async def async_get_worker_health(self, db: AsyncSession) -> WorkerHealthResponse:
        await heartbeat_service.async_mark_stale_workers_offline(db)

        stmt = select(WorkerHeartbeat)
        result = await db.execute(stmt)
        workers = result.scalars().all()

        responses = [
            WorkerHeartbeatResponse.model_validate(w) for w in workers
        ]
        return WorkerHealthResponse(
            workers=responses,
            total_online=sum(1 for w in workers if w.status == WorkerStatus.ONLINE),
            total_busy=sum(1 for w in workers if w.status == WorkerStatus.BUSY),
            total_offline=sum(1 for w in workers if w.status == WorkerStatus.OFFLINE),
        )

    async def _async_avg_processing_time(self, db: AsyncSession) -> float | None:
        stmt = (
            select(
                func.avg(func.extract("epoch", Job.updated_at - Job.created_at))
            )
            .where(Job.status == JobStatus.COMPLETED)
        )
        result = await db.execute(stmt)
        value = result.scalar_one_or_none()
        return round(float(value), 3) if value else None

    async def _async_slowest_job_types(
        self, db: AsyncSession, k: int = 5
    ) -> list[JobTypeStats]:
        stmt = (
            select(
                Job.job_type,
                func.count(Job.id).label("total"),
                func.avg(
                    func.extract("epoch", Job.updated_at - Job.created_at)
                ).label("avg_duration"),
            )
            .where(Job.status == JobStatus.COMPLETED)
            .group_by(Job.job_type)
        )
        result = await db.execute(stmt)
        rows = result.all()

        stats = [
            JobTypeStats(
                job_type=row.job_type.value,
                total=row.total,
                avg_duration_seconds=round(float(row.avg_duration), 3)
                if row.avg_duration
                else None,
            )
            for row in rows
        ]

        return heapq.nlargest(k, stats, key=lambda s: s.avg_duration_seconds or 0)


    def _get_queue_size(self) -> int:
        try:
            high = redis_client.llen("high") or 0
            normal = redis_client.llen("normal") or 0
            low = redis_client.llen("low") or 0
            return high + normal + low
        except Exception:
            return -1


admin_service = AdminService()