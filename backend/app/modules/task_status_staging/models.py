"""
PrescpHealth Backend — BackgroundTask Model.

Tenant-scoped model that tracks lifecycle and results of
asynchronous background tasks (Celery or otherwise).

HIPAA: params and result columns may contain PHI — never log their content.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TenantMixin


class BackgroundTask(TenantMixin, Base):
    """
    Persists the state and result of an async background task.

    Status lifecycle:
        pending → running → completed
                          → failed → retrying → running (cycle until max_retries)

    PHI note: params and result may contain clinical data and must
    never appear in log output.
    """

    __tablename__ = "background_tasks"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Unique task identifier (UUID4)",
    )

    # Task classification
    task_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Logical task category, e.g. 'risk_score_batch', 'report_generate'",
    )

    # Current lifecycle state
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="pending",
        comment="One of: pending, running, completed, failed, retrying",
    )

    # Task input — may contain PHI; never log
    params: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Task input parameters (may contain PHI — do not log)",
    )

    # Task output — may contain PHI; never log
    result: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Task output/result payload (may contain PHI — do not log)",
    )

    # Human-readable error message on failure
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Last error message (no PHI in error strings)",
    )

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="Number of retry attempts so far",
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("3"),
        comment="Maximum allowed retry attempts before permanent failure",
    )

    # Celery integration
    celery_task_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Celery task UUID for status polling via broker",
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When task execution began (NULL until picked up by worker)",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When task finished (completed or permanently failed)",
    )

    # Composite index for tenant-scoped status queries (dashboard polling)
    __table_args__ = (
        Index("ix_bg_task_tenant_status", "tenant_id", "status", "created_at"),
    )
