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
    """Create tables. For Stage 1, calling this on startup is fine."""
    # Import all models so SQLAlchemy can register metadata
    import app.models
    Base.metadata.create_all(bind=engine)
    