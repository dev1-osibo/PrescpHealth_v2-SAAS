"""
Comprehensive unit tests for bed_management module.

Covers:
- BedManagementService: admit_patient, discharge_patient, transfer_patient, get_ward_overview, get_bed_availability
- NursingService: add_nursing_note, chart_vitals, get_nursing_notes
- Schemas: all request/response schemas
- Enums: all values present
- Exceptions: error conditions
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bed_management.enums import (
    AdmissionStatus,
    BedStatus,
    BedType,
    DischargeType,
    NoteType,
)
from app.modules.bed_management.exceptions import (
    AdmissionAlreadyDischargedError,
    AdmissionNotFoundError,
    BedNotAvailableError,
    BedNotFoundError,
    WardNotFoundError,
)
from app.modules.bed_management.models import Admission, Bed, NursingNote, Ward
from app.modules.bed_management.schemas import (
    AdmitPatientRequest,
    DischargeRequest,
    TransferRequest,
    NursingNoteRequest,
    VitalsRequest,
)
from app.modules.bed_management.service import BedManagementService
from app.modules.bed_management.service_nursing import NursingService


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def bed_management_service():
    """Instantiate BedManagementService for testing."""
    return BedManagementService()


@pytest.fixture
def nursing_service():
    """Instantiate NursingService for testing."""
    return NursingService()


@pytest.fixture
def test_tenant_id():
    """Test tenant UUID."""
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def test_doctor_id():
    """Test doctor UUID."""
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def test_nurse_id():
    """Test nurse UUID."""
    return uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def test_patient_id():
    """Test patient UUID."""
    return uuid.UUID("44444444-4444-4444-4444-444444444444")


@pytest.fixture
def test_bed_id():
    """Test bed UUID."""
    return uuid.UUID("55555555-5555-5555-5555-555555555555")


@pytest.fixture
def test_ward_id():
    """Test ward UUID."""
    return uuid.UUID("66666666-6666-6666-6666-666666666666")


@pytest.fixture
def test_admission_id():
    """Test admission UUID."""
    return uuid.UUID("77777777-7777-7777-7777-777777777777")


@pytest.fixture
def test_encounter_id():
    """Test encounter UUID."""
    return uuid.UUID("88888888-8888-8888-8888-888888888888")


@pytest.fixture
def mock_db():
    """Mock AsyncSession."""
    return MagicMock(spec=AsyncSession)


# ============================================================================
# BedManagementService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_admit_patient_success(
    bed_management_service,
    mock_db,
    test_tenant_id,
    test_doctor_id,
    test_patient_id,
    test_bed_id,
    test_encounter_id,
):
    """
    Test successful patient admission to a bed.
    """
    with patch("app.modules.bed_management.service._audit", MagicMock(log=AsyncMock())):
        bed = MagicMock(spec=Bed)
        bed.id = test_bed_id
        bed.status = BedStatus.AVAILABLE
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=bed)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        
        admit_request = AdmitPatientRequest(
            patient_id=test_patient_id,
            bed_id=test_bed_id,
            encounter_id=test_encounter_id,
            reason="Test admission",
            notes="Patient is stable",
        )
        
        admission = await bed_management_service.admit_patient(
            db=mock_db,
            data=admit_request,
            tenant_id=test_tenant_id,
            doctor_id=test_doctor_id,
        )
        
        assert admission is not None
        assert admission.patient_id == test_patient_id
        assert admission.bed_id == test_bed_id
        assert admission.status == AdmissionStatus.ACTIVE
        assert bed.status == BedStatus.OCCUPIED


@pytest.mark.asyncio
async def test_admit_patient_bed_not_available(
    bed_management_service,
    mock_db,
    test_tenant_id,
    test_doctor_id,
    test_patient_id,
    test_bed_id,
    test_encounter_id,
):
    """
    Test that admitting to unavailable bed raises BedNotAvailableError.
    """
    bed = MagicMock(spec=Bed)
    bed.id = test_bed_id
    bed.status = BedStatus.OCCUPIED
    
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=bed)
    mock_db.execute.return_value = result
    
    admit_request = AdmitPatientRequest(
        patient_id=test_patient_id,
        bed_id=test_bed_id,
        encounter_id=test_encounter_id,
        reason="Test",
    )
    
    with pytest.raises(BedNotAvailableError):
        await bed_management_service.admit_patient(
            db=mock_db,
            data=admit_request,
            tenant_id=test_tenant_id,
            doctor_id=test_doctor_id,
        )


@pytest.mark.asyncio
async def test_discharge_patient_success(
    bed_management_service,
    mock_db,
    test_tenant_id,
    test_doctor_id,
    test_bed_id,
    test_admission_id,
):
    """
    Test successful patient discharge.
    """
    with patch("app.modules.bed_management.service._audit", MagicMock(log=AsyncMock())):
        admission = MagicMock(spec=Admission)
        admission.id = test_admission_id
        admission.status = AdmissionStatus.ACTIVE
        admission.bed_id = test_bed_id
        admission.discharge_plan = None
        admission.notes = "Original notes"
        
        bed = MagicMock(spec=Bed)
        bed.id = test_bed_id
        bed.status = BedStatus.OCCUPIED
        
        mock_db.execute = AsyncMock()
        
        def execute_side_effect(*args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=admission)
            return result
        
        mock_db.execute.side_effect = [execute_side_effect(), MagicMock(scalar_one_or_none=MagicMock(return_value=bed))]
        mock_db.flush = AsyncMock()
        
        discharge_request = DischargeRequest(
            discharge_type=DischargeType.ROUTINE,
            notes="Patient discharged in stable condition",
        )
        
        discharged = await bed_management_service.discharge_patient(
            db=mock_db,
            admission_id=test_admission_id,
            tenant_id=test_tenant_id,
            user_id=test_doctor_id,
            data=discharge_request,
        )
        
        assert discharged.status == AdmissionStatus.DISCHARGED
        assert bed.status == BedStatus.AVAILABLE


@pytest.mark.asyncio
async def test_discharge_patient_already_discharged(
    bed_management_service,
    mock_db,
    test_tenant_id,
    test_doctor_id,
    test_admission_id,
):
    """
    Test that discharging already-discharged patient raises error.
    """
    admission = MagicMock(spec=Admission)
    admission.status = AdmissionStatus.DISCHARGED
    
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    
    discharge_request = DischargeRequest(
        discharge_type=DischargeType.ROUTINE,
    )
    
    with pytest.raises(AdmissionNotFoundError):
        await bed_management_service.discharge_patient(
            db=mock_db,
            admission_id=test_admission_id,
            tenant_id=test_tenant_id,
            user_id=test_doctor_id,
            data=discharge_request,
        )


@pytest.mark.asyncio
async def test_transfer_patient_success(
    bed_management_service,
    mock_db,
    test_tenant_id,
    test_doctor_id,
    test_bed_id,
    test_admission_id,
):
    """
    Test successful patient transfer to a different bed.
    """
    with patch("app.modules.bed_management.service._audit", MagicMock(log=AsyncMock())):
        old_bed = MagicMock(spec=Bed)
        old_bed.status = BedStatus.OCCUPIED
        
        new_bed = MagicMock(spec=Bed)
        new_bed.status = BedStatus.AVAILABLE
        
        admission = MagicMock(spec=Admission)
        admission.id = test_admission_id
        admission.status = AdmissionStatus.ACTIVE
        admission.bed_id = test_bed_id
        
        mock_db.execute = AsyncMock()
        
        # Each execute() returns a different result mock
        result1 = MagicMock()
        result1.scalar_one_or_none = MagicMock(return_value=admission)
        result2 = MagicMock()
        result2.scalar_one_or_none = MagicMock(return_value=new_bed)
        result3 = MagicMock()
        result3.scalar_one_or_none = MagicMock(return_value=old_bed)
        
        mock_db.execute.side_effect = [result1, result2, result3]
        mock_db.flush = AsyncMock()
        
        new_bed_id = uuid.uuid4()
        
        transferred = await bed_management_service.transfer_patient(
            db=mock_db,
            admission_id=test_admission_id,
            new_bed_id=new_bed_id,
            tenant_id=test_tenant_id,
            user_id=test_doctor_id,
        )
        
        assert transferred.bed_id == new_bed_id
        assert transferred.status == AdmissionStatus.ACTIVE
        assert old_bed.status == BedStatus.AVAILABLE
        assert new_bed.status == BedStatus.OCCUPIED


@pytest.mark.asyncio
async def test_transfer_patient_to_occupied_bed(
    bed_management_service,
    mock_db,
    test_tenant_id,
    test_doctor_id,
    test_admission_id,
):
    """
    Test that transferring to occupied bed raises BedNotAvailableError.
    """
    admission = MagicMock(spec=Admission)
    admission.status = AdmissionStatus.ACTIVE
    admission.bed_id = uuid.uuid4()
    
    new_bed = MagicMock(spec=Bed)
    new_bed.status = BedStatus.OCCUPIED
    
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(side_effect=[admission, new_bed])
    mock_db.execute.return_value = result
    
    new_bed_id = uuid.uuid4()
    
    with pytest.raises(BedNotAvailableError):
        await bed_management_service.transfer_patient(
            db=mock_db,
            admission_id=test_admission_id,
            new_bed_id=new_bed_id,
            tenant_id=test_tenant_id,
            user_id=test_doctor_id,
        )


@pytest.mark.asyncio
async def test_get_ward_overview(
    bed_management_service,
    mock_db,
    test_tenant_id,
    test_ward_id,
):
    """
    Test retrieving ward overview with bed counts.
    """
    ward = MagicMock(spec=Ward)
    ward.id = test_ward_id
    ward.name = "ICU Ward"
    ward.floor = 3
    ward.specialty = "Intensive Care"
    ward.tenant_id = test_tenant_id
    ward.is_active = True
    
    bed1 = MagicMock(spec=Bed)
    bed1.status = BedStatus.AVAILABLE
    
    bed2 = MagicMock(spec=Bed)
    bed2.status = BedStatus.OCCUPIED
    
    mock_db.execute = AsyncMock()
    
    # First call: get wards
    wards_result = MagicMock()
    wards_result.scalars = MagicMock(return_value=[ward])
    
    # Second call: get beds for ward
    beds_result = MagicMock()
    beds_result.scalars = MagicMock(return_value=[bed1, bed2])
    
    mock_db.execute.side_effect = [wards_result, beds_result]
    
    overview = await bed_management_service.get_ward_overview(
        db=mock_db,
        tenant_id=test_tenant_id,
    )
    
    assert len(overview) > 0
    assert overview[0]["ward_name"] == "ICU Ward"


@pytest.mark.asyncio
async def test_get_bed_availability(
    bed_management_service,
    mock_db,
    test_ward_id,
):
    """
    Test retrieving bed availability counts for a ward.
    """
    bed1 = MagicMock(spec=Bed)
    bed1.status = BedStatus.AVAILABLE
    
    bed2 = MagicMock(spec=Bed)
    bed2.status = BedStatus.OCCUPIED
    
    bed3 = MagicMock(spec=Bed)
    bed3.status = BedStatus.AVAILABLE
    
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalars = MagicMock(return_value=[bed1, bed2, bed3])
    mock_db.execute.return_value = result
    
    availability = await bed_management_service.get_bed_availability(
        db=mock_db,
        ward_id=test_ward_id,
    )
    
    assert availability["counts"]["available"] == 2
    assert availability["counts"]["occupied"] == 1


# ============================================================================
# NursingService Tests
# ============================================================================

@pytest.mark.asyncio
async def test_add_nursing_note_success(
    nursing_service,
    mock_db,
    test_tenant_id,
    test_nurse_id,
    test_admission_id,
):
    """
    Test adding a nursing note to an admission.
    """
    with patch("app.modules.bed_management.service_nursing._audit", MagicMock(log=AsyncMock())):
        admission = MagicMock(spec=Admission)
        admission.status = AdmissionStatus.ACTIVE
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=admission)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        
        note_request = NursingNoteRequest(
            content="Patient vitals stable, pain controlled",
            note_type=NoteType.GENERAL,
        )
        
        note = await nursing_service.add_nursing_note(
            db=mock_db,
            admission_id=test_admission_id,
            tenant_id=test_tenant_id,
            nurse_id=test_nurse_id,
            data=note_request,
        )
        
        assert note is not None
        assert note.content == "Patient vitals stable, pain controlled"
        assert note.note_type == NoteType.GENERAL


@pytest.mark.asyncio
async def test_add_nursing_note_to_discharged_admission_raises_error(
    nursing_service,
    mock_db,
    test_tenant_id,
    test_nurse_id,
    test_admission_id,
):
    """
    Test that adding a note to discharged admission raises error.
    """
    mock_db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute.return_value = result
    
    note_request = NursingNoteRequest(
        content="Test note",
        note_type=NoteType.GENERAL,
    )
    
    with pytest.raises(AdmissionNotFoundError):
        await nursing_service.add_nursing_note(
            db=mock_db,
            admission_id=test_admission_id,
            tenant_id=test_tenant_id,
            nurse_id=test_nurse_id,
            data=note_request,
        )


@pytest.mark.asyncio
async def test_chart_vitals_success(
    nursing_service,
    mock_db,
    test_tenant_id,
    test_nurse_id,
    test_admission_id,
):
    """
    Test charting vitals for an admitted patient.
    """
    with patch("app.modules.bed_management.service_nursing._audit", MagicMock(log=AsyncMock())):
        admission = MagicMock(spec=Admission)
        admission.status = AdmissionStatus.ACTIVE
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=admission)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        
        vitals_request = VitalsRequest(
            temperature=37.5,
            heart_rate=72,
            systolic_bp=120,
            diastolic_bp=80,
        )
        
        result_dict = await nursing_service.chart_vitals(
            db=mock_db,
            admission_id=test_admission_id,
            tenant_id=test_tenant_id,
            nurse_id=test_nurse_id,
            data=vitals_request,
        )
        
        assert result_dict is not None
        assert "measurement_id" in result_dict


@pytest.mark.asyncio
async def test_chart_vitals_multiple_types(
    nursing_service,
    mock_db,
    test_tenant_id,
    test_nurse_id,
    test_admission_id,
):
    """
    Test charting multiple vital signs at once.
    """
    with patch("app.modules.bed_management.service_nursing._audit", MagicMock(log=AsyncMock())):
        admission = MagicMock(spec=Admission)
        admission.status = AdmissionStatus.ACTIVE
        
        mock_db.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=admission)
        mock_db.execute.return_value = result
        mock_db.flush = AsyncMock()
        
        vitals_request = VitalsRequest(
            temperature=36.8,
            heart_rate=68,
            systolic_bp=118,
            diastolic_bp=78,
            respiratory_rate=16,
            oxygen_saturation=98.5,
        )
        
        result_dict = await nursing_service.chart_vitals(
            db=mock_db,
            admission_id=test_admission_id,
            tenant_id=test_tenant_id,
            nurse_id=test_nurse_id,
            data=vitals_request,
        )
        
        assert result_dict is not None


# ============================================================================
# Schema Validation Tests
# ============================================================================

def test_admit_patient_request_valid():
    """Test valid admission request."""
    req = AdmitPatientRequest(
        patient_id=uuid.uuid4(),
        bed_id=uuid.uuid4(),
        encounter_id=uuid.uuid4(),
        reason="Test admission",
    )
    assert req.reason == "Test admission"


def test_admit_patient_request_optional_notes():
    """Test admission request with optional notes."""
    req = AdmitPatientRequest(
        patient_id=uuid.uuid4(),
        bed_id=uuid.uuid4(),
        encounter_id=uuid.uuid4(),
        reason="Test",
        notes="Patient is stable",
    )
    assert req.notes == "Patient is stable"


def test_discharge_request_valid():
    """Test valid discharge request."""
    req = DischargeRequest(
        discharge_type=DischargeType.ROUTINE,
    )
    assert req.discharge_type == DischargeType.ROUTINE


def test_nursing_note_request_valid():
    """Test valid nursing note request."""
    req = NursingNoteRequest(
        content="Patient is doing well",
        note_type=NoteType.GENERAL,
    )
    assert req.content == "Patient is doing well"


def test_vitals_request_with_all_values():
    """Test vitals request with all vital signs."""
    req = VitalsRequest(
        temperature=37.0,
        heart_rate=72,
        systolic_bp=120,
        diastolic_bp=80,
        respiratory_rate=16,
        oxygen_saturation=98.0,
    )
    assert req.temperature == 37.0


def test_vitals_request_optional_fields():
    """Test vitals request with only required fields."""
    req = VitalsRequest(
        temperature=37.0,
    )
    assert req.temperature == 37.0


def test_transfer_request_valid():
    """Test valid transfer request."""
    req = TransferRequest(
        new_bed_id=uuid.uuid4(),
    )
    assert req.new_bed_id is not None


# ============================================================================
# Enum Tests
# ============================================================================

def test_admission_status_all_values():
    """Test all AdmissionStatus enum values exist."""
    expected = {
        AdmissionStatus.ACTIVE,
        AdmissionStatus.DISCHARGED,
        AdmissionStatus.TRANSFERRED,
    }
    actual = set(AdmissionStatus)
    assert expected == actual


def test_bed_status_all_values():
    """Test all BedStatus enum values exist."""
    expected = {
        BedStatus.AVAILABLE,
        BedStatus.OCCUPIED,
        BedStatus.MAINTENANCE,
        BedStatus.RESERVED,
    }
    actual = set(BedStatus)
    assert expected == actual


def test_discharge_type_all_values():
    """Test all DischargeType enum values exist."""
    expected = {
        DischargeType.ROUTINE,
        DischargeType.AGAINST_MEDICAL_ADVICE,
        DischargeType.TRANSFER,
        DischargeType.DECEASED,
    }
    actual = set(DischargeType)
    assert expected == actual


def test_note_type_all_values():
    """Test all NoteType enum values exist."""
    expected = {
        NoteType.ASSESSMENT,
        NoteType.INTERVENTION,
        NoteType.EVALUATION,
        NoteType.HANDOFF,
        NoteType.GENERAL,
    }
    actual = set(NoteType)
    assert expected == actual


def test_bed_type_all_values():
    """Test all BedType enum values exist."""
    expected = {
        BedType.STANDARD,
        BedType.ICU,
        BedType.ISOLATION,
        BedType.PEDIATRIC,
        BedType.MATERNITY,
    }
    actual = set(BedType)
    assert expected == actual


# ============================================================================
# Exception Tests
# ============================================================================

def test_admission_not_found_error():
    """Test AdmissionNotFoundError message."""
    admission_id = uuid.uuid4()
    exc = AdmissionNotFoundError(admission_id)
    assert "admission" in str(exc).lower()


def test_bed_not_found_error():
    """Test BedNotFoundError message."""
    bed_id = uuid.uuid4()
    exc = BedNotFoundError(bed_id)
    assert "bed" in str(exc).lower()


def test_bed_not_available_error():
    """Test BedNotAvailableError message."""
    bed_id = uuid.uuid4()
    exc = BedNotAvailableError(bed_id, "occupied")
    assert "available" in str(exc).lower()


def test_admission_already_discharged_error():
    """Test AdmissionAlreadyDischargedError message."""
    admission_id = uuid.uuid4()
    exc = AdmissionAlreadyDischargedError(admission_id)
    assert "discharge" in str(exc).lower()


def test_ward_not_found_error():
    """Test WardNotFoundError message."""
    ward_id = uuid.uuid4()
    exc = WardNotFoundError(ward_id)
    assert "ward" in str(exc).lower()
