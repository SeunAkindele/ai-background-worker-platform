import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FilePurpose(str, enum.Enum):
    """What the uploaded file will be used for."""
    OCR = "ocr"
    TRANSCRIPTION = "transcription"


class JobFile(Base):
    """Metadata for an uploaded file stored on disk (deduped by content_hash)."""
    __tablename__ = "job_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True
    )
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    file_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purpose: Mapped[FilePurpose] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job = relationship("Job", backref="files", lazy="selectin")