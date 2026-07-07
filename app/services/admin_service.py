import heapq

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.redis_client import redis_client
from app.models.job import Job, JobStatus
from app.models.worker_heartbeat import WorkerStatus
from app.schemas.admin_schema import (
    DashboardResponse,
    JobTypeStats,
    TopKJobResponse,
    WorkerHealthResponse,
    WorkerHeartbeatResponse,
)
from app.services.heartbeat_service import heartbeat_service


class AdminService:
    def get_dashboard(self, db: Session) -> DashboardResponse:
        """
        Aggregate metrics across jobs, workers, and queues.

        DSA: Hash map aggregation.
        We're building a frequency map (status → count) with a single
        GROUP BY query. PostgreSQL does this with a hash aggregate internally —
        same concept as counting word frequencies with a dict in Python.
        """
        status_counts = dict(
            db.query(Job.status, func.count(Job.id))
            .group_by(Job.status)
            .all()
        )

        total = sum(status_counts.values())
        pending = status_counts.get(JobStatus.PENDING, 0)
        processing = status_counts.get(JobStatus.PROCESSING, 0)
        completed = status_counts.get(JobStatus.COMPLETED, 0)
        failed = status_counts.get(JobStatus.FAILED, 0)

        avg_seconds = self._avg_processing_time(db)
        slowest = self._slowest_job_types(db, k=5)
        queue_size = self._get_queue_size()
        workers = self.get_worker_health(db)

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

    def get_top_k_slowest_jobs(
        self, db: Session, k: int = 10
    ) -> list[TopKJobResponse]:
        """
        DSA: Top-K using a heap.

        Find the K slowest completed jobs without sorting the entire table.

        Algorithm (conceptually, even though SQL does the work):
        1. Compute duration for each completed job
        2. Use a min-heap of size k
        3. For each job: if duration > heap min, replace
        4. Result: k largest durations

        Time: O(n log k) — better than O(n log n) full sort when k << n
        Space: O(k)

        We demonstrate this both via SQL (practical) and Python (educational).
        """
        completed_jobs = (
            db.query(
                Job.id,
                Job.job_type,
                func.extract(
                    "epoch", Job.updated_at - Job.created_at
                ).label("duration_seconds"),
            )
            .filter(Job.status == JobStatus.COMPLETED)
            .all()
        )

        if not completed_jobs:
            return []

        job_tuples = [
            (row.duration_seconds or 0.0, row.id, row.job_type)
            for row in completed_jobs
        ]

        top_k = heapq.nlargest(k, job_tuples, key=lambda x: x[0])

        return [
            TopKJobResponse(
                job_id=job_id,
                job_type=job_type.value,
                duration_seconds=round(duration, 3),
            )
            for duration, job_id, job_type in top_k
        ]

    def _avg_processing_time(self, db: Session) -> float | None:
        result = db.query(
            func.avg(
                func.extract("epoch", Job.updated_at - Job.created_at)
            )
        ).filter(Job.status == JobStatus.COMPLETED).scalar()

        return round(float(result), 3) if result else None

    def _slowest_job_types(
        self, db: Session, k: int = 5
    ) -> list[JobTypeStats]:
        """
        DSA: GROUP BY + aggregation = building a hash map of
        {job_type: (count, avg_duration)}, then sorting by avg_duration.
        """
        rows = (
            db.query(
                Job.job_type,
                func.count(Job.id).label("total"),
                func.avg(
                    func.extract("epoch", Job.updated_at - Job.created_at)
                ).label("avg_duration"),
            )
            .filter(Job.status == JobStatus.COMPLETED)
            .group_by(Job.job_type)
            .all()
        )

        stats = [
            JobTypeStats(
                job_type=row.job_type.value,
                total=row.total,
                avg_duration_seconds=round(float(row.avg_duration), 3) if row.avg_duration else None,
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

    def get_worker_health(self, db: Session) -> WorkerHealthResponse:
        heartbeat_service.mark_stale_workers_offline(db)
        return self._build_worker_health(db)

    def _build_worker_health(self, db: Session) -> WorkerHealthResponse:
        workers = heartbeat_service.get_all_workers(db)
        responses = [
            WorkerHeartbeatResponse.model_validate(w) for w in workers
        ]

        return WorkerHealthResponse(
            workers=responses,
            total_online=sum(1 for w in workers if w.status == WorkerStatus.ONLINE),
            total_busy=sum(1 for w in workers if w.status == WorkerStatus.BUSY),
            total_offline=sum(1 for w in workers if w.status == WorkerStatus.OFFLINE),
        )


admin_service = AdminService()