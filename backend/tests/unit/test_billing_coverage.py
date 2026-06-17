"""
Comprehensive unit tests for billing module.

Covers:
- BillingService: generate_invoice, list_invoices, get_invoice_detail, record_payment, void_invoice
- ClaimsService: submit_claim, update_claim_status, list_claims
- Schemas: request/response validation
- Enums: all values present
- Exceptions: error conditions
"""

import uuid
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.enums import (
    ClaimStatus,
    InvoiceStatus,
    ItemType,
    PaymentMethod,
)
from app.modules.billing.exceptions import (
    DuplicateInvoiceError,
    EncounterBillingError,
    InvoiceAlreadyVoidError,
    InvoiceNotFoundError,
    ClaimNotFoundError,
    InvalidInvoiceStatusError,
)
from app.modules.billing.models import Invoice, InvoiceLineItem, Payment, InsuranceClaim
from app.modules.billing.schemas import (
    InvoiceGenerateRequest,
    InvoiceOut,
    PaymentRecordRequest,
    ClaimSubmitRequest,
    ClaimStatusUpdateRequest,
    VoidRequest,
)
from app.modules.billing.service import BillingService
from app.modules.billing.service_claims import ClaimsService


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def billing_service():
    """Instantiate BillingService for testing."""
    return BillingService()


@pytest.fixture
def claims_service():
    """Instantiate ClaimsService for testing."""
    return ClaimsService()


@pytest.fixture
def test_tenant_id():
    """Test tenant UUID."""
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def test_user_id():
    """Test user UUID."""
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def test_patient_id():
    """Test patient UUID."""
    return uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def test_encounter_id():
    """Test encounter UUID."""
    return uuid.UUID("44444444-4444-4444-4444-444444444444")


@pytest.fixture
def test_invoice_id():
    """Test invoice UUID."""
    return uuid.UUID("55555555-5555-5555-5555-555555555555")


@pytest.fixture
def mock_db():
    """Mock AsyncSession."""
    return MagicMock(spec=AsyncSession)


# ============================================================================
# BillingService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_generate_invoice_success(
    billing_service,
    mock_db,
    test_tenant_id,
    test_user_id,
    test_patient_id,
    test_encounter_id,
):
    """
    Test successful invoice generation from an encounter.
    """
    with patch("app.modules.billing.service._audit", MagicMock(log=AsyncMock())):
        # Mock the DB queries
        mock_db.execute = AsyncMock()
        
        # Mock: no existing invoice
        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        
        # Mock: encounter lookup
        enc_result = MagicMock()
        enc_result.mappings = MagicMock(return_value=MagicMock(first=MagicMock(return_value={
            "id": test_encounter_id,
            "patient_id": test_patient_id,
            "status": "completed",
        })))
        
        mock_db.execute.side_effect = [existing_result, enc_result]
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        
        request = InvoiceGenerateRequest(
            encounter_id=test_encounter_id,
            currency="USD",
            notes="Test invoice",
        )
        
        result = await billing_service.generate_invoice(
            db=mock_db,
            encounter_id=test_encounter_id,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
        )
        
        assert result is not None
        assert result.tenant_id == test_tenant_id
        assert result.patient_id == test_patient_id
        assert result.encounter_id == test_encounter_id
        assert result.status == InvoiceStatus.DRAFT
        assert result.total_amount == Decimal("100.00")
        assert result.paid_amount == Decimal("0.00")


@pytest.mark.asyncio
async def test_generate_invoice_duplicate_error(
    billing_service,
    mock_db,
    test_tenant_id,
    test_user_id,
    test_encounter_id,
    test_invoice_id,
):
    """
    Test that duplicate invoice for same encounter raises DuplicateInvoiceError.
    """
    with patch("app.modules.billing.service._audit", MagicMock(log=AsyncMock())):
        mock_db.execute = AsyncMock()
        
        # Mock: existing invoice found
        existing_invoice = MagicMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=existing_invoice)
        
        mock_db.execute.return_value = existing_result
        
        with pytest.raises(DuplicateInvoiceError):
            await billing_service.generate_invoice(
                db=mock_db,
                encounter_id=test_encounter_id,
                tenant_id=test_tenant_id,
                user_id=test_user_id,
            )


@pytest.mark.asyncio
async def test_generate_invoice_encounter_not_found(
    billing_service,
    mock_db,
    test_tenant_id,
    test_user_id,
    test_encounter_id,
):
    """
    Test that missing encounter raises EncounterBillingError.
    """
    with patch("app.modules.billing.service._audit", MagicMock(log=AsyncMock())):
        mock_db.execute = AsyncMock()
        
        # Mock: no existing invoice
        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        
        # Mock: no encounter found
        enc_result = MagicMock()
        enc_result.mappings = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
        
        mock_db.execute.side_effect = [existing_result, enc_result]
        
        with pytest.raises(EncounterBillingError):
            await billing_service.generate_invoice(
                db=mock_db,
                encounter_id=test_encounter_id,
                tenant_id=test_tenant_id,
                user_id=test_user_id,
            )


@pytest.mark.asyncio
async def test_list_invoices_filtered_by_status(
    billing_service,
    mock_db,
    test_tenant_id,
):
    """
    Test list_invoices with status filter.
    """
    # Create mock invoices
    invoice1 = MagicMock(spec=Invoice)
    invoice1.id = uuid.uuid4()
    invoice1.status = InvoiceStatus.PAID
    
    invoice2 = MagicMock(spec=Invoice)
    invoice2.id = uuid.uuid4()
    invoice2.status = InvoiceStatus.DRAFT
    
    mock_db.execute = AsyncMock()
    
    # Mock count query
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=2)
    
    # Mock list query
    list_result = MagicMock()
    list_result.scalars = MagicMock(return_value=[invoice1, invoice2])
    
    mock_db.execute.side_effect = [count_result, list_result]
    
    invoices, total = await billing_service.list_invoices(
        db=mock_db,
        tenant_id=test_tenant_id,
        status=InvoiceStatus.PAID,
        limit=25,
        offset=0,
    )
    
    assert total == 2
    assert len(invoices) == 2


@pytest.mark.asyncio
async def test_list_invoices_filtered_by_patient(
    billing_service,
    mock_db,
    test_tenant_id,
    test_patient_id,
):
    """
    Test list_invoices with patient_id filter.
    """
    invoice = MagicMock(spec=Invoice)
    invoice.id = uuid.uuid4()
    
    mock_db.execute = AsyncMock()
    
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=1)
    
    list_result = MagicMock()
    list_result.scalars = MagicMock(return_value=[invoice])
    
    mock_db.execute.side_effect = [count_result, list_result]
    
    invoices, total = await billing_service.list_invoices(
        db=mock_db,
        tenant_id=test_tenant_id,
        patient_id=test_patient_id,
        limit=25,
        offset=0,
    )
    
    assert total == 1


@pytest.mark.asyncio
async def test_get_invoice_detail_success(
    billing_service,
    mock_db,
    test_invoice_id,
):
    """
    Test retrieving invoice detail with line items and payments.
    """
    invoice = MagicMock(spec=Invoice)
    invoice.id = test_invoice_id
    invoice.line_items = []
    invoice.payments = []
    invoice.claims = []
    
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=invoice)
    mock_db.execute.return_value = result
    
    found = await billing_service.get_invoice_detail(
        db=mock_db,
        invoice_id=test_invoice_id,
    )
    
    assert found.id == test_invoice_id


@pytest.mark.asyncio
async def test_get_invoice_detail_not_found(
    billing_service,
    mock_db,
    test_invoice_id,
):
    """
    Test that missing invoice raises InvoiceNotFoundError.
    """
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    
    with pytest.raises(InvoiceNotFoundError):
        await billing_service.get_invoice_detail(
            db=mock_db,
            invoice_id=test_invoice_id,
        )


@pytest.mark.asyncio
async def test_record_payment_success(
    billing_service,
    mock_db,
    test_invoice_id,
    test_tenant_id,
    test_user_id,
):
    """
    Test successful payment recording against an invoice.
    """
    with patch("app.modules.billing.service._audit", MagicMock(log=AsyncMock())):
        invoice = MagicMock(spec=Invoice)
        invoice.id = test_invoice_id
        invoice.status = InvoiceStatus.DRAFT
        invoice.total_amount = Decimal("100.00")
        invoice.paid_amount = Decimal("0.00")
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=invoice)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        
        payment_request = PaymentRecordRequest(
            amount=Decimal("50.00"),
            payment_method=PaymentMethod.CASH,
            reference_number="CASH-001",
        )
        
        payment = await billing_service.record_payment(
            db=mock_db,
            invoice_id=test_invoice_id,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
            data=payment_request,
        )
        
        assert payment is not None
        assert payment.amount == Decimal("50.00")
        assert payment.payment_method == PaymentMethod.CASH


@pytest.mark.asyncio
async def test_record_payment_on_void_invoice_raises_error(
    billing_service,
    mock_db,
    test_invoice_id,
    test_tenant_id,
    test_user_id,
):
    """
    Test that recording payment on a voided invoice raises InvoiceAlreadyVoidError.
    """
    invoice = MagicMock(spec=Invoice)
    invoice.status = InvoiceStatus.VOID
    
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=invoice)
    mock_db.execute.return_value = result
    
    payment_request = PaymentRecordRequest(
        amount=Decimal("50.00"),
        payment_method=PaymentMethod.CASH,
    )
    
    with pytest.raises(InvoiceAlreadyVoidError):
        await billing_service.record_payment(
            db=mock_db,
            invoice_id=test_invoice_id,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
            data=payment_request,
        )


@pytest.mark.asyncio
async def test_void_invoice_success(
    billing_service,
    mock_db,
    test_invoice_id,
    test_tenant_id,
    test_user_id,
):
    """
    Test successful invoice voiding.
    """
    with patch("app.modules.billing.service._audit", MagicMock(log=AsyncMock())):
        invoice = MagicMock(spec=Invoice)
        invoice.id = test_invoice_id
        invoice.status = InvoiceStatus.DRAFT
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=invoice)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        
        voided = await billing_service.void_invoice(
            db=mock_db,
            invoice_id=test_invoice_id,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
            reason="Test void reason",
        )
        
        assert voided.status == InvoiceStatus.VOID


# ============================================================================
# ClaimsService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_submit_claim_success(
    claims_service,
    mock_db,
    test_tenant_id,
    test_user_id,
    test_invoice_id,
    test_patient_id,
):
    """
    Test successful insurance claim submission.
    """
    with patch("app.modules.billing.service_claims._audit", MagicMock(log=AsyncMock())):
        invoice = MagicMock(spec=Invoice)
        invoice.id = test_invoice_id
        invoice.patient_id = test_patient_id
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=invoice)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        
        claim_request = ClaimSubmitRequest(
            invoice_id=test_invoice_id,
            insurance_provider="Test Insurance Co.",
            policy_number="POL-123456",
            submitted_amount=Decimal("100.00"),
        )
        
        claim = await claims_service.submit_claim(
            db=mock_db,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
            data=claim_request,
        )
        
        assert claim is not None
        assert claim.status == ClaimStatus.SUBMITTED
        assert claim.submitted_amount == Decimal("100.00")


@pytest.mark.asyncio
async def test_submit_claim_invoice_not_found(
    claims_service,
    mock_db,
    test_tenant_id,
    test_user_id,
    test_invoice_id,
):
    """
    Test that submitting claim for missing invoice raises InvoiceNotFoundError.
    """
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    
    claim_request = ClaimSubmitRequest(
        invoice_id=test_invoice_id,
        insurance_provider="Test Insurance",
        policy_number="POL-123",
        submitted_amount=Decimal("100.00"),
    )
    
    with pytest.raises(InvoiceNotFoundError):
        await claims_service.submit_claim(
            db=mock_db,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
            data=claim_request,
        )


@pytest.mark.asyncio
async def test_update_claim_status_to_approved(
    claims_service,
    mock_db,
    test_tenant_id,
    test_user_id,
):
    """
    Test updating claim status to APPROVED with amount.
    """
    with patch("app.modules.billing.service_claims._audit", MagicMock(log=AsyncMock())):
        claim = MagicMock(spec=InsuranceClaim)
        claim.id = uuid.uuid4()
        claim.status = ClaimStatus.PENDING_REVIEW
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=claim)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        
        update_request = ClaimStatusUpdateRequest(
            status=ClaimStatus.APPROVED,
            approved_amount=Decimal("100.00"),
        )
        
        updated = await claims_service.update_claim_status(
            db=mock_db,
            claim_id=claim.id,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
            data=update_request,
        )
        
        assert updated.status == ClaimStatus.APPROVED
        assert updated.approved_amount == Decimal("100.00")


@pytest.mark.asyncio
async def test_update_claim_status_to_partially_approved(
    claims_service,
    mock_db,
    test_tenant_id,
    test_user_id,
):
    """
    Test partial approval with reduced amount.
    """
    with patch("app.modules.billing.service_claims._audit", MagicMock(log=AsyncMock())):
        claim = MagicMock(spec=InsuranceClaim)
        claim.id = uuid.uuid4()
        claim.status = ClaimStatus.PENDING_REVIEW
        claim.submitted_amount = Decimal("200.00")
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=claim)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        
        update_request = ClaimStatusUpdateRequest(
            status=ClaimStatus.PARTIALLY_APPROVED,
            approved_amount=Decimal("100.00"),
        )
        
        updated = await claims_service.update_claim_status(
            db=mock_db,
            claim_id=claim.id,
            tenant_id=test_tenant_id,
            user_id=test_user_id,
            data=update_request,
        )
        
        assert updated.status == ClaimStatus.PARTIALLY_APPROVED
        assert updated.approved_amount == Decimal("100.00")


@pytest.mark.asyncio
async def test_list_claims(
    claims_service,
    mock_db,
    test_tenant_id,
):
    """
    Test listing claims for a tenant.
    """
    claim1 = MagicMock(spec=InsuranceClaim)
    claim1.id = uuid.uuid4()
    claim1.status = ClaimStatus.APPROVED
    
    claim2 = MagicMock(spec=InsuranceClaim)
    claim2.id = uuid.uuid4()
    claim2.status = ClaimStatus.PENDING_REVIEW
    
    mock_db.execute = AsyncMock()
    
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=2)
    
    list_result = MagicMock()
    list_result.scalars = MagicMock(return_value=[claim1, claim2])
    
    mock_db.execute.side_effect = [count_result, list_result]
    
    claims, total = await claims_service.list_claims(
        db=mock_db,
        tenant_id=test_tenant_id,
        limit=25,
        offset=0,
    )
    
    assert total == 2
    assert len(claims) == 2


# ============================================================================
# Schema Validation Tests
# ============================================================================

def test_invoice_generate_request_valid():
    """Test valid invoice generation request."""
    req = InvoiceGenerateRequest(
        encounter_id=uuid.uuid4(),
        currency="USD",
        notes="Valid invoice",
    )
    assert req.currency == "USD"


def test_invoice_generate_request_defaults():
    """Test invoice request defaults."""
    req = InvoiceGenerateRequest(
        encounter_id=uuid.uuid4(),
    )
    assert req.currency == "USD"
    assert req.notes is None


def test_payment_record_request_valid():
    """Test valid payment record request."""
    req = PaymentRecordRequest(
        amount=Decimal("50.00"),
        payment_method=PaymentMethod.CARD,
        reference_number="CC-12345",
    )
    assert req.amount == Decimal("50.00")
    assert req.payment_method == PaymentMethod.CARD


def test_payment_record_request_rejects_negative_amount():
    """Test that negative amounts are rejected."""
    with pytest.raises(ValueError):
        PaymentRecordRequest(
            amount=Decimal("-10.00"),
            payment_method=PaymentMethod.CASH,
        )


def test_claim_submit_request_valid():
    """Test valid claim submission request."""
    req = ClaimSubmitRequest(
        invoice_id=uuid.uuid4(),
        insurance_provider="Insurance Corp",
        policy_number="POL-999",
        submitted_amount=Decimal("500.00"),
    )
    assert req.submitted_amount == Decimal("500.00")


def test_claim_submit_request_rejects_zero_amount():
    """Test that zero amounts are rejected."""
    with pytest.raises(ValueError):
        ClaimSubmitRequest(
            invoice_id=uuid.uuid4(),
            insurance_provider="Insurance Corp",
            policy_number="POL-999",
            submitted_amount=Decimal("0.00"),
        )


def test_void_request_valid():
    """Test valid void request."""
    req = VoidRequest(reason="Invoice duplicate")
    assert req.reason == "Invoice duplicate"


def test_void_request_rejects_short_reason():
    """Test that void reason must be at least 5 chars."""
    with pytest.raises(ValueError):
        VoidRequest(reason="Bad")


# ============================================================================
# Enum Tests
# ============================================================================

def test_invoice_status_all_values():
    """Test all InvoiceStatus enum values exist."""
    expected = {
        InvoiceStatus.DRAFT,
        InvoiceStatus.ISSUED,
        InvoiceStatus.PAID,
        InvoiceStatus.PARTIALLY_PAID,
        InvoiceStatus.OVERDUE,
        InvoiceStatus.CANCELLED,
        InvoiceStatus.VOID,
    }
    actual = set(InvoiceStatus)
    assert expected == actual


def test_payment_method_all_values():
    """Test all PaymentMethod enum values exist."""
    expected = {
        PaymentMethod.CASH,
        PaymentMethod.CARD,
        PaymentMethod.BANK_TRANSFER,
        PaymentMethod.MOBILE_MONEY,
        PaymentMethod.INSURANCE,
    }
    actual = set(PaymentMethod)
    assert expected == actual


def test_item_type_all_values():
    """Test all ItemType enum values exist."""
    expected = {
        ItemType.CONSULTATION,
        ItemType.PROCEDURE,
        ItemType.LAB_TEST,
        ItemType.MEDICATION,
        ItemType.SUPPLY,
        ItemType.OTHER,
    }
    actual = set(ItemType)
    assert expected == actual


def test_claim_status_all_values():
    """Test all ClaimStatus enum values exist."""
    expected = {
        ClaimStatus.SUBMITTED,
        ClaimStatus.PENDING_REVIEW,
        ClaimStatus.APPROVED,
        ClaimStatus.PARTIALLY_APPROVED,
        ClaimStatus.DENIED,
        ClaimStatus.RESUBMITTED,
    }
    actual = set(ClaimStatus)
    assert expected == actual


# ============================================================================
# Exception Tests
# ============================================================================

def test_invoice_not_found_error():
    """Test InvoiceNotFoundError message."""
    invoice_id = uuid.uuid4()
    exc = InvoiceNotFoundError(invoice_id)
    assert "invoice" in str(exc).lower()


def test_duplicate_invoice_error():
    """Test DuplicateInvoiceError message."""
    encounter_id = uuid.uuid4()
    exc = DuplicateInvoiceError(encounter_id)
    assert "already exists" in str(exc).lower() or "invoice" in str(exc).lower()


def test_invoice_already_void_error():
    """Test InvoiceAlreadyVoidError message."""
    invoice_id = uuid.uuid4()
    exc = InvoiceAlreadyVoidError(invoice_id)
    assert "void" in str(exc).lower()


def test_claim_not_found_error():
    """Test ClaimNotFoundError message."""
    claim_id = uuid.uuid4()
    exc = ClaimNotFoundError(claim_id)
    assert "claim" in str(exc).lower()
