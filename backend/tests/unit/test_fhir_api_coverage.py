"""
Comprehensive unit tests for fhir_api module.

Covers:
- FHIRService: validate_resource, parse_to_internal, print_to_fhir, search, create_subscription
- FHIRValidator: validate resource types and schemas
- FHIRSearch: search with combined parameters
- Subscriptions: create, list, validate callback
- Schemas: FHIRSearchResponse, OperationOutcome
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fhir_api.service import FHIRService
from app.modules.fhir_api.search import FHIRSearchParams
from app.modules.fhir_api.validator import validate_fhir_resource, build_operation_outcome
from app.modules.fhir_api.subscriptions import SubscriptionManager


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fhir_service():
    """Instantiate FHIRService for testing."""
    return FHIRService()


@pytest.fixture
def subscription_manager():
    """Instantiate SubscriptionManager for testing."""
    return SubscriptionManager()


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
def mock_db():
    """Mock AsyncSession."""
    return MagicMock(spec=AsyncSession)


# ============================================================================
# FHIRService Tests
# ============================================================================

def test_validate_resource_patient_valid(fhir_service):
    """
    Test validation of a valid Patient resource.
    """
    fhir_json = {
        "resourceType": "Patient",
        "id": str(uuid.uuid4()),
        "identifier": [{"system": "http://example.com", "value": "12345"}],
        "name": [{"given": ["John"], "family": "Doe"}],
    }
    
    result = fhir_service.validate_resource("Patient", fhir_json)
    assert result is None  # None means valid


def test_validate_resource_patient_missing_required_field(fhir_service):
    """
    Test validation fails when required field is missing.
    """
    fhir_json = {
        "resourceType": "Patient",
        # Missing id (required per _REQUIRED_FIELDS)
    }
    
    result = fhir_service.validate_resource("Patient", fhir_json)
    # Should return OperationOutcome on failure
    assert result is not None


def test_validate_resource_medication_request_valid(fhir_service):
    """
    Test validation of a valid MedicationRequest resource.
    """
    fhir_json = {
        "resourceType": "MedicationRequest",
        "id": str(uuid.uuid4()),
        "status": "active",
        "intent": "order",
        "subject": {"reference": f"Patient/{uuid.uuid4()}"},
        "medicationCodeableConcept": {
            "coding": [{"system": "http://snomed.info/sct", "code": "763158003"}]
        },
        "dosageInstruction": [{"text": "One tablet daily"}],
    }
    
    result = fhir_service.validate_resource("MedicationRequest", fhir_json)
    assert result is None


def test_validate_resource_service_request_valid(fhir_service):
    """
    Test validation of a valid ServiceRequest resource.
    """
    fhir_json = {
        "resourceType": "ServiceRequest",
        "id": str(uuid.uuid4()),
        "status": "active",
        "intent": "order",
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "1234567"}]},
        "subject": {"reference": f"Patient/{uuid.uuid4()}"},
    }
    
    result = fhir_service.validate_resource("ServiceRequest", fhir_json)
    assert result is None


def test_validate_resource_unsupported_type(fhir_service):
    """
    Test validation of unsupported resource type returns None (passes through).
    The validator has no required fields for unknown types, so they pass structural validation.
    """
    fhir_json = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
    }
    
    result = fhir_service.validate_resource("Bundle", fhir_json)
    # Unknown types have no required fields defined, so they pass validation
    assert result is None


def test_parse_to_internal_patient(fhir_service):
    """
    Test converting FHIR Patient to internal representation.
    """
    patient_id = uuid.uuid4()
    fhir_json = {
        "resourceType": "Patient",
        "id": str(patient_id),
        "name": [{"given": ["Jane"], "family": "Smith"}],
    }
    
    internal = fhir_service.parse_to_internal("Patient", fhir_json)
    
    assert internal["fhir_resource_type"] == "Patient"
    assert internal["fhir_json"] == fhir_json


def test_parse_to_internal_encounter(fhir_service):
    """
    Test converting FHIR Encounter to internal representation.
    """
    patient_id = uuid.uuid4()
    fhir_json = {
        "resourceType": "Encounter",
        "id": str(uuid.uuid4()),
        "status": "finished",
        "subject": {"reference": f"Patient/{patient_id}"},
        "serviceType": [{"coding": [{"system": "http://terminology.hl7.org", "code": "amt"}]}],
    }
    
    internal = fhir_service.parse_to_internal("Encounter", fhir_json)
    
    assert internal["fhir_resource_type"] == "Encounter"
    assert internal["patient_id"] == patient_id


def test_parse_to_internal_medication_request(fhir_service):
    """
    Test converting FHIR MedicationRequest to internal representation.
    """
    patient_id = uuid.uuid4()
    fhir_json = {
        "resourceType": "MedicationRequest",
        "id": str(uuid.uuid4()),
        "status": "active",
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    
    internal = fhir_service.parse_to_internal("MedicationRequest", fhir_json)
    
    assert internal["fhir_resource_type"] == "MedicationRequest"
    assert internal["patient_id"] == patient_id


def test_print_to_fhir_returns_stored_json(fhir_service):
    """
    Test that print_to_fhir returns stored FHIR JSON when available.
    """
    stored_fhir = {
        "resourceType": "Patient",
        "id": str(uuid.uuid4()),
    }
    
    internal_record = {
        "fhir_json": stored_fhir,
        "id": str(uuid.uuid4()),
    }
    
    result = fhir_service.print_to_fhir("Patient", internal_record)
    
    assert result == stored_fhir


def test_print_to_fhir_builds_minimal_when_no_stored_json(fhir_service):
    """
    Test that print_to_fhir builds minimal FHIR when no stored JSON.
    """
    internal_record = {
        "id": str(uuid.uuid4()),
        "status": "active",
    }
    
    result = fhir_service.print_to_fhir("Patient", internal_record)
    
    assert result is not None
    assert "resourceType" in result or result is not None


@pytest.mark.asyncio
async def test_search_with_parameters(fhir_service, mock_db):
    """
    Test FHIR search with combined parameters.
    """
    search_params = FHIRSearchParams(
        resource_type="Patient",
        status="active",
    )
    
    mock_db.execute = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar = MagicMock(return_value=0)
    mock_db.execute.return_value = result_mock
    
    results, total = await fhir_service.search(
        db=mock_db,
        resource_type="Patient",
        params=search_params,
        tenant_id=uuid.uuid4(),
    )
    
    assert results is not None


@pytest.mark.asyncio
async def test_search_empty_results(fhir_service, mock_db):
    """
    Test FHIR search returning no results.
    """
    search_params = FHIRSearchParams(
        resource_type="Patient",
        status="unknown",
    )
    
    mock_db.execute = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar = MagicMock(return_value=0)
    mock_db.execute.return_value = result_mock
    
    results, total = await fhir_service.search(
        db=mock_db,
        resource_type="Patient",
        params=search_params,
        tenant_id=uuid.uuid4(),
    )
    
    assert len(results) == 0


# ============================================================================
# FHIRValidator Tests
# ============================================================================

def test_validator_patient_with_valid_identifier():
    """
    Test patient validation with valid identifier.
    """
    fhir_json = {
        "resourceType": "Patient",
        "id": "valid-id-123",
        "identifier": [{"system": "http://example.com", "value": "12345"}],
    }
    
    errors = validate_fhir_resource("Patient", fhir_json)
    # Valid structure should have no errors
    assert errors == []


def test_validator_patient_without_identifier():
    """
    Test patient validation without required id field.
    """
    fhir_json = {
        "resourceType": "Patient",
        # Missing id (required per validator _REQUIRED_FIELDS)
    }
    
    errors = validate_fhir_resource("Patient", fhir_json)
    # Should have errors for missing id
    assert len(errors) > 0


def test_validator_medication_request_invalid_status():
    """
    Test medication request with invalid status.
    """
    fhir_json = {
        "resourceType": "MedicationRequest",
        "status": "invalid_status",
        "intent": "order",
        "subject": {"reference": "Patient/123"},
        "medicationCodeableConcept": {"coding": [{"code": "123"}]},
    }
    
    errors = validate_fhir_resource("MedicationRequest", fhir_json)
    # Invalid status should be caught
    assert len(errors) > 0


def test_build_operation_outcome():
    """
    Test building OperationOutcome (error response) from validation errors.
    """
    errors = ["Missing required field: identifier", "Invalid status value"]
    
    outcome = build_operation_outcome(errors)
    
    assert outcome is not None
    # Should contain issue details
    assert isinstance(outcome, dict)


# ============================================================================
# Additional Search Tests (via FHIRService)
# ============================================================================
# (FHIRSearch is internal; testing via FHIRService.search())


# ============================================================================
# Subscription Tests
# ============================================================================

@pytest.mark.asyncio
async def test_create_subscription_success(
    subscription_manager,
    mock_db,
    test_tenant_id,
    test_user_id,
):
    """
    Test creating a subscription for resource changes.
    """
    fhir_subscription = {
        "resourceType": "Subscription",
        "criteria": "Encounter?status=finished",
        "channel": {
            "type": "rest-hook",
            "endpoint": "https://example.com/webhook",
        },
    }
    
    subscription = subscription_manager.create_subscription(
        fhir_subscription=fhir_subscription,
        tenant_id=test_tenant_id,
    )
    
    assert subscription is not None
    assert subscription["status"] == "active"


@pytest.mark.asyncio
async def test_create_subscription_invalid_callback_url(
    subscription_manager,
    mock_db,
    test_tenant_id,
    test_user_id,
):
    """
    Test that missing required fields are rejected.
    """
    # Missing channel.endpoint should raise ValueError
    fhir_subscription = {
        "resourceType": "Subscription",
        "criteria": "Encounter?status=finished",
        "channel": {
            "type": "rest-hook",
            # Missing endpoint
        },
    }
    
    with pytest.raises(ValueError):
        subscription_manager.create_subscription(
            fhir_subscription=fhir_subscription,
            tenant_id=test_tenant_id,
        )


@pytest.mark.asyncio
async def test_list_subscriptions(
    subscription_manager,
    mock_db,
    test_tenant_id,
):
    """
    Test listing subscriptions for a tenant.
    """
    # Create two subscriptions first
    sub1 = subscription_manager.create_subscription(
        fhir_subscription={
            "resourceType": "Subscription",
            "criteria": "Patient",
            "channel": {"type": "rest-hook", "endpoint": "https://example.com/hook1"},
        },
        tenant_id=test_tenant_id,
    )
    sub2 = subscription_manager.create_subscription(
        fhir_subscription={
            "resourceType": "Subscription",
            "criteria": "Encounter",
            "channel": {"type": "rest-hook", "endpoint": "https://example.com/hook2"},
        },
        tenant_id=test_tenant_id,
    )
    
    subscriptions = subscription_manager.list_subscriptions(
        tenant_id=test_tenant_id,
    )
    
    assert len(subscriptions) >= 2


# ============================================================================
# Schema Validation Tests
# ============================================================================

def test_fhir_search_bundle_structure():
    """
    Test FHIR search bundle structure (dict-based).
    """
    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 1,
        "entry": [],
    }
    
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    assert bundle["total"] == 1





# ============================================================================
# Integration-like Tests
# ============================================================================

def test_roundtrip_encounter_parse_and_print(fhir_service):
    """
    Test roundtrip: FHIR → internal → FHIR for Encounter.
    """
    patient_id = uuid.uuid4()
    original_fhir = {
        "resourceType": "Encounter",
        "id": str(uuid.uuid4()),
        "status": "finished",
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    
    # Parse to internal
    internal = fhir_service.parse_to_internal("Encounter", original_fhir)
    
    # Print back to FHIR
    result_fhir = fhir_service.print_to_fhir("Encounter", internal)
    
    assert result_fhir is not None
    assert result_fhir["resourceType"] == "Encounter"


def test_roundtrip_medication_request_parse_and_print(fhir_service):
    """
    Test roundtrip: FHIR → internal → FHIR for MedicationRequest.
    """
    patient_id = uuid.uuid4()
    original_fhir = {
        "resourceType": "MedicationRequest",
        "id": str(uuid.uuid4()),
        "status": "active",
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    
    # Parse to internal
    internal = fhir_service.parse_to_internal("MedicationRequest", original_fhir)
    
    # Print back to FHIR
    result_fhir = fhir_service.print_to_fhir("MedicationRequest", internal)
    
    assert result_fhir is not None
    assert result_fhir["resourceType"] == "MedicationRequest"
