"""
Unit Tests: Billing Module (Task 17.4).

Tests cover:
- Invoice generation from encounter (line items for consultation)
- Payment recording updates paid_amount and transitions status
- Insurance claim submission creates claim with correct fields
- Claim denial updates status and stores denial_reason
- Void invoice sets status to void
- Total amount computation matches line items sum

All tests use mocked AsyncSession — no real DB connections.
Monetary values use Decimal (never float).
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.billing.enums import (
    ClaimStatus,
    InvoiceStatus,
    ItemType,
    PaymentMethod,
)
from app.modules.billing.exceptions import (
    InvoiceAlreadyVoidError,
    InvoiceNotFoundError,
)

# Module-level audit mock — patched into both service modules
_mock_audit = MagicMock(log=AsyncMock())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_invoice(**overrides):
    """Create a mock Invoice with sensible defaults."""
    inv = MagicMock()
    inv.id = overrides.get("id", uuid.uuid4())
    inv.tenant_id = overrides.get("tenant_id", uuid.uuid4())
    inv.patient_id = overrides.get("patient_id", uuid.uuid4())
    inv.encounter_id = overrides.get("encounter_id", uuid.uuid4())
    inv.invoice_number = overrides.get("invoice_number", "INV-TEST-001")
    inv.status = overrides.get("status", InvoiceStatus.ISSUED)
    inv.total_amount = overrides.get("total_amount", Decimal("100.00"))
    inv.paid_amount = overrides.get("paid_amount", Decimal("0.00"))
    inv.currency = overrides.get("currency", "USD")
    inv.notes = overrides.get("notes", None)
    inv.created_by = overrides.get("created_by", uuid.uuid4())
    return inv


class TestInvoiceGeneration:
    """Verify invoice generation from encounter creates proper line items."""

    @pytest.mark.asyncio
    async def test_generate_invoice_creates_consultation_line_item(self):
        """Invoice generation creates a consultation line item with correct total."""
        from app.modules.billing.service import BillingService

        encounter_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        patient_id = uuid.uuid4()

        # Mock DB: no duplicate invoice, encounter exists
        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # Duplicate check returns None
                result.scalar_one_or_none.return_value = None
            else:
                # Encounter lookup returns a row
                row = {"id": encounter_id, "patient_id": patient_id, "status": "completed"}
                mappings = MagicMock()
                mappings.first.return_value = row
                result.mappings.return_value = mappings
            return result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        service = BillingService()
        with patch("app.modules.billing.service._audit", _mock_audit):
            invoice = await service.generate_invoice(
                db=mock_db, encounter_id=encounter_id,
                tenant_id=tenant_id, user_id=user_id,
            )

        # Invoice was added to session
        assert mock_db.add.called
        assert invoice.status == InvoiceStatus.DRAFT
        assert invoice.total_amount == Decimal("100.00")


class TestPaymentRecording:
    """Verify payment recording updates paid_amount and transitions status."""

    @pytest.mark.asyncio
    async def test_partial_payment_sets_partially_paid(self):
        """Recording a partial payment transitions status to PARTIALLY_PAID."""
        from app.modules.billing.service import BillingService

        invoice = _mock_invoice(
            total_amount=Decimal("200.00"),
            paid_amount=Decimal("0.00"),
            status=InvoiceStatus.ISSUED,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # Payment of $50 against $200 total
        mock_data = MagicMock()
        mock_data.amount = Decimal("50.00")
        mock_data.payment_method = PaymentMethod.CASH
        mock_data.reference_number = None
        mock_data.paid_at = None
        mock_data.notes = None

        service = BillingService()
        with patch("app.modules.billing.service._audit", _mock_audit):
            await service.record_payment(
                db=mock_db, invoice_id=invoice.id,
                tenant_id=invoice.tenant_id, user_id=uuid.uuid4(),
                data=mock_data,
            )

        assert invoice.status == InvoiceStatus.PARTIALLY_PAID
        assert invoice.paid_amount == Decimal("50.00")

    @pytest.mark.asyncio
    async def test_full_payment_sets_paid(self):
        """Recording full payment transitions status to PAID."""
        from app.modules.billing.service import BillingService

        invoice = _mock_invoice(
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("0.00"),
            status=InvoiceStatus.ISSUED,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_data = MagicMock()
        mock_data.amount = Decimal("100.00")
        mock_data.payment_method = PaymentMethod.CARD
        mock_data.reference_number = "REF-001"
        mock_data.paid_at = None
        mock_data.notes = None

        service = BillingService()
        with patch("app.modules.billing.service._audit", _mock_audit):
            await service.record_payment(
                db=mock_db, invoice_id=invoice.id,
                tenant_id=invoice.tenant_id, user_id=uuid.uuid4(),
                data=mock_data,
            )

        assert invoice.status == InvoiceStatus.PAID
        assert invoice.paid_amount == Decimal("100.00")


class TestInsuranceClaims:
    """Verify insurance claim submission and denial handling."""

    @pytest.mark.asyncio
    async def test_submit_claim_creates_with_correct_fields(self):
        """Claim submission creates a claim with SUBMITTED status."""
        from app.modules.billing.service_claims import ClaimsService

        invoice = _mock_invoice(patient_id=uuid.uuid4())

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_data = MagicMock()
        mock_data.invoice_id = invoice.id
        mock_data.insurance_provider = "Test Insurance Co"
        mock_data.policy_number = "POL-12345"
        mock_data.submitted_amount = Decimal("100.00")

        service = ClaimsService()
        with patch("app.modules.billing.service_claims._audit", _mock_audit):
            claim = await service.submit_claim(
                db=mock_db, tenant_id=invoice.tenant_id,
                user_id=uuid.uuid4(), data=mock_data,
            )

        assert claim.status == ClaimStatus.SUBMITTED
        assert claim.insurance_provider == "Test Insurance Co"
        assert claim.policy_number == "POL-12345"

    @pytest.mark.asyncio
    async def test_claim_denial_updates_status_and_reason(self):
        """Denying a claim sets status to DENIED and stores denial_reason."""
        from app.modules.billing.service_claims import ClaimsService

        mock_claim = MagicMock()
        mock_claim.id = uuid.uuid4()
        mock_claim.status = ClaimStatus.PENDING_REVIEW

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_claim
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()

        mock_data = MagicMock()
        mock_data.status = ClaimStatus.DENIED
        mock_data.denial_reason = "Pre-authorization not obtained"
        mock_data.approved_amount = None
        mock_data.claim_number = None

        service = ClaimsService()
        with patch("app.modules.billing.service_claims._audit", _mock_audit):
            await service.update_claim_status(
                db=mock_db, claim_id=mock_claim.id,
                tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
                data=mock_data,
            )

        assert mock_claim.status == ClaimStatus.DENIED
        assert mock_claim.denial_reason == "Pre-authorization not obtained"


class TestVoidInvoice:
    """Verify void_invoice sets status and appends reason."""

    @pytest.mark.asyncio
    async def test_void_sets_status_to_void(self):
        """Voiding an invoice sets status to VOID."""
        from app.modules.billing.service import BillingService

        invoice = _mock_invoice(status=InvoiceStatus.ISSUED, notes=None)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()

        service = BillingService()
        with patch("app.modules.billing.service._audit", _mock_audit):
            await service.void_invoice(
                db=mock_db, invoice_id=invoice.id,
                tenant_id=invoice.tenant_id, user_id=uuid.uuid4(),
                reason="Duplicate billing",
            )

        assert invoice.status == InvoiceStatus.VOID

    @pytest.mark.asyncio
    async def test_void_already_void_raises(self):
        """Voiding an already-void invoice raises InvoiceAlreadyVoidError."""
        from app.modules.billing.service import BillingService

        invoice = _mock_invoice(status=InvoiceStatus.VOID)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        mock_db.execute.return_value = mock_result

        service = BillingService()
        with pytest.raises(InvoiceAlreadyVoidError):
            await service.void_invoice(
                db=mock_db, invoice_id=invoice.id,
                tenant_id=invoice.tenant_id, user_id=uuid.uuid4(),
                reason="Test",
            )


class TestClaimResubmission:
    """Verify claim denial and resubmission flow."""

    @pytest.mark.asyncio
    async def test_resubmit_denied_claim(self):
        """Resubmitting a denied claim sets status to RESUBMITTED."""
        from app.modules.billing.service_claims import ClaimsService

        mock_claim = MagicMock()
        mock_claim.id = uuid.uuid4()
        mock_claim.status = ClaimStatus.DENIED
        mock_claim.denial_reason = "Missing documentation"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_claim
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()

        mock_data = MagicMock()
        mock_data.status = ClaimStatus.RESUBMITTED
        mock_data.denial_reason = None
        mock_data.approved_amount = None
        mock_data.claim_number = None

        service = ClaimsService()
        with patch("app.modules.billing.service_claims._audit", _mock_audit):
            await service.update_claim_status(
                db=mock_db, claim_id=mock_claim.id,
                tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
                data=mock_data,
            )

        assert mock_claim.status == ClaimStatus.RESUBMITTED


class TestVoidInvoiceCannotModify:
    """Verify voided invoices cannot be modified (payment recording blocked)."""

    @pytest.mark.asyncio
    async def test_record_payment_on_void_invoice_raises(self):
        """Recording a payment on a voided invoice raises InvoiceAlreadyVoidError."""
        from app.modules.billing.service import BillingService

        invoice = _mock_invoice(status=InvoiceStatus.VOID)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        mock_db.execute.return_value = mock_result

        mock_data = MagicMock()
        mock_data.amount = Decimal("50.00")
        mock_data.payment_method = PaymentMethod.CASH
        mock_data.reference_number = None
        mock_data.paid_at = None
        mock_data.notes = None

        service = BillingService()
        with patch("app.modules.billing.service._audit", _mock_audit):
            with pytest.raises(InvoiceAlreadyVoidError):
                await service.record_payment(
                    db=mock_db, invoice_id=invoice.id,
                    tenant_id=invoice.tenant_id, user_id=uuid.uuid4(),
                    data=mock_data,
                )


class TestTotalAmountComputation:
    """Verify _build_line_items total matches sum of line item prices."""

    @pytest.mark.asyncio
    async def test_build_line_items_total_matches_items(self):
        """The total returned by _build_line_items equals the sum of item.total_price."""
        from app.modules.billing.service import BillingService

        service = BillingService()
        items, total = service._build_line_items(
            tenant_id=uuid.uuid4(), encounter_id=uuid.uuid4(),
        )

        computed_total = sum(item.total_price for item in items)
        assert total == computed_total
        assert isinstance(total, Decimal)
