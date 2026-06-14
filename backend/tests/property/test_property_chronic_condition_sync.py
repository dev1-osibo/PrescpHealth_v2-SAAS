"""
Property Test: Chronic Condition Synchronization (Property 4).

Invariant:
    When a diagnosis is recorded with is_chronic=True, the patient's
    chronic_conditions JSONB field is updated to include the new condition.
    When is_chronic=False, the patient's chronic_conditions remain unchanged.

Why this matters (Clinical Safety):
    Chronic condition tracking drives risk computation, drug-health
    interaction checks, and longitudinal care planning. If a chronic
    diagnosis fails to sync, the patient's risk profile becomes stale
    and dangerous drug-health interactions may go undetected.

Tested service: app.modules.encounters.service_diagnosis.DiagnosisService
Method: record_diagnosis(db, encounter_id, patient_id, tenant_id,
    user_id, icd10_code, is_chronic, is_primary)

**Validates: Requirement 2.2 — Chronic condition synchronization**
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.encounters.enums import EncounterStatus

# Import models so SQLAlchemy mappers resolve correctly
import app.modules.encounters.models  # noqa: F401
import app.modules.patients.models  # noqa: F401
import app.modules.prescriptions.models  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies: Generate diagnosis-related data
# ---------------------------------------------------------------------------

# ICD-10 codes follow pattern: letter + 2 digits + optional "." + digits
icd10_strategy = st.from_regex(r"[A-Z]\d{2}\.\d{1,2}", fullmatch=True)

# Display names for conditions (synthetic, never real PHI)
display_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
    min_size=5,
    max_size=50,
)


# ---------------------------------------------------------------------------
# Property Tests: Chronic Condition Sync
# ---------------------------------------------------------------------------
class TestChronicConditionSync:
    """
    Property-based tests proving chronic condition synchronization.

    Core invariants:
    1. Chronic diagnosis → patient.chronic_conditions updated
    2. Non-chronic diagnosis → patient.chronic_conditions unchanged
    3. Duplicate chronic codes are not added twice (idempotent)
    """

    @given(icd10_code=icd10_strategy, display_name=display_name_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_chronic_diagnosis_syncs_to_patient(
        self, icd10_code, display_name
    ):
        """
        Property: Recording a diagnosis with is_chronic=True adds the
        condition to patient.chronic_conditions JSONB.

        After record_diagnosis completes, the patient's chronic_conditions
        list must contain an entry with the matching ICD-10 code.
        """
        from app.modules.encounters.service_diagnosis import DiagnosisService
        from app.modules.patients.patient_model import Patient

        encounter_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock patient with empty chronic_conditions
        mock_patient = MagicMock(spec=Patient)
        mock_patient.id = patient_id
        mock_patient.chronic_conditions = []

        # Mock encounter row (in_progress, modifiable)
        mock_encounter_row = MagicMock()
        mock_encounter_row.status = EncounterStatus.IN_PROGRESS

        # Mock DB session
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # execute() returns different results depending on the query
        encounter_result = MagicMock()
        encounter_result.one_or_none.return_value = mock_encounter_row

        patient_result = MagicMock()
        patient_result.scalar_one_or_none.return_value = mock_patient

        mock_db.execute = AsyncMock(
            side_effect=[encounter_result, patient_result]
        )

        with patch(
            "app.modules.encounters.service_diagnosis._code_catalog.validate_code",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.service_diagnosis._code_catalog.lookup_code",
            new_callable=AsyncMock,
            return_value={"display_name": display_name},
        ), patch(
            "app.modules.encounters.service_diagnosis._audit.log",
            new_callable=AsyncMock,
        ):
            service = DiagnosisService()
            await service.record_diagnosis(
                db=mock_db,
                encounter_id=encounter_id,
                patient_id=patient_id,
                tenant_id=tenant_id,
                user_id=user_id,
                icd10_code=icd10_code,
                is_chronic=True,
                is_primary=False,
            )

        # INVARIANT: Patient chronic_conditions now contains the code
        codes_in_list = [
            c.get("code") for c in mock_patient.chronic_conditions
            if isinstance(c, dict)
        ]
        assert icd10_code in codes_in_list, (
            f"Chronic condition {icd10_code} was not synced to patient record. "
            f"Current conditions: {mock_patient.chronic_conditions}"
        )

    @given(icd10_code=icd10_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_non_chronic_diagnosis_does_not_sync(
        self, icd10_code
    ):
        """
        Property: Recording a diagnosis with is_chronic=False does NOT
        modify patient.chronic_conditions.

        Non-chronic diagnoses (e.g., acute infections, injuries) are
        encounter-specific and should never appear in the patient's
        longitudinal chronic condition list.
        """
        from app.modules.encounters.service_diagnosis import DiagnosisService
        from app.modules.patients.patient_model import Patient

        encounter_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock patient with pre-existing conditions (should remain unchanged)
        existing_conditions = [
            {"code": "E11.9", "display_name": "Type 2 diabetes"}
        ]
        mock_patient = MagicMock(spec=Patient)
        mock_patient.id = patient_id
        mock_patient.chronic_conditions = list(existing_conditions)

        # Mock encounter row
        mock_encounter_row = MagicMock()
        mock_encounter_row.status = EncounterStatus.IN_PROGRESS

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        encounter_result = MagicMock()
        encounter_result.one_or_none.return_value = mock_encounter_row

        # For non-chronic, _sync_chronic_condition is never called,
        # so patient query should not happen
        mock_db.execute = AsyncMock(return_value=encounter_result)

        with patch(
            "app.modules.encounters.service_diagnosis._code_catalog.validate_code",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.service_diagnosis._code_catalog.lookup_code",
            new_callable=AsyncMock,
            return_value={"display_name": "Acute condition"},
        ), patch(
            "app.modules.encounters.service_diagnosis._audit.log",
            new_callable=AsyncMock,
        ):
            service = DiagnosisService()
            await service.record_diagnosis(
                db=mock_db,
                encounter_id=encounter_id,
                patient_id=patient_id,
                tenant_id=tenant_id,
                user_id=user_id,
                icd10_code=icd10_code,
                is_chronic=False,
                is_primary=False,
            )

        # INVARIANT: Patient chronic_conditions unchanged
        assert mock_patient.chronic_conditions == existing_conditions, (
            f"Non-chronic diagnosis modified patient conditions. "
            f"Expected {existing_conditions}, got {mock_patient.chronic_conditions}"
        )

    @given(icd10_code=icd10_strategy, display_name=display_name_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    @pytest.mark.property
    async def test_property_duplicate_chronic_not_added_twice(
        self, icd10_code, display_name
    ):
        """
        Property: Recording the same chronic condition code twice does
        NOT create a duplicate entry in patient.chronic_conditions.

        The sync is idempotent — re-diagnosing an existing chronic
        condition at a new encounter should not bloat the patient record.
        """
        from app.modules.encounters.service_diagnosis import DiagnosisService
        from app.modules.patients.patient_model import Patient

        encounter_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Patient already has this chronic condition
        existing_conditions = [
            {"code": icd10_code, "display_name": display_name}
        ]
        mock_patient = MagicMock(spec=Patient)
        mock_patient.id = patient_id
        mock_patient.chronic_conditions = list(existing_conditions)

        mock_encounter_row = MagicMock()
        mock_encounter_row.status = EncounterStatus.IN_PROGRESS

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        encounter_result = MagicMock()
        encounter_result.one_or_none.return_value = mock_encounter_row

        patient_result = MagicMock()
        patient_result.scalar_one_or_none.return_value = mock_patient

        mock_db.execute = AsyncMock(
            side_effect=[encounter_result, patient_result]
        )

        with patch(
            "app.modules.encounters.service_diagnosis._code_catalog.validate_code",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.service_diagnosis._code_catalog.lookup_code",
            new_callable=AsyncMock,
            return_value={"display_name": display_name},
        ), patch(
            "app.modules.encounters.service_diagnosis._audit.log",
            new_callable=AsyncMock,
        ):
            service = DiagnosisService()
            await service.record_diagnosis(
                db=mock_db,
                encounter_id=encounter_id,
                patient_id=patient_id,
                tenant_id=tenant_id,
                user_id=user_id,
                icd10_code=icd10_code,
                is_chronic=True,
                is_primary=False,
            )

        # INVARIANT: No duplicate — count of this code is exactly 1
        code_count = sum(
            1 for c in mock_patient.chronic_conditions
            if isinstance(c, dict) and c.get("code") == icd10_code
        )
        assert code_count == 1, (
            f"Duplicate chronic condition: {icd10_code} appears {code_count} "
            f"times in {mock_patient.chronic_conditions}"
        )
