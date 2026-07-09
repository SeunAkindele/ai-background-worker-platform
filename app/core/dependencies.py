"""
Shared FastAPI dependencies.

Python Internals Focus:
-----------------------
FastAPI dependencies are callables (functions, classes, or generators).
When a dependency is an `async def` with `yield`, FastAPI treats it as an
async context manager — enter before the route, exit after.

Depends() uses Python's type annotation system at import time to build
a dependency graph. At runtime, it resolves dependencies in topological
order (another DSA concept: DAG traversal).
"""
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_async_db
from app.core.rate_limiter import rate_limiter


def get_client_id(request: Request) -> str:
    """
    Extract a client identifier for rate limiting.

    In a real app, this would come from an auth token (JWT, API key).
    For now, we use the client IP. In production you'd add authentication
    as a Stage 8.5 enhancement.

    Python Internals:
    request.client is an optional NamedTuple-like object.
    request.client.host is the IP. Behind a reverse proxy, you'd
    read X-Forwarded-For instead.
    """
    if request.client:
        return request.client.host
    return "unknown"


async def enforce_rate_limit(
    client_id: str = Depends(get_client_id),
) -> str:
    """
    Dependency that blocks requests exceeding the rate limit.

    DSA Focus:
    This is where the sliding window counter gets used.
    Every request passes through this checkpoint.

    If rate limited → 429 Too Many Requests.
    If allowed → request proceeds, counter incremented.
    """
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
    """
    Prevent a single user from flooding the queue with too many pending jobs.

    DSA Focus:
    This is backpressure — a mechanism to prevent unbounded queue growth.
    Without this, one user could submit 10,000 jobs and starve others.

    The max_pending_jobs_per_user setting acts as a bounded buffer:
    - Buffer full → reject new submissions (HTTP 429)
    - Buffer has space → allow submission
    """
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