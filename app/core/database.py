from sqlalchemy import create_engine
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


def init_db():
    """Create database tables from registered SQLAlchemy models."""
    import app.models  # noqa: F401 — register model metadata
    Base.metadata.create_all(bind=engine)
    