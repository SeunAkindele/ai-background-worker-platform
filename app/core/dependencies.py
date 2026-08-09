"""Shared FastAPI dependencies for rate limiting and backpressure."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_async_db
from app.core.rate_limiter import rate_limiter


def get_client_id(request: Request) -> str:
    """Return a client identifier for rate limiting (client IP for now)."""
    if request.client:
        return request.client.host
    return "unknown"


async def enforce_rate_limit(
    client_id: str = Depends(get_client_id),
) -> str:
    """Raise 429 when the client exceeds the configured rate limit."""
    allowed, count = rate_limiter.check_and_record(client_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit exceeded",
                "limit": settings.rate_limit_requests,
                "window_seconds": settings.rate_limit_window_seconds,
                "current_count": count,
            },
        )
    return client_id


async def enforce_pending_limit(
    client_id: str = Depends(get_client_id),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Raise 429 when pending jobs exceed max_pending_jobs_per_user."""
    from sqlalchemy import func, select

    from app.models.job import Job, JobStatus

    stmt = (
        select(func.count())
        .where(Job.status == JobStatus.PENDING)
    )
    result = await db.execute(stmt)
    pending_count = result.scalar_one()

    if pending_count >= settings.max_pending_jobs_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Too many pending jobs",
                "pending_count": pending_count,
                "limit": settings.max_pending_jobs_per_user,
            },
        )