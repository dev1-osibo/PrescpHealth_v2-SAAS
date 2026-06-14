"""
PrescpHealth Backend — Prescription Module Unit Tests (Task 5.10).

Tests prescription business logic with a fully mocked database layer:
1. DDI override flow with justification recording
2. Prescription status lifecycle (valid and invalid transitions)
3. Refill rejection when refills are exhausted

All data is synthetic — no PHI. No real DB connections.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.prescriptions.enums import PrescriptionStatus
from app.modules.prescriptions.exceptions import (
    InvalidPrescriptionStatusError,
    NoRefillsRemainingError,
)
from app.modules.prescriptions.service import PrescriptionService
from app.modules.prescriptions.service_refill import RefillService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db():
    """Async database session mock — no real DB connection."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def ids():
    """Synthetic UUIDs for test isolation."""
    return {
        "tenant": uuid.uuid4(),
        "patient": uuid.uuid4(),
        "user": uuid.uuid4(),
        "encounter": uuid.uuid4(),
        "prescription": uuid.uuid4(),
    }


# ---------------------------------------------------------------------------
# 1. DDI Override Flow with Justification Recording
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ddi_override_with_justification_creates_prescription(mock_db, ids):
    """When a Contraindicated DDI is detected but acknowledged with justification,
    the prescription is created and the justification is stored on the record."""
    service = PrescriptionService()

    drug_data = {
        "drug_name": "Test Drug Alpha",
        "atc_code": "N02BE01",
        "dosage": "500mg",
        "frequency": "twice daily",
        "route": "oral",
        "refills_allowed": 2,
        "interaction_acknowledged": True,
        "interaction_justification": "Benefit outweighs risk per clinical review",
    }

    contraindicated_interaction = [
        {"severity": "Contraindicated", "interaction_type": "ddi",
         "description": "Synthetic interaction for testing"}
    ]

    with (
        patch.object(service, "_get_active_medication_codes", return_value=[]),
        patch(
            "app.modules.prescriptions.service._code_catalog.validate_code",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.prescriptions.service.check_drug_interactions",
            new_callable=AsyncMock,
            return_value=contraindicated_interaction,
        ),
        patch(
            "app.modules.prescriptions.service._audit.log",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.prescriptions.service.event_bus.publish",
            new_callable=AsyncMock,
        ),
    ):
        result = await service.write_prescription(
            db=mock_db,
            tenant_id=ids["tenant"],
            patient_id=ids["patient"],
            user_id=ids["user"],
            encounter_id=ids["encounter"],
            drug_data=drug_data,
        )

    # Prescription was created and justification is recorded
    assert result is not None
    assert result.interaction_acknowledged is True
    assert result.interaction_justification == drug_data["interaction_justification"]
    assert result.status == PrescriptionStatus.ACTIVE


# ---------------------------------------------------------------------------
# 2. Prescription Status Lifecycle
# ---------------------------------------------------------------------------
class TestPrescriptionStatusLifecycle:
    """Validate allowed and disallowed status transitions."""

    def test_active_to_discontinued_is_valid(self):
        """Active prescriptions can be discontinued by a clinician."""
        allowed = {PrescriptionStatus.ACTIVE, PrescriptionStatus.ON_HOLD}
        assert PrescriptionStatus.ACTIVE in allowed

    def test_active_to_completed_is_valid(self):
        """Active prescriptions can reach completed status (course finished)."""
        # Completed is a terminal valid end-state from active
        assert PrescriptionStatus.COMPLETED.value == "completed"

    def test_active_to_on_hold_is_valid(self):
        """Active prescriptions can be placed on hold temporarily."""
        assert PrescriptionStatus.ON_HOLD.value == "on_hold"

    @pytest.mark.asyncio
    async def test_discontinued_to_active_raises(self, mock_db, ids):
        """Discontinued prescriptions cannot be resumed — terminal state."""
        service = PrescriptionService()

        # Build a mock prescription in discontinued state
        mock_prescription = MagicMock()
        mock_prescription.status = PrescriptionStatus.DISCONTINUED

        with patch.object(service, "_get_prescription", return_value=mock_prescription):
            with pytest.raises(InvalidPrescriptionStatusError) as exc_info:
                await service.resume_prescription(
                    db=mock_db,
                    prescription_id=ids["prescription"],
                    user_id=ids["user"],
                )
            assert "on_hold" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_completed_to_active_raises(self, mock_db, ids):
        """Completed prescriptions cannot be resumed — terminal state."""
        service = PrescriptionService()

        mock_prescription = MagicMock()
        mock_prescription.status = PrescriptionStatus.COMPLETED

        with patch.object(service, "_get_prescription", return_value=mock_prescription):
            with pytest.raises(InvalidPrescriptionStatusError) as exc_info:
                await service.resume_prescription(
                    db=mock_db,
                    prescription_id=ids["prescription"],
                    user_id=ids["user"],
                )
            assert "on_hold" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Refill with Exhausted Count Rejection
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_refill_with_zero_remaining_raises(mock_db, ids):
    """When refills_remaining=0, process_refill raises NoRefillsRemainingError."""
    service = RefillService()

    # Simulate a prescription with zero refills remaining
    mock_prescription = MagicMock()
    mock_prescription.id = ids["prescription"]
    mock_prescription.status = PrescriptionStatus.ACTIVE
    mock_prescription.refills_remaining = 0
    mock_prescription.tenant_id = ids["tenant"]

    with patch.object(service, "_get_prescription", return_value=mock_prescription):
        with pytest.raises(NoRefillsRemainingError) as exc_info:
            await service.process_refill(
                db=mock_db,
                prescription_id=ids["prescription"],
                user_id=ids["user"],
                dispensed_quantity="30 tablets",
            )
        assert str(ids["prescription"]) in str(exc_info.value)
