"""
Property Test: Bed Status Consistency (Property 13).

Invariant:
    - After admit_patient: bed.status == "occupied"
    - After discharge_patient: bed.status == "available"
    - Admitting to a bed with status != "available" raises BedNotAvailableError

Why this matters (Patient Safety & Operations):
    Incorrect bed status can lead to double-admissions (two patients
    assigned the same physical bed) or phantom beds (beds marked occupied
    when they're empty, blocking new admissions). The status state machine
    MUST be consistent after every admission/discharge operation.

Tested service: app.modules.bed_management.service.BedManagementService
Methods: admit_patient, discharge_patient

**Validates: Requirement — Bed status transitions**
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume, strategies as st

from app.modules.bed_management.enums import (
    AdmissionStatus,
    BedStatus,
    DischargeType,
)
from app.modules.bed_management.exceptions import BedNotAvailableError

# Ensure model mappers are loaded
import app.modules.bed_management.models  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-available bed statuses (should reject admission)
non_available_status_strategy = st.sampled_from([
    BedStatus.OCCUPIED,
    BedStatus.MAINTENANCE,
    BedStatus.RESERVED,
])

# Discharge types for generating discharge requests
discharge_type_strategy = st.sampled_from([
    DischargeType.ROUTINE,
    DischargeType.AGAINST_MEDICAL_ADVICE,
    DischargeType.TRANSFER,
])


# ---------------------------------------------------------------------------
# Property Tests: Bed Status Consistency
# ---------------------------------------------------------------------------
class TestBedStatusConsistency:
    """
    Property-based tests proving bed status transitions are correct.

    Core invariants:
    1. admit_patient sets bed to OCCUPIED
    2. discharge_patient sets bed to AVAILABLE
    3. Admission to non-available bed always raises BedNotAvailableError
    """

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_admit_sets_bed_occupied(self, data):
        """
        Property: After a successful admit_patient call, the bed's
        status MUST be BedStatus.OCCUPIED regardless of patient or
        doctor identity.
        """
        from app.modules.bed_management.service import BedManagementService

        bed_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        doctor_id = uuid.uuid4()

        # Create a mock bed in AVAILABLE state
        mock_bed = MagicMock()
        mock_bed.id = bed_id
        mock_bed.status = BedStatus.AVAILABLE

        # Mock DB: _load_bed returns our bed
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_bed
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # Mock admission request
        mock_request = MagicMock()
        mock_request.bed_id = bed_id
        mock_request.patient_id = uuid.uuid4()
        mock_request.encounter_id = uuid.uuid4()
        mock_request.reason = "Synthetic test admission"
        mock_request.notes = None

        service = BedManagementService()
        with patch("app.modules.bed_management.service._audit", MagicMock(log=AsyncMock())):
            await service.admit_patient(
                db=mock_db, data=mock_request,
                tenant_id=tenant_id, doctor_id=doctor_id,
            )

        # INVARIANT: bed status must be OCCUPIED after admission
        assert mock_bed.status == BedStatus.OCCUPIED

    @given(discharge_type=discharge_type_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_discharge_sets_bed_available(self, discharge_type):
        """
        Property: After a successful discharge_patient call, the bed's
        status MUST be BedStatus.AVAILABLE regardless of discharge type.
        """
        from app.modules.bed_management.service import BedManagementService

        admission_id = uuid.uuid4()
        bed_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock active admission
        mock_admission = MagicMock()
        mock_admission.id = admission_id
        mock_admission.bed_id = bed_id
        mock_admission.status = AdmissionStatus.ACTIVE
        mock_admission.notes = None

        # Mock bed currently occupied
        mock_bed = MagicMock()
        mock_bed.id = bed_id
        mock_bed.status = BedStatus.OCCUPIED

        # DB returns admission first, then bed
        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = mock_admission
            else:
                result.scalar_one_or_none.return_value = mock_bed
            return result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_db.flush = AsyncMock()

        # Mock discharge request
        mock_request = MagicMock()
        mock_request.discharge_type = discharge_type
        mock_request.discharge_plan = None
        mock_request.notes = None

        service = BedManagementService()
        with patch("app.modules.bed_management.service._audit", MagicMock(log=AsyncMock())):
            await service.discharge_patient(
                db=mock_db, admission_id=admission_id,
                tenant_id=tenant_id, user_id=user_id, data=mock_request,
            )

        # INVARIANT: bed status must be AVAILABLE after discharge
        assert mock_bed.status == BedStatus.AVAILABLE

    @given(bad_status=non_available_status_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_admit_to_non_available_raises(self, bad_status):
        """
        Property: Attempting to admit a patient to a bed whose status
        is NOT 'available' MUST raise BedNotAvailableError. This holds
        for occupied, maintenance, and reserved beds.
        """
        from app.modules.bed_management.service import BedManagementService

        bed_id = uuid.uuid4()

        # Create a mock bed in non-available state
        mock_bed = MagicMock()
        mock_bed.id = bed_id
        mock_bed.status = bad_status

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_bed
        mock_db.execute.return_value = mock_result

        mock_request = MagicMock()
        mock_request.bed_id = bed_id
        mock_request.patient_id = uuid.uuid4()
        mock_request.encounter_id = uuid.uuid4()
        mock_request.reason = "Synthetic test"
        mock_request.notes = None

        service = BedManagementService()

        # INVARIANT: Must raise BedNotAvailableError
        with pytest.raises(BedNotAvailableError):
            await service.admit_patient(
                db=mock_db, data=mock_request,
                tenant_id=uuid.uuid4(), doctor_id=uuid.uuid4(),
            )
