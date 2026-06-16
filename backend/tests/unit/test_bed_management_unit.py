"""
Unit Tests: Bed Management Module (Task 17.5).

Tests cover:
- Admission to available bed (sets occupied, creates admission record)
- Admission to occupied bed raises BedNotAvailableError
- Admission to maintenance bed raises BedNotAvailableError
- Discharge sets bed to available and admission to discharged
- Nursing note recording (creates NursingNote with correct fields)
- Vitals charting creates measurement metadata
- get_bed_availability returns correct counts per status

All tests use mocked AsyncSession — no real DB connections.
All patient data is synthetic (no PHI).
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.bed_management.enums import (
    AdmissionStatus,
    BedStatus,
    DischargeType,
    NoteType,
)
from app.modules.bed_management.exceptions import (
    BedNotAvailableError,
    AdmissionAlreadyDischargedError,
)

# Module-level audit mock
_mock_audit = MagicMock(log=AsyncMock())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_bed(status=BedStatus.AVAILABLE, **overrides):
    """Create a mock Bed object."""
    bed = MagicMock()
    bed.id = overrides.get("id", uuid.uuid4())
    bed.ward_id = overrides.get("ward_id", uuid.uuid4())
    bed.status = status
    return bed


def _mock_admission(status=AdmissionStatus.ACTIVE, **overrides):
    """Create a mock Admission object."""
    adm = MagicMock()
    adm.id = overrides.get("id", uuid.uuid4())
    adm.bed_id = overrides.get("bed_id", uuid.uuid4())
    adm.patient_id = overrides.get("patient_id", uuid.uuid4())
    adm.status = status
    adm.notes = overrides.get("notes", None)
    return adm


class TestAdmission:
    """Verify patient admission to beds."""

    @pytest.mark.asyncio
    async def test_admit_to_available_bed_sets_occupied(self):
        """Admitting to an available bed sets status to OCCUPIED and creates admission."""
        from app.modules.bed_management.service import BedManagementService

        bed = _mock_bed(status=BedStatus.AVAILABLE)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = bed
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_request = MagicMock()
        mock_request.bed_id = bed.id
        mock_request.patient_id = uuid.uuid4()
        mock_request.encounter_id = uuid.uuid4()
        mock_request.reason = "Synthetic admission for unit test"
        mock_request.notes = None

        service = BedManagementService()
        with patch("app.modules.bed_management.service._audit", _mock_audit):
            admission = await service.admit_patient(
                db=mock_db, data=mock_request,
                tenant_id=uuid.uuid4(), doctor_id=uuid.uuid4(),
            )

        assert bed.status == BedStatus.OCCUPIED
        assert mock_db.add.called
        assert admission.status == AdmissionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_admit_to_occupied_bed_raises(self):
        """Admitting to an occupied bed raises BedNotAvailableError."""
        from app.modules.bed_management.service import BedManagementService

        bed = _mock_bed(status=BedStatus.OCCUPIED)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = bed
        mock_db.execute.return_value = mock_result

        mock_request = MagicMock()
        mock_request.bed_id = bed.id
        mock_request.patient_id = uuid.uuid4()

        service = BedManagementService()
        with pytest.raises(BedNotAvailableError):
            await service.admit_patient(
                db=mock_db, data=mock_request,
                tenant_id=uuid.uuid4(), doctor_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_admit_to_maintenance_bed_raises(self):
        """Admitting to a maintenance bed raises BedNotAvailableError."""
        from app.modules.bed_management.service import BedManagementService

        bed = _mock_bed(status=BedStatus.MAINTENANCE)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = bed
        mock_db.execute.return_value = mock_result

        mock_request = MagicMock()
        mock_request.bed_id = bed.id
        mock_request.patient_id = uuid.uuid4()

        service = BedManagementService()
        with pytest.raises(BedNotAvailableError):
            await service.admit_patient(
                db=mock_db, data=mock_request,
                tenant_id=uuid.uuid4(), doctor_id=uuid.uuid4(),
            )


class TestDischarge:
    """Verify discharge sets bed available and admission to discharged."""

    @pytest.mark.asyncio
    async def test_discharge_sets_bed_available(self):
        """Discharging a patient sets bed back to AVAILABLE."""
        from app.modules.bed_management.service import BedManagementService

        bed_id = uuid.uuid4()
        admission = _mock_admission(bed_id=bed_id)
        bed = _mock_bed(status=BedStatus.OCCUPIED, id=bed_id)

        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = admission
            else:
                result.scalar_one_or_none.return_value = bed
            return result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_db.flush = AsyncMock()

        mock_request = MagicMock()
        mock_request.discharge_type = DischargeType.ROUTINE
        mock_request.discharge_plan = None
        mock_request.notes = None

        service = BedManagementService()
        with patch("app.modules.bed_management.service._audit", _mock_audit):
            await service.discharge_patient(
                db=mock_db, admission_id=admission.id,
                tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
                data=mock_request,
            )

        assert bed.status == BedStatus.AVAILABLE
        assert admission.status == AdmissionStatus.DISCHARGED


class TestNursingNotes:
    """Verify nursing note recording."""

    @pytest.mark.asyncio
    async def test_add_nursing_note_creates_record(self):
        """Adding a nursing note creates a NursingNote with correct fields."""
        from app.modules.bed_management.service_nursing import NursingService

        admission = _mock_admission(status=AdmissionStatus.ACTIVE)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = admission
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_data = MagicMock()
        mock_data.content = "Synthetic nursing note content for testing"
        mock_data.note_type = NoteType.ASSESSMENT
        mock_data.recorded_at = None

        service = NursingService()
        with patch("app.modules.bed_management.service_nursing._audit", _mock_audit):
            note = await service.add_nursing_note(
                db=mock_db, admission_id=admission.id,
                tenant_id=uuid.uuid4(), nurse_id=uuid.uuid4(),
                data=mock_data,
            )

        assert note.note_type == NoteType.ASSESSMENT
        assert note.content == "Synthetic nursing note content for testing"
        assert mock_db.add.called


class TestVitalsCharting:
    """Verify vitals charting creates measurement metadata."""

    @pytest.mark.asyncio
    async def test_chart_vitals_returns_measurement_metadata(self):
        """Charting vitals returns metadata with recorded fields."""
        from app.modules.bed_management.service_nursing import NursingService

        admission = _mock_admission(status=AdmissionStatus.ACTIVE)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = admission
        mock_db.execute.return_value = mock_result

        mock_data = MagicMock()
        mock_data.model_dump.return_value = {
            "systolic_bp": 120, "diastolic_bp": 80,
            "heart_rate": 72, "notes": None,
        }

        service = NursingService()
        with patch("app.modules.bed_management.service_nursing._audit", _mock_audit):
            result = await service.chart_vitals(
                db=mock_db, admission_id=admission.id,
                tenant_id=uuid.uuid4(), nurse_id=uuid.uuid4(),
                data=mock_data,
            )

        assert "measurement_id" in result
        assert "recorded_fields" in result
        assert "systolic_bp" in result["recorded_fields"]


class TestTransfer:
    """Verify bed transfer frees old bed and occupies new bed."""

    @pytest.mark.asyncio
    async def test_transfer_old_bed_available_new_bed_occupied(self):
        """Transferring a patient frees old bed and occupies new bed."""
        from app.modules.bed_management.service import BedManagementService

        old_bed_id = uuid.uuid4()
        new_bed_id = uuid.uuid4()
        admission = _mock_admission(bed_id=old_bed_id)
        old_bed = _mock_bed(status=BedStatus.OCCUPIED, id=old_bed_id)
        new_bed = _mock_bed(status=BedStatus.AVAILABLE, id=new_bed_id)

        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # Load active admission
                result.scalar_one_or_none.return_value = admission
            elif call_count[0] == 2:
                # Load new bed
                result.scalar_one_or_none.return_value = new_bed
            else:
                # Load old bed
                result.scalar_one_or_none.return_value = old_bed
            return result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_execute_side_effect)
        mock_db.flush = AsyncMock()

        service = BedManagementService()
        with patch("app.modules.bed_management.service._audit", _mock_audit):
            await service.transfer_patient(
                db=mock_db, admission_id=admission.id,
                new_bed_id=new_bed_id,
                tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
            )

        assert old_bed.status == BedStatus.AVAILABLE
        assert new_bed.status == BedStatus.OCCUPIED
        assert admission.bed_id == new_bed_id


class TestBedAvailability:
    """Verify get_bed_availability returns correct counts."""

    @pytest.mark.asyncio
    async def test_get_bed_availability_counts(self):
        """Availability returns correct counts per status."""
        from app.modules.bed_management.service import BedManagementService

        ward_id = uuid.uuid4()
        beds = [
            _mock_bed(status=BedStatus.AVAILABLE),
            _mock_bed(status=BedStatus.AVAILABLE),
            _mock_bed(status=BedStatus.OCCUPIED),
            _mock_bed(status=BedStatus.MAINTENANCE),
        ]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.__iter__ = MagicMock(return_value=iter(beds))
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service = BedManagementService()
        result = await service.get_bed_availability(db=mock_db, ward_id=ward_id)

        assert result["counts"]["available"] == 2
        assert result["counts"]["occupied"] == 1
        assert result["counts"]["maintenance"] == 1
        assert result["counts"]["reserved"] == 0
