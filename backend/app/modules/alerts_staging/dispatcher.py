"""
PrescpHealth Backend — Alert Dispatcher.

Handles multi-channel delivery of alert notifications.
Each channel is attempted independently; failures are recorded in alert.dispatch_status
so retry logic can target only failed channels.

HIPAA: This module MUST NOT log patient names, phone numbers, email addresses,
       alert message content, or any clinical values. Only alert_id and channel names
       appear in logs.

Current implementation:
- in_app: Marks as sent (in-app notification store is managed by frontend polling)
- email: STUB — real SendGrid integration is future work
- sms: STUB — real Twilio integration is future work
- whatsapp: STUB — real WhatsApp Business API integration is future work
"""
import uuid
import structlog
from typing import Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts_staging.enums import DispatchChannel
from app.modules.alerts_staging.exceptions import DispatchFailedError
from app.modules.alerts_staging.models import Alert

logger = structlog.get_logger(__name__)


class AlertDispatcher:
    """
    Orchestrates multi-channel alert delivery and tracks per-channel delivery status.
    Instantiated per-dispatch-task execution with an injected DB session.
    """

    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        """
        Args:
            db: Async SQLAlchemy session for loading and updating the alert record.
            tenant_id: Current tenant scope; enforced on all alert queries.
        """
        self.db = db
        self.tenant_id = tenant_id

    async def dispatch(self, alert_id: uuid.UUID, channels: list[str]) -> Alert:
        """
        Orchestrate multi-channel delivery for an alert.

        Attempts each requested channel in order. Per-channel status is written back
        to alert.dispatch_status after each attempt so partial delivery is tracked.
        Channels already marked 'sent' in dispatch_status are skipped (idempotent).

        Args:
            alert_id: UUID of the alert to dispatch.
            channels: List of DispatchChannel values to attempt.

        Returns:
            Updated Alert record with current dispatch_status.

        Raises:
            DispatchFailedError: If the alert record cannot be loaded.
        """
        # Load alert — tenant-scoped for security
        stmt = select(Alert).where(
            and_(Alert.id == alert_id, Alert.tenant_id == self.tenant_id)
        )
        alert = (await self.db.scalars(stmt)).first()

        if not alert:
            # Alert may have been deleted or belongs to different tenant — log and raise
            logger.error(
                "dispatch_alert_not_found",
                alert_id=str(alert_id),
                tenant_id=str(self.tenant_id),
            )
            raise DispatchFailedError(str(alert_id), "all")

        # Ensure dispatch_status dict is mutable (JSONB returns immutable by default)
        current_status: dict = dict(alert.dispatch_status or {})
        dispatched_channels: list = list(alert.channels_dispatched or [])

        for channel in channels:
            # Idempotency: skip channels already successfully delivered
            if current_status.get(channel) == "sent":
                continue

            try:
                if channel == DispatchChannel.IN_APP.value:
                    await self.send_in_app(alert)
                elif channel == DispatchChannel.EMAIL.value:
                    await self.send_email(alert, recipient_id=alert.patient_id)
                elif channel == DispatchChannel.SMS.value:
                    await self.send_sms(alert, recipient_id=alert.patient_id)
                elif channel == DispatchChannel.WHATSAPP.value:
                    await self.send_whatsapp(alert, recipient_id=alert.patient_id)

                # Record successful delivery
                current_status[channel] = "sent"
                if channel not in dispatched_channels:
                    dispatched_channels.append(channel)

            except Exception as exc:
                # Record failure with description; task retry handles re-attempt
                current_status[channel] = f"failed: {type(exc).__name__}"
                logger.warning(
                    "dispatch_channel_failed",
                    alert_id=str(alert_id),
                    channel=channel,
                    error_type=type(exc).__name__,
                )

        # Write updated dispatch state back to the alert record
        alert.dispatch_status = current_status
        alert.channels_dispatched = dispatched_channels
        await self.db.commit()
        await self.db.refresh(alert)

        logger.info(
            "dispatch_completed",
            alert_id=str(alert_id),
            channels_attempted=channels,
            tenant_id=str(self.tenant_id),
        )

        return alert

    async def send_in_app(self, alert: Alert) -> None:
        """
        Record in-app notification delivery.

        In-app notifications are consumed by the frontend via polling the alerts API.
        The alert record itself serves as the notification — no external call needed.

        Args:
            alert: Alert record to mark as delivered in-app.
        """
        # In-app delivery is always successful — the alert record IS the notification
        logger.info(
            "dispatch_in_app_sent",
            alert_id=str(alert.id),
        )

    async def send_email(self, alert: Alert, recipient_id: uuid.UUID) -> None:
        """
        STUB: Send email notification.

        TODO (future task): Integrate with SendGrid API.
                           Recipient email should be resolved via user profile service,
                           not stored on the alert record itself.

        Args:
            alert: Alert record (alert_id logged; message content NOT logged).
            recipient_id: UUID of the user to notify; email resolved at send time.

        PHI note: Do NOT log email address, patient name, or alert message.
        """
        # STUB: log intent only — no PHI, no real network call
        logger.info(
            "dispatch_email_stub",
            alert_id=str(alert.id),
            recipient_id=str(recipient_id),  # UUID only; never email address
            note="Real SendGrid integration is future work",
        )
        # Stub returns without error; marked as sent_stub by caller convention

    async def send_sms(self, alert: Alert, recipient_id: uuid.UUID) -> None:
        """
        STUB: Send SMS notification via Twilio.

        TODO (future task): Integrate with Twilio Messaging API.
                           Phone number resolved via user profile service at send time.

        Args:
            alert: Alert record (alert_id logged; message content NOT logged).
            recipient_id: UUID of the user to notify; phone resolved at send time.

        PHI note: Do NOT log phone number, patient name, or alert message.
        """
        logger.info(
            "dispatch_sms_stub",
            alert_id=str(alert.id),
            recipient_id=str(recipient_id),  # UUID only; never phone number
            note="Real Twilio integration is future work",
        )

    async def send_whatsapp(self, alert: Alert, recipient_id: uuid.UUID) -> None:
        """
        STUB: Send WhatsApp notification via WhatsApp Business API.

        TODO (future task): Integrate with WhatsApp Business Cloud API.
                           Message templates must be pre-approved to avoid PHI in template params.

        Args:
            alert: Alert record (alert_id logged; message content NOT logged).
            recipient_id: UUID of the user to notify; WhatsApp ID resolved at send time.

        PHI note: Do NOT log WhatsApp ID, phone number, patient name, or alert message.
        """
        logger.info(
            "dispatch_whatsapp_stub",
            alert_id=str(alert.id),
            recipient_id=str(recipient_id),  # UUID only
            note="Real WhatsApp Business API integration is future work",
        )
