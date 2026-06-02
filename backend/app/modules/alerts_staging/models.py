"""
PrescpHealth Backend — Alert System SQLAlchemy Models.

Three tenant-scoped tables:
- Alert: Clinical alert records with multi-channel dispatch tracking
- AlertThreshold: Configurable per-patient or tenant-wide alert thresholds
- EscalationRecord: Audit trail for alert escalation events

HIPAA: All three tables contain PHI and are RLS-scoped to tenant_id.
Row-Level Security (RLS) is enforced at the database level via PostgreSQL policies
defined in the corresponding Alembic migration (0015_alert_system_tables.py).
"""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.base_model import Base, TenantMixin
from app.modules.alerts_staging.enums import AlertType, AlertSeverity, AlertStatus, ThresholdCondition


class Alert(TenantMixin, Base):
    """
    Clinical alert record with full lifecycle tracking.

    Stores the alert from creation through acknowledgment, escalation, and resolution.
    The `payload` JSONB column holds structured clinical context (risk scores, measurements)
    but is never surfaced in logs — only UUID references are logged.
    """
    __tablename__ = "alerts"

    # Primary key — UUID avoids sequential ID enumeration attacks
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Patient reference — joins to patients table; always scoped by tenant_id
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Alert classification fields
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # Human-readable description — contains PHI; never logged
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured clinical context: risk scores, measurements, forecast info — PHI
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Structured data: risk scores, measurements, forecast info — PHI",
    )

    # Lifecycle state; starts as 'active'
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="active")

    # Acknowledgment tracking
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="User UUID who acknowledged"
    )
    acknowledgment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Escalation tracking — level 0 = initial; 1 = doctor; 2 = clinic_admin
    escalation_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="0=initial, 1=escalated to doctor, 2=escalated to admin",
    )
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Dispatch tracking — list of channels attempted, per-channel delivery status
    channels_dispatched: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="e.g. ['in_app', 'email', 'sms']",
    )
    dispatch_status: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="e.g. {'email': 'sent', 'sms': 'failed_retry_2'}",
    )

    __table_args__ = (
        # Covering index for common query: patient's alerts filtered by status
        Index("ix_alert_tenant_patient_status", "tenant_id", "patient_id", "status"),
        # Dashboard query: all active alerts sorted by severity and time
        Index("ix_alert_tenant_status_severity", "tenant_id", "status", "severity", "created_at"),
    )


class AlertThreshold(TenantMixin, Base):
    """
    Configurable alert threshold, per-patient or tenant-wide default.

    If patient_id is NULL, the threshold applies as a tenant-wide default for all patients.
    Patient-specific thresholds take precedence over tenant defaults in the rules engine.
    """
    __tablename__ = "alert_thresholds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # NULL means this is a tenant-wide default threshold
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="NULL means tenant-wide default"
    )

    # What clinical value this threshold monitors
    measurement_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="For measurement-based thresholds"
    )
    disease: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="For risk-score-based thresholds"
    )

    # Condition and threshold value defining when an alert fires
    condition: Mapped[str] = mapped_column(String(30), nullable=False)
    threshold_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_stratum: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="For enters_stratum condition"
    )

    # Severity of alerts generated by this threshold
    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    # Soft-delete: deactivated instead of deleted to preserve audit history
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Who configured this threshold — important for audit and ownership
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="Clinician who created this threshold"
    )

    __table_args__ = (
        Index("ix_threshold_tenant_patient_active", "tenant_id", "patient_id", "is_active"),
    )


class EscalationRecord(TenantMixin, Base):
    """
    Immutable audit record of each alert escalation event.

    Created whenever an alert moves to a higher escalation level.
    Never updated — only new records are inserted to preserve the escalation trail.
    """
    __tablename__ = "escalation_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Reference to the parent alert — not a FK constraint to allow soft-archiving
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="FK to alerts.id"
    )

    # Escalation transition details
    from_level: Mapped[int] = mapped_column(Integer, nullable=False)
    to_level: Mapped[int] = mapped_column(Integer, nullable=False)
    escalated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Who received the escalation notification
    target_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="User to whom alert was escalated"
    )

    # Machine-readable reason for escalation
    reason: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="e.g. unacknowledged_timeout"
    )

    __table_args__ = (
        # Fast lookup of all escalations for a given alert
        Index("ix_escalation_alert_id", "alert_id"),
    )
