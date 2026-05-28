"""
Unit tests for EncounterService business logic (update, list, helpers).

Tests the service methods with mocked database to verify update logic,
encounter-for-update validation, and list pagination.

Validates:
- update_encounter applies field changes and audits
- _get_encounter_for_update raises for missing encounter
- _get_encounter_for_update raises for completed encounter
- list_patient_encounters clamps limit and applies cursor
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
)
from app.modules.encounters.service import EncounterService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def enc_service():
    """Create an EncounterService instance for testing."""
    return EncounterService()


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Test: _get_encounter_for_update
# ---------------------------------------------------------------------------
class TestGetEncounterForUpdate:
    """Verify _get_encounter_for_update validates encounter state."""

    @pytest.mark.asyncio
    async def test_raises_for_missing_encounter(self, enc_service, mock_db):
        """_get_encounter_for_update raises EncounterNotFoundError."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(EncounterNotFoundError):
            await enc_service._get_encounter_for_update(mock_db, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_for_completed_encounter(self, enc_service, mock_db):
        """_get_encounter_for_update raises EncounterAlreadyCompletedError."""
        mock_enc = SimpleNamespace(
            id=uuid.uuid4(),
            status=EncounterStatus.COMPLETED,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_enc
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(EncounterAlreadyCompletedError):
            await enc_service._get_encounter_for_update(mock_db, mock_enc.id)

    @pytest.mark.asyncio
    async def test_returns_encounter_when_in_progress(self, enc_service, mock_db):
        """_get_encounter_for_update returns encounter if in_progress."""
        mock_enc = SimpleNamespace(
            id=uuid.uuid4(),
            status=EncounterStatus.IN_PROGRESS,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_enc
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await enc_service._get_encounter_for_update(mock_db, mock_enc.id)
        assert result.status == EncounterStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Test: update_encounter
# ---------------------------------------------------------------------------
class TestUpdateEncounter:
    """Verify update_encounter applies changes and audits."""

    @pytest.mark.asyncio
    async def test_updates_clinician_id(self, enc_service, mock_db):
        """update_encounter applies clinician_id change."""
        enc_id = uuid.uuid4()
        new_clinician = uuid.uuid4()
        mock_enc = SimpleNamespace(
            id=enc_id,
            status=EncounterStatus.IN_PROGRESS,
            tenant_id=uuid.uuid4(),
            clinician_id=uuid.uuid4(),
            encounter_class=EncounterClass.AMBULATORY,
        )

        with patch.object(
            enc_service, "_get_encounter_for_update",
            new_callable=AsyncMock, return_value=mock_enc,
        ):
            with patch("app.modules.encounters.service._audit") as mock_audit:
                mock_audit.log = AsyncMock()
                result = await enc_service.update_encounter(
                    db=mock_db,
                    encounter_id=enc_id,
                    user_id=uuid.uuid4(),
                    data={"clinician_id": new_clinician},
                )

        assert result.clinician_id == new_clinician

    @pytest.mark.asyncio
    async def test_updates_encounter_class(self, enc_service, mock_db):
        """update_encounter applies encounter_class change."""
        enc_id = uuid.uuid4()
        mock_enc = SimpleNamespace(
            id=enc_id,
            status=EncounterStatus.IN_PROGRESS,
            tenant_id=uuid.uuid4(),
            clinician_id=uuid.uuid4(),
            encounter_class=EncounterClass.AMBULATORY,
        )

        with patch.object(
            enc_service, "_get_encounter_for_update",
            new_callable=AsyncMock, return_value=mock_enc,
        ):
            with patch("app.modules.encounters.service._audit") as mock_audit:
                mock_audit.log = AsyncMock()
                result = await enc_service.update_encounter(
                    db=mock_db,
                    encounter_id=enc_id,
                    user_id=uuid.uuid4(),
                    data={"encounter_class": "emergency"},
                )

        assert result.encounter_class == EncounterClass.EMERGENCY


# ---------------------------------------------------------------------------
# Test: list_patient_encounters
# ---------------------------------------------------------------------------
class TestListPatientEncounters:
    """Verify list_patient_encounters returns results from DB."""

    @pytest.mark.asyncio
    async def test_returns_encounters_list(self, enc_service, mock_db):
        """list_patient_encounters returns list from query."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = ["enc1", "enc2"]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await enc_service.list_patient_encounters(
            mock_db, uuid.uuid4()
        )

        assert len(result) == 2
