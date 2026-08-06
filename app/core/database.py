from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    ...


engine = create_engine(settings.database_url, echo=settings.app_env == "development")
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """FastAPI dependency — yields a DB session, closes after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session():
    """
    Context manager for worker / scripts.
    Commits on success, rolls back on error, always closes.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ============================================================
# ASYNC engine + session — used by FastAPI API routes
# ============================================================
async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.app_env == "development",
    pool_size=20,
    max_overflow=10,
)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)


async def get_async_db():
    """
    FastAPI dependency — yields an async DB session.
    Python Internals Focus:
    -----------------------
    This is an async generator (has `yield` inside an `async def`).
    FastAPI detects this and uses it as an async context manager dependency.
    When you write:
        async def my_route(db: AsyncSession = Depends(get_async_db)):
    FastAPI does (conceptually):
        async with contextmanager(get_async_db)() as db:
            response = await my_route(db=db)
    The yield pauses the generator, hands db to the route, and resumes
    after the route finishes (to run the finally block).
    expire_on_commit=False above means attributes on ORM objects remain
    accessible after commit without triggering a lazy load (which would
    fail outside the session context).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def async_db_session():
    """
    Async context manager for services that need commit/rollback control.
    Mirrors the sync db_session() but for async code paths.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def init_db():
    import app.models
    Base.metadata.create_all(bind=engine)