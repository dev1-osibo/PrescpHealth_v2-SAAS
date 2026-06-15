"""
Unit Tests: Registration Module (Task 11.8).

Tests cover:
- Partial registration workflow (start_intake → update → complete)
- Consent capture stores digital_signature and consent_type
- MRN generation format (MRN-{TENANT_SHORT}-{SEQUENCE}) and uniqueness
- Consent revocation sets revoked_at and reason
- complete_registration fails if required fields missing

All tests use mocked AsyncSession — no real DB connections.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.registration.enums import ConsentType
from app.modules.registration.exceptions import (
    RegistrationIncompleteError,
    RegistrationNotFoundError,
    ConsentAlreadyRevokedError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mock_db_for_registration():
    """Create mock DB for registration service (uses raw text SQL)."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0
    mock_db.execute.return_value = mock_result
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    return mock_db


class TestPartialRegistrationWorkflow:
    """Verify the start_intake → update → complete workflow."""

    @pytest.mark.asyncio
    async def test_start_intake_creates_patient(self):
        """start_intake executes INSERT and returns a patient UUID."""
        from app.modules.registration.service import RegistrationService

        mock_db = _mock_db_for_registration()
        service = RegistrationService()

        with patch("app.modules.registration.service._audit", MagicMock(log_action=AsyncMock())):
            patient_id = await service.start_intake(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                first_name="Test",
                last_name="Patient",
                date_of_birth="1990-01-15",
                created_by=uuid.uuid4(),
            )

        # Verify a UUID was returned
        assert isinstance(patient_id, uuid.UUID)
        # Verify DB execute was called (INSERT)
        assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_update_registration_applies_fields(self):
        """update_registration executes UPDATE with provided data fields."""
        from app.modules.registration.service import RegistrationService

        mock_db = _mock_db_for_registration()
        service = RegistrationService()

        with patch("app.modules.registration.service._audit", MagicMock(log_action=AsyncMock())):
            await service.update_registration(
                db=mock_db,
                patient_id=uuid.uuid4(),
                data={"phone": "+1234567890", "address": "123 Synthetic St"},
                user_id=uuid.uuid4(),
            )

        # Verify UPDATE was executed
        assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_complete_registration_fails_if_fields_missing(self):
        """complete_registration raises RegistrationIncompleteError for missing fields."""
        from app.modules.registration.service import RegistrationService

        # Simulate a row missing required fields (phone and address)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_mappings = MagicMock()
        mock_mappings.first.return_value = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "first_name": "Test",
            "last_name": "Patient",
            "date_of_birth": "1990-01-15",
            "phone": None,       # Missing
            "address": None,     # Missing
        }
        mock_result.mappings.return_value = mock_mappings
        mock_db.execute.return_value = mock_result

        service = RegistrationService()

        with pytest.raises(RegistrationIncompleteError) as exc_info:
            await service.complete_registration(
                db=mock_db, patient_id=uuid.uuid4(), user_id=uuid.uuid4(),
            )

        assert "phone" in exc_info.value.missing_fields
        assert "address" in exc_info.value.missing_fields


class TestMRNGeneration:
    """Verify MRN format and per-call uniqueness."""

    @pytest.mark.asyncio
    async def test_mrn_format_matches_spec(self):
        """Generated MRN matches format MRN-{TENANT_SHORT}-{SEQUENCE}."""
        from app.modules.registration.service import RegistrationService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_db.execute.return_value = mock_result

        tenant_id = uuid.UUID("abcdef12-3456-7890-abcd-ef1234567890")
        service = RegistrationService()

        mrn = await service.generate_mrn(db=mock_db, tenant_id=tenant_id)

        # Format: MRN-{first 6 hex chars uppercase}-{zero-padded sequence}
        assert mrn.startswith("MRN-")
        parts = mrn.split("-")
        assert len(parts) == 3
        assert parts[1] == "ABCDEF"  # First 6 hex chars of tenant UUID
        assert parts[2] == "000043"  # count (42) + 1, zero-padded

    @pytest.mark.asyncio
    async def test_mrn_unique_per_call(self):
        """Two calls with different counts produce different MRNs."""
        from app.modules.registration.service import RegistrationService

        tenant_id = uuid.uuid4()
        service = RegistrationService()

        # First call: count = 0
        mock_db_1 = AsyncMock()
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one.return_value = 0
        mock_db_1.execute.return_value = mock_result_1
        mrn_1 = await service.generate_mrn(db=mock_db_1, tenant_id=tenant_id)

        # Second call: count = 1
        mock_db_2 = AsyncMock()
        mock_result_2 = MagicMock()
        mock_result_2.scalar_one.return_value = 1
        mock_db_2.execute.return_value = mock_result_2
        mrn_2 = await service.generate_mrn(db=mock_db_2, tenant_id=tenant_id)

        assert mrn_1 != mrn_2


class TestConsentCapture:
    """Verify consent capture stores signature and consent type."""

    @pytest.mark.asyncio
    async def test_capture_consent_stores_signature(self):
        """capture_consent persists digital_signature and consent_type."""
        from app.modules.registration.service_consent import ConsentService

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        service = ConsentService()
        sig = "base64-encoded-signature-data"

        with patch("app.modules.registration.service_consent._audit", MagicMock(log_action=AsyncMock())):
            result = await service.capture_consent(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                consent_type=ConsentType.TREATMENT,
                version="1.0",
                is_granted=True,
                captured_by=uuid.uuid4(),
                digital_signature=sig,
            )

        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.digital_signature == sig
        assert added_obj.consent_type == ConsentType.TREATMENT


class TestConsentRevocation:
    """Verify consent revocation sets revoked_at and reason."""

    @pytest.mark.asyncio
    async def test_revoke_consent_sets_fields(self):
        """revoke_consent sets revoked_at timestamp and revocation_reason."""
        from app.modules.registration.service_consent import ConsentService

        consent = MagicMock()
        consent.id = uuid.uuid4()
        consent.tenant_id = uuid.uuid4()
        consent.revoked_at = None  # Not yet revoked

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = consent
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        service = ConsentService()

        with patch("app.modules.registration.service_consent._audit", MagicMock(log_action=AsyncMock())):
            await service.revoke_consent(
                db=mock_db,
                consent_id=consent.id,
                reason="Patient withdrew consent",
                user_id=uuid.uuid4(),
            )

        assert consent.revoked_at is not None
        assert consent.revocation_reason == "Patient withdrew consent"

    @pytest.mark.asyncio
    async def test_revoke_already_revoked_raises(self):
        """Revoking an already-revoked consent raises ConsentAlreadyRevokedError."""
        from app.modules.registration.service_consent import ConsentService

        consent = MagicMock()
        consent.id = uuid.uuid4()
        consent.revoked_at = datetime.now(timezone.utc)  # Already revoked

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = consent
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service = ConsentService()

        with pytest.raises(ConsentAlreadyRevokedError):
            await service.revoke_consent(
                db=mock_db,
                consent_id=consent.id,
                reason="Duplicate revocation attempt",
                user_id=uuid.uuid4(),
            )
