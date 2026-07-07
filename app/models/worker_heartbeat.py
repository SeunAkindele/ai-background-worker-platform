import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WorkerStatus(str, enum.Enum):
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    worker_name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    worker_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[WorkerStatus] = mapped_column(
        Enum(WorkerStatus), nullable=False, default=WorkerStatus.ONLINE
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    current_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    jobs_completed: Mapped[int] = mapped_column(default=0, nullable=False)
    jobs_failed: Mapped[int] = mapped_column(default=0, nullable=False)