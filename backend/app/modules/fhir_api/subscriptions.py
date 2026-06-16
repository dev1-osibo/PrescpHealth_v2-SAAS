"""
PrescpHealth Backend — FHIR R4 Webhook Subscriptions (STUB).

Manages FHIR Subscription resources — external systems can register
webhooks to receive notifications when resources change.

STUB ONLY:
    This implementation stores subscription configuration and logs
    intent. It does NOT send real webhook HTTP requests.
    Production: integrate with a message queue (Redis/Celery) or
    a dedicated notification service (e.g., AWS SNS, Azure Event Grid).

FHIR Subscription Reference:
    https://www.hl7.org/fhir/R4/subscription.html

PHI:
    Subscription endpoints (URLs) may be PHI-adjacent — logged by ID only.
    Resource criteria are metadata (e.g., "Encounter?status=finished") — safe to log.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# In-memory store for subscriptions (stub — would be a DB table in production)
_SUBSCRIPTION_STORE: dict[str, dict[str, Any]] = {}


class SubscriptionManager:
    """
    FHIR Subscription management (stub implementation).

    Stores webhook subscription configurations in memory.
    In production, subscriptions would be persisted in the database
    and the delivery mechanism would use Celery tasks.
    """

    def create_subscription(
        self,
        fhir_subscription: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]:
        """
        Register a new FHIR Subscription.

        Validates the subscription resource structure and stores it.
        Returns the subscription with a server-assigned ID.

        Args:
            fhir_subscription: FHIR R4 Subscription resource JSON.
            tenant_id: Tenant context for isolation.

        Returns:
            Stored FHIR Subscription with server-assigned id.

        Raises:
            ValueError: If required subscription fields are missing.
        """
        # Validate required FHIR Subscription fields
        if fhir_subscription.get("resourceType") != "Subscription":
            raise ValueError("resourceType must be 'Subscription'")
        if "criteria" not in fhir_subscription:
            raise ValueError("Subscription.criteria is required")
        if "channel" not in fhir_subscription:
            raise ValueError("Subscription.channel is required")
        if "type" not in fhir_subscription.get("channel", {}):
            raise ValueError("Subscription.channel.type is required")
        if "endpoint" not in fhir_subscription.get("channel", {}):
            raise ValueError("Subscription.channel.endpoint is required")

        sub_id = str(uuid.uuid4())
        stored: dict[str, Any] = {
            **fhir_subscription,
            "id": sub_id,
            "status": "active",
            "resourceType": "Subscription",
            "meta": {
                "versionId": "1",
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            },
            # Internal metadata — not part of FHIR spec
            "_tenant_id": str(tenant_id),
            "_created_at": datetime.now(timezone.utc).isoformat(),
        }
        _SUBSCRIPTION_STORE[sub_id] = stored

        # Log intent — endpoint URL is logged by ID only (may be sensitive)
        logger.info(
            "fhir_subscription_created",
            subscription_id=sub_id,
            criteria=fhir_subscription.get("criteria"),
            channel_type=fhir_subscription.get("channel", {}).get("type"),
            tenant_id=str(tenant_id),
        )

        return stored

    def get_subscription(self, subscription_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve a subscription by ID.

        Args:
            subscription_id: Server-assigned subscription UUID.

        Returns:
            FHIR Subscription dict or None if not found.
        """
        return _SUBSCRIPTION_STORE.get(subscription_id)

    def list_subscriptions(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        """
        List all subscriptions for a tenant.

        Args:
            tenant_id: Tenant context.

        Returns:
            List of FHIR Subscription resources.
        """
        tenant_str = str(tenant_id)
        return [
            sub for sub in _SUBSCRIPTION_STORE.values()
            if sub.get("_tenant_id") == tenant_str
        ]

    def notify_stub(
        self,
        resource_type: str,
        resource_id: uuid.UUID,
        event_type: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """
        Stub notification trigger — logs intent, does NOT send HTTP requests.

        In production, this would:
        1. Find matching subscriptions by criteria.
        2. Enqueue a Celery task to POST the resource to the webhook endpoint.
        3. Handle retries and error responses per FHIR spec.

        Args:
            resource_type: FHIR resource type that changed.
            resource_id: ID of the changed resource.
            event_type: created / updated / deleted.
            tenant_id: Tenant context.
        """
        matching = [
            sub for sub in _SUBSCRIPTION_STORE.values()
            if sub.get("_tenant_id") == str(tenant_id)
            and resource_type in sub.get("criteria", "")
        ]

        logger.info(
            "fhir_subscription_notify_stub",
            resource_type=resource_type,
            resource_id=str(resource_id),
            event_type=event_type,
            matching_subscriptions=len(matching),
            # STUB: would enqueue Celery tasks for each matching subscription
        )
