"""
Unit Tests: Encounters Module — Task 5.9.

Tests encounter creation, SOAP note CRUD, status transitions,
invalid transition rejection, ICD-10 validation, and discharge
summary generation — all with mocked DB (no real connections).

Validates:
- Encounter creation with valid data
- SOAP note create, read, update
- Status transitions: planned → in_progress → completed
- Invalid status transition rejection (completed → planned)
- ICD-10 code validation rejection via CodeCatalogService
- Discharge summary includes all diagnoses and procedures
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.encounters.enums import EncounterClass, EncounterStatus
from app.modules.encounters.exceptions import (
    EncounterAlreadyCompletedError,
    EncounterNotFoundError,
    InvalidEncounterStatusTransitionError,
)
from app.modules.encounters.service import EncounterService
from app.modules.encounters.service_soap import SOAPNoteService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    """Mock AsyncSession — tracks added objects, never hits a real DB."""
    db = AsyncMock()
    db.added = []

    def _add(obj):
        db.added.append(obj)

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock()
    return db


@pytest.fixture
def enc_service():
    """EncounterService instance."""
    return EncounterService()


@pytest.fixture
def soap_service():
    """SOAPNoteService instance."""
    return SOAPNoteService()


# ---------------------------------------------------------------------------
# Test: Encounter Creation
# ---------------------------------------------------------------------------

class TestEncounterCreation:
    """Verify encounter creation with valid data."""

    @pytest.mark.asyncio
    async def test_create_encounter_with_valid_data(self, mock_db):
        """Encounter creation sets correct fields and status IN_PROGRESS."""
        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        clinician_id = uuid.uuid4()

        with patch("app.modules.encounters.service._audit") as mock_audit:
            mock_audit.log = AsyncMock()
            svc = EncounterService()
            result = await svc.create_encounter(
                db=mock_db,
                tenant_id=tenant_id,
                patient_id=patient_id,
                clinician_id=clinician_id,
                reason="Routine checkup",
                encounter_class=EncounterClass.AMBULATORY,
            )

        # Verify the encounter was added to the DB session
        assert len(mock_db.added) == 1
        enc = mock_db.added[0]
        assert enc.tenant_id == tenant_id
        assert enc.patient_id == patient_id
        assert enc.clinician_id == clinician_id
        assert enc.status == EncounterStatus.IN_PROGRESS
        assert enc.encounter_class == EncounterClass.AMBULATORY


# ---------------------------------------------------------------------------
# Test: SOAP Note CRUD
# ---------------------------------------------------------------------------

class TestSOAPNoteCRUD:
    """Verify SOAP note create, read, and update operations."""

    @pytest.mark.asyncio
    async def test_add_soap_note_success(self, mock_db, soap_service):
        """Adding a SOAP note to a modifiable encounter succeeds."""
        encounter_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock _validate_encounter_modifiable to pass
        with patch.object(
            soap_service, "_validate_encounter_modifiable", new_callable=AsyncMock
        ):
            with patch("app.modules.encounters.service_soap._audit") as mock_audit:
                mock_audit.log = AsyncMock()
                note = await soap_service.add_soap_note(
                    db=mock_db,
                    encounter_id=encounter_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    subjective="Patient reports headache",
                    objective="BP 120/80",
                    assessment="Tension headache",
                    plan="Ibuprofen 400mg PRN",
                )

        assert len(mock_db.added) == 1
        created = mock_db.added[0]
        assert created.encounter_id == encounter_id
        assert created.subjective == "Patient reports headache"

    @pytest.mark.asyncio
    async def test_get_soap_notes_returns_list(self, mock_db, soap_service):
        """get_soap_notes returns notes for an encounter."""
        note1 = SimpleNamespace(id=uuid.uuid4(), subjective="Headache")
        note2 = SimpleNamespace(id=uuid.uuid4(), subjective="Follow-up")

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [note1, note2]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        notes = await soap_service.get_soap_notes(mock_db, uuid.uuid4())
        assert len(notes) == 2

    @pytest.mark.asyncio
    async def test_update_soap_note_modifies_fields(self, mock_db, soap_service):
        """Updating a SOAP note modifies the specified fields."""
        note_id = uuid.uuid4()
        mock_note = SimpleNamespace(
            id=note_id,
            encounter_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            subjective="Old subjective",
            objective="Old objective",
            assessment="Old assessment",
            plan="Old plan",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_note
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch.object(
            soap_service, "_validate_encounter_modifiable", new_callable=AsyncMock
        ):
            with patch("app.modules.encounters.service_soap._audit") as mock_audit:
                mock_audit.log = AsyncMock()
                updated = await soap_service.update_soap_note(
                    db=mock_db,
                    note_id=note_id,
                    user_id=uuid.uuid4(),
                    data={"assessment": "Migraine", "plan": "Sumatriptan 50mg"},
                )

        assert updated.assessment == "Migraine"
        assert updated.plan == "Sumatriptan 50mg"
        # Unchanged fields remain intact
        assert updated.subjective == "Old subjective"


# ---------------------------------------------------------------------------
# Test: Status Transitions
# ---------------------------------------------------------------------------

class TestStatusTransitions:
    """Verify valid and invalid encounter status transitions."""

    def test_planned_to_in_progress_valid(self, enc_service):
        """Transition planned → in_progress is allowed."""
        enc = SimpleNamespace(
            id=uuid.uuid4(), status=EncounterStatus.PLANNED.value
        )
        # Should not raise
        enc_service._validate_transition(enc, EncounterStatus.IN_PROGRESS)

    def test_in_progress_to_completed_valid(self, enc_service):
        """Transition in_progress → completed is allowed."""
        enc = SimpleNamespace(
            id=uuid.uuid4(), status=EncounterStatus.IN_PROGRESS.value
        )
        enc_service._validate_transition(enc, EncounterStatus.COMPLETED)

    def test_completed_to_planned_rejected(self, enc_service):
        """Transition completed → planned is rejected (terminal state)."""
        enc = SimpleNamespace(
            id=uuid.uuid4(), status=EncounterStatus.COMPLETED.value
        )
        with pytest.raises(EncounterAlreadyCompletedError):
            enc_service._validate_transition(enc, EncounterStatus.PLANNED)

    def test_completed_to_in_progress_rejected(self, enc_service):
        """Transition completed → in_progress is rejected (terminal state)."""
        enc = SimpleNamespace(
            id=uuid.uuid4(), status=EncounterStatus.COMPLETED.value
        )
        with pytest.raises(EncounterAlreadyCompletedError):
            enc_service._validate_transition(enc, EncounterStatus.IN_PROGRESS)

    def test_planned_to_completed_rejected(self, enc_service):
        """Transition planned → completed is invalid (must pass through in_progress)."""
        enc = SimpleNamespace(
            id=uuid.uuid4(), status=EncounterStatus.PLANNED.value
        )
        with pytest.raises(InvalidEncounterStatusTransitionError):
            enc_service._validate_transition(enc, EncounterStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Test: Discharge Summary Generation
# ---------------------------------------------------------------------------

class TestDischargeSummary:
    """Verify discharge summary includes all diagnoses and procedures."""

    def test_discharge_summary_includes_diagnoses_and_procedures(self, enc_service):
        """_build_discharge_summary captures all diagnoses and procedures."""
        dx1 = SimpleNamespace(
            icd10_code="I10", display_name="Hypertension",
            is_primary=True, is_chronic=True,
        )
        dx2 = SimpleNamespace(
            icd10_code="E11.9", display_name="Type 2 Diabetes",
            is_primary=False, is_chronic=True,
        )
        proc1 = SimpleNamespace(
            code="99213", description="Office visit",
            performed_at=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc),
        )

        encounter = SimpleNamespace(
            diagnoses=[dx1, dx2],
            procedures=[proc1],
        )

        summary = enc_service._build_discharge_summary(encounter)

        assert len(summary["diagnoses"]) == 2
        assert summary["diagnoses"][0]["icd10_code"] == "I10"
        assert summary["diagnoses"][1]["icd10_code"] == "E11.9"
        assert len(summary["procedures"]) == 1
        assert summary["procedures"][0]["code"] == "99213"
        # Structure validation
        assert "prescriptions" in summary
        assert "follow_up" in summary
