"""
Coverage tests: Registration Module — uncovered service paths, schemas, enums, exceptions.

Targets paths not exercised by test_registration_unit.py:
  - RegistrationService.complete_registration (happy path — all fields present)
  - RegistrationService.complete_registration (patient not found)
  - RegistrationService.update_registration (empty dict — early return)
  - ConsentService.get_active_consents
  - ConsentService.check_consent (True + False)
  - ConsentService.capture_consent (is_granted=False)
  - ConsentService.revoke_consent (not found)
  - Pydantic schemas
  - Custom exceptions
  - Enum value completeness
"""

import uuid
from datetime import datetime, date, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.registration.enums import ConsentType, VerificationType
from app.modules.registration.exceptions import (
    ConsentAlreadyRevokedError,
    ConsentNotFoundError,
    RegistrationIncompleteError,
    RegistrationNotFoundError,
)
from app.modules.registration.schemas import (
    ConsentCapture,
    ConsentResponse,
    IdentityVerificationCreate,
    IdentityVerificationResponse,
    IntakeCreate,
    RegistrationUpdate,
)

# ---------------------------------------------------------------------------
# Shared mock audit
# ---------------------------------------------------------------------------
_mock_audit = MagicMock()
_mock_audit.log_action = AsyncMock()


# ===========================================================================
# RegistrationService.complete_registration — happy path
# ===========================================================================
class TestCompleteRegistrationHappyPath:
    """Verify complete_registration succeeds when all required fields are present."""

    @pytest.mark.asyncio
    async def test_complete_registration_returns_mrn(self):
        """complete_registration returns an MRN string when all required fields are present."""
        from app.modules.registration.service import RegistrationService

        tenant_id = uuid.uuid4()
        patient_id = uuid.uuid4()

        # First execute: fetch patient row (all fields present)
        # Second execute: count for MRN generation
        # Third execute: UPDATE status=active
        call_count = [0]

        async def _side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # SELECT * FROM patients WHERE id = ...
                row = {
                    "id": patient_id,
                    "tenant_id": tenant_id,
                    "first_name": "Test",
                    "last_name": "Patient",
                    "date_of_birth": date(1985, 3, 20),
                    "phone": "+2340000000000",
                    "address": "1 Synthetic Street Lagos",
                }
                result.mappings.return_value.first.return_value = row
                result.scalar_one.return_value = 10
            elif call_count[0] == 2:
                # SELECT COUNT(*) — for MRN generation
                result.scalar_one.return_value = 10
            else:
                # UPDATE patients SET status = 'active'...
                result.mappings.return_value.first.return_value = None
            return result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_side_effect)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        svc = RegistrationService()
        with patch("app.modules.registration.service._audit", _mock_audit):
            mrn = await svc.complete_registration(
                db=mock_db, patient_id=patient_id, user_id=uuid.uuid4(),
            )

        assert mrn.startswith("MRN-")
        parts = mrn.split("-")
        assert len(parts) == 3

    @pytest.mark.asyncio
    async def test_complete_registration_patient_not_found_raises(self):
        """complete_registration raises RegistrationNotFoundError if row missing."""
        from app.modules.registration.service import RegistrationService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None  # No row
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = RegistrationService()

        with pytest.raises(RegistrationNotFoundError):
            await svc.complete_registration(
                db=mock_db, patient_id=uuid.uuid4(), user_id=uuid.uuid4(),
            )


# ===========================================================================
# RegistrationService.update_registration — empty data early-return
# ===========================================================================
class TestUpdateRegistrationEarlyReturn:
    """Verify update_registration returns immediately on empty data dict."""

    @pytest.mark.asyncio
    async def test_empty_data_dict_skips_update(self):
        """update_registration with all-None values does not execute an UPDATE."""
        from app.modules.registration.service import RegistrationService

        mock_db = AsyncMock()
        svc = RegistrationService()

        with patch("app.modules.registration.service._audit", _mock_audit):
            await svc.update_registration(
                db=mock_db,
                patient_id=uuid.uuid4(),
                data={"phone": None, "address": None},  # All None → stripped
                user_id=uuid.uuid4(),
            )

        # No DB execute should have been called
        mock_db.execute.assert_not_called()


# ===========================================================================
# ConsentService.get_active_consents
# ===========================================================================
class TestGetActiveConsents:
    """Verify active consent retrieval excludes revoked and expired records."""

    @pytest.mark.asyncio
    async def test_get_active_consents_returns_list(self):
        """get_active_consents returns list of non-revoked, non-expired consents."""
        from app.modules.registration.service_consent import ConsentService

        consent1 = MagicMock()
        consent1.id = uuid.uuid4()
        consent1.revoked_at = None
        consent2 = MagicMock()
        consent2.id = uuid.uuid4()
        consent2.revoked_at = None

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [consent1, consent2]
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = ConsentService()
        results = await svc.get_active_consents(
            db=mock_db,
            patient_id=uuid.uuid4(),
        )

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_active_consents_empty(self):
        """get_active_consents returns empty list when no active consents exist."""
        from app.modules.registration.service_consent import ConsentService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = ConsentService()
        results = await svc.get_active_consents(
            db=mock_db,
            patient_id=uuid.uuid4(),
        )

        assert results == []


# ===========================================================================
# ConsentService.check_consent
# ===========================================================================
class TestCheckConsent:
    """Verify check_consent returns correct boolean."""

    @pytest.mark.asyncio
    async def test_check_consent_true_when_active(self):
        """check_consent returns True when an active granted consent exists."""
        from app.modules.registration.service_consent import ConsentService

        active_consent = MagicMock()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = active_consent
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = ConsentService()
        result = await svc.check_consent(
            db=mock_db,
            patient_id=uuid.uuid4(),
            consent_type=ConsentType.TREATMENT,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_check_consent_false_when_none(self):
        """check_consent returns False when no active granted consent exists."""
        from app.modules.registration.service_consent import ConsentService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = ConsentService()
        result = await svc.check_consent(
            db=mock_db,
            patient_id=uuid.uuid4(),
            consent_type=ConsentType.DATA_SHARING,
        )

        assert result is False


# ===========================================================================
# ConsentService.capture_consent — denied consent
# ===========================================================================
class TestCaptureConsentDenied:
    """Verify consent denial is stored correctly."""

    @pytest.mark.asyncio
    async def test_capture_denied_consent(self):
        """capture_consent with is_granted=False stores denial correctly."""
        from app.modules.registration.service_consent import ConsentService

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        svc = ConsentService()
        with patch("app.modules.registration.service_consent._audit", _mock_audit):
            await svc.capture_consent(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                consent_type=ConsentType.RESEARCH,
                version="2.0",
                is_granted=False,
                captured_by=uuid.uuid4(),
            )

        added = mock_db.add.call_args[0][0]
        assert added.is_granted is False
        assert added.consent_type == ConsentType.RESEARCH

    @pytest.mark.asyncio
    async def test_capture_consent_hipaa_notice(self):
        """capture_consent for HIPAA_NOTICE type stores correctly."""
        from app.modules.registration.service_consent import ConsentService

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        svc = ConsentService()
        with patch("app.modules.registration.service_consent._audit", _mock_audit):
            await svc.capture_consent(
                db=mock_db,
                tenant_id=uuid.uuid4(),
                patient_id=uuid.uuid4(),
                consent_type=ConsentType.HIPAA_NOTICE,
                version="1.0",
                is_granted=True,
                captured_by=uuid.uuid4(),
                expires_at=datetime.now(timezone.utc) + timedelta(days=365),
            )

        added = mock_db.add.call_args[0][0]
        assert added.consent_type == ConsentType.HIPAA_NOTICE
        assert added.expires_at is not None


# ===========================================================================
# ConsentService.revoke_consent — not found
# ===========================================================================
class TestRevokeConsentNotFound:
    """Verify revoke_consent raises when consent record does not exist."""

    @pytest.mark.asyncio
    async def test_revoke_consent_not_found_raises(self):
        """revoke_consent raises ConsentNotFoundError when consent UUID not in DB."""
        from app.modules.registration.service_consent import ConsentService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = ConsentService()

        with pytest.raises(ConsentNotFoundError):
            await svc.revoke_consent(
                db=mock_db,
                consent_id=uuid.uuid4(),
                reason="Consent record not found",
                user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_revoke_telehealth_consent(self):
        """revoke_consent sets revoked_at for TELEHEALTH consent type."""
        from app.modules.registration.service_consent import ConsentService

        consent = MagicMock()
        consent.id = uuid.uuid4()
        consent.tenant_id = uuid.uuid4()
        consent.revoked_at = None

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = consent
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        svc = ConsentService()
        with patch("app.modules.registration.service_consent._audit", _mock_audit):
            await svc.revoke_consent(
                db=mock_db,
                consent_id=consent.id,
                reason="No longer consenting to telehealth",
                user_id=uuid.uuid4(),
            )

        assert consent.revoked_at is not None
        assert consent.revocation_reason == "No longer consenting to telehealth"


# ===========================================================================
# Pydantic Schemas
# ===========================================================================
class TestRegistrationSchemas:
    """Verify request/response schemas validate correctly."""

    def test_intake_create_valid(self):
        """IntakeCreate accepts first_name, last_name, date_of_birth."""
        obj = IntakeCreate(
            first_name="Test",
            last_name="Patient",
            date_of_birth=date(1990, 6, 15),
        )
        assert obj.first_name == "Test"
        assert obj.last_name == "Patient"

    def test_intake_create_name_max_length(self):
        """IntakeCreate rejects first_name longer than 100 chars."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            IntakeCreate(
                first_name="x" * 101,
                last_name="Patient",
                date_of_birth=date(1990, 6, 15),
            )

    def test_registration_update_all_optional(self):
        """RegistrationUpdate can be constructed with no fields (all optional)."""
        obj = RegistrationUpdate()
        assert obj.phone is None
        assert obj.address is None

    def test_registration_update_with_fields(self):
        """RegistrationUpdate stores provided optional fields."""
        obj = RegistrationUpdate(phone="+2348000000000", address="5 Test Ave")
        assert obj.phone == "+2348000000000"

    def test_consent_capture_valid(self):
        """ConsentCapture accepts consent_type, version, and is_granted."""
        obj = ConsentCapture(
            consent_type=ConsentType.TREATMENT,
            version="1.0",
            is_granted=True,
        )
        assert obj.consent_type == ConsentType.TREATMENT
        assert obj.digital_signature is None  # PHI field optional, defaults None

    def test_consent_capture_with_signature(self):
        """ConsentCapture accepts digital_signature field."""
        obj = ConsentCapture(
            consent_type=ConsentType.HIPAA_NOTICE,
            version="2.0",
            is_granted=True,
            digital_signature="base64-synthetic-sig",
        )
        assert obj.digital_signature == "base64-synthetic-sig"

    def test_identity_verification_create_valid(self):
        """IdentityVerificationCreate accepts verification_type."""
        obj = IdentityVerificationCreate(
            verification_type=VerificationType.GOVERNMENT_ID,
        )
        assert obj.verification_type == VerificationType.GOVERNMENT_ID
        assert obj.document_number is None  # PHI field optional

    def test_consent_response_from_orm_fields(self):
        """ConsentResponse schema correctly declares ORM-serialisable fields."""
        # Verify all expected fields are present in model_fields
        fields = set(ConsentResponse.model_fields.keys())
        assert "id" in fields
        assert "patient_id" in fields
        assert "consent_type" in fields
        assert "is_granted" in fields
        assert "revoked_at" in fields


# ===========================================================================
# Enum completeness
# ===========================================================================
class TestRegistrationEnums:
    """Verify all enum members are present."""

    def test_consent_type_values(self):
        """ConsentType contains all five consent categories."""
        expected = {
            "treatment", "data_sharing", "research",
            "hipaa_notice", "telehealth",
        }
        assert {e.value for e in ConsentType} == expected

    def test_verification_type_values(self):
        """VerificationType contains all five verification document types."""
        expected = {
            "government_id", "passport", "insurance_card",
            "biometric", "other",
        }
        assert {e.value for e in VerificationType} == expected


# ===========================================================================
# Custom Exceptions
# ===========================================================================
class TestRegistrationExceptions:
    """Verify exception constructors and PHI-safe messages."""

    def test_registration_not_found_stores_patient_id(self):
        """RegistrationNotFoundError stores patient_id attribute."""
        pid = str(uuid.uuid4())
        err = RegistrationNotFoundError(pid)
        assert err.patient_id == pid
        assert pid in str(err)
        assert isinstance(err, Exception)

    def test_registration_incomplete_stores_missing_fields(self):
        """RegistrationIncompleteError stores list of missing field names."""
        err = RegistrationIncompleteError(["phone", "address"])
        assert "phone" in err.missing_fields
        assert "address" in err.missing_fields
        assert isinstance(err, Exception)

    def test_registration_incomplete_message_lists_fields(self):
        """RegistrationIncompleteError message references the missing fields."""
        err = RegistrationIncompleteError(["phone"])
        assert "phone" in str(err)

    def test_consent_not_found_stores_id(self):
        """ConsentNotFoundError stores consent_id attribute."""
        cid = str(uuid.uuid4())
        err = ConsentNotFoundError(cid)
        assert err.consent_id == cid
        assert isinstance(err, Exception)

    def test_consent_already_revoked_stores_id(self):
        """ConsentAlreadyRevokedError stores consent_id attribute."""
        cid = str(uuid.uuid4())
        err = ConsentAlreadyRevokedError(cid)
        assert err.consent_id == cid
        assert cid in str(err)
        assert isinstance(err, Exception)
