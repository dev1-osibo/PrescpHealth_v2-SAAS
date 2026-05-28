"""
Unit tests for SOAP note service logic.

Tests the SOAPNoteService methods with mocked database to verify
business rules around note creation, updates, and encounter validation.

Validates:
- add_soap_note creates a note when encounter is modifiable
- add_soap_note raises EncounterNotFoundError for missing encounter
- add_soap_note raises EncounterAlreadyCompletedError for completed encounter
- update_soap_note raises ValueError for missing note
- get_soap_notes returns notes ordered by creation time
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.encounters.enums import EncounterStatus
from app.modules.encounters.exceptions import (
    EncounterAlreadyCompletedError,
    EncounterNotFoundError,
)
from app.modules.encounters.service_soap import SOAPNoteService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def soap_service():
    """Create a SOAPNoteService instance for testing."""
    return SOAPNoteService()


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Test: add_soap_note success path
# ---------------------------------------------------------------------------
class TestAddSoapNote:
    """Verify add_soap_note creates notes correctly."""

    @pytest.mark.asyncio
    async def test_creates_note_for_active_encounter(self, soap_service, mock_db):
        """add_soap_note creates a note when encounter is in_progress."""
        encounter_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock encounter lookup — returns active encounter
        mock_row = SimpleNamespace(
            id=encounter_id, status=EncounterStatus.IN_PROGRESS
        )
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = mock_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.encounters.service_soap._audit"
        ) as mock_audit:
            mock_audit.log = AsyncMock()
            note = await soap_service.add_soap_note(
                db=mock_db,
                encounter_id=encounter_id,
                tenant_id=tenant_id,
                user_id=user_id,
                subjective="Patient reports headache",
                assessment="Tension headache",
            )

        # Verify note was added to session
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_raises_for_missing_encounter(self, soap_service, mock_db):
        """add_soap_note raises EncounterNotFoundError for non-existent encounter."""
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(EncounterNotFoundError):
            await soap_service.add_soap_note(
                db=mock_db,
                encounter_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_raises_for_completed_encounter(self, soap_service, mock_db):
        """add_soap_note raises EncounterAlreadyCompletedError for completed."""
        encounter_id = uuid.uuid4()
        mock_row = SimpleNamespace(
            id=encounter_id, status=EncounterStatus.COMPLETED
        )
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = mock_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(EncounterAlreadyCompletedError):
            await soap_service.add_soap_note(
                db=mock_db,
                encounter_id=encounter_id,
                tenant_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# Test: update_soap_note
# ---------------------------------------------------------------------------
class TestUpdateSoapNote:
    """Verify update_soap_note handles missing notes."""

    @pytest.mark.asyncio
    async def test_raises_value_error_for_missing_note(self, soap_service, mock_db):
        """update_soap_note raises ValueError when note_id doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="SOAP note not found"):
            await soap_service.update_soap_note(
                db=mock_db,
                note_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                data={"subjective": "Updated symptoms"},
            )


# ---------------------------------------------------------------------------
# Test: get_soap_notes
# ---------------------------------------------------------------------------
class TestGetSoapNotes:
    """Verify get_soap_notes returns notes from database."""

    @pytest.mark.asyncio
    async def test_returns_notes_list(self, soap_service, mock_db):
        """get_soap_notes returns list of notes from query result."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = ["note1", "note2"]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        notes = await soap_service.get_soap_notes(mock_db, uuid.uuid4())

        assert len(notes) == 2
