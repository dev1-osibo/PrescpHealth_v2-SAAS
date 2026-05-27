"""
Property Test: FHIR Round-Trip Compatibility.

Property 2 from design.md:
    "For any internal model instance, converting to FHIR and back
    produces equivalent fields: from_fhir(to_fhir(model)) ≡ model."

This proves that the FHIR mappers maintain data integrity through
serialization/deserialization cycles:
1. Encounter → FHIR R4 Encounter → internal dict preserves key fields
2. Prescription → FHIR R4 MedicationRequest → internal dict preserves key fields
3. LabOrder → FHIR R4 ServiceRequest → internal dict preserves key fields

Why this matters (Interoperability + Data Integrity):
    - FHIR is the standard for health data exchange between systems
    - If round-trip loses data, external systems receive incomplete records
    - If parsing fails, imported FHIR data corrupts internal state
    - Bidirectional sync (OpenMRS, DHIS2) depends on lossless conversion

**Validates: Requirements 4.1, 4.2, 4.3, 4.5, 11.7**
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.encounters.enums import EncounterClass, EncounterStatus
from app.modules.encounters.fhir_mapper import (
    encounter_to_fhir,
    from_fhir_encounter,
)
from app.modules.prescriptions.enums import PrescriptionStatus
from app.modules.prescriptions.fhir_mapper import (
    from_fhir_prescription,
    prescription_to_fhir,
)
from app.modules.lab_orders.enums import LabOrderStatus, LabPriority
from app.modules.lab_orders.fhir_mapper import (
    from_fhir_order,
    order_to_fhir,
)


# ---------------------------------------------------------------------------
# Strategies: Generate realistic model-like objects for FHIR mapping
# ---------------------------------------------------------------------------

# Encounter class and status strategies
encounter_class_strategy = st.sampled_from([
    EncounterClass.AMBULATORY,
    EncounterClass.INPATIENT,
    EncounterClass.EMERGENCY,
])

encounter_status_strategy = st.sampled_from([
    EncounterStatus.PLANNED,
    EncounterStatus.IN_PROGRESS,
    EncounterStatus.COMPLETED,
    EncounterStatus.CANCELLED,
])

# Prescription status strategy
prescription_status_strategy = st.sampled_from([
    PrescriptionStatus.ACTIVE,
    PrescriptionStatus.COMPLETED,
    PrescriptionStatus.DISCONTINUED,
    PrescriptionStatus.ON_HOLD,
])

# Lab order priority strategy
lab_priority_strategy = st.sampled_from([
    LabPriority.ROUTINE,
    LabPriority.URGENT,
    LabPriority.STAT,
])

# Lab order status strategy (only statuses that map to known FHIR values)
lab_status_strategy = st.sampled_from([
    LabOrderStatus.ORDERED,
    LabOrderStatus.SPECIMEN_COLLECTED,
    LabOrderStatus.IN_PROGRESS,
    LabOrderStatus.RESULTED,
    LabOrderStatus.CANCELLED,
])

# Realistic clinical text strategies (no empty strings, no control chars)
reason_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
        whitelist_characters=" .,;:-"
    ),
    min_size=3,
    max_size=100,
).filter(lambda s: s.strip())

drug_name_strategy = st.sampled_from([
    "Metformin", "Lisinopril", "Amlodipine", "Atorvastatin",
    "Paracetamol", "Amoxicillin", "Azithromycin", "Omeprazole",
])

atc_code_strategy = st.sampled_from([
    "A10BA02", "C08CA01", "C09AA02", "C09CA01", "C10AA05",
    "N02BE01", "J01CA04", "J01FA10", "P01BF01", "A02BC01",
])

dosage_strategy = st.sampled_from([
    "500mg", "10mg", "5mg", "250mg", "20mg", "100mg",
])

frequency_strategy = st.sampled_from([
    "once daily", "twice daily", "three times daily",
    "every 8 hours", "every 12 hours", "at bedtime",
])

route_strategy = st.sampled_from([
    "oral", "IV", "topical", "inhaled", "sublingual", "rectal",
])

loinc_code_strategy = st.sampled_from([
    "2345-7", "4548-4", "2160-0", "33914-3", "2093-3",
    "2085-9", "2571-8", "718-7", "6690-2", "1742-6",
])

test_name_strategy = st.sampled_from([
    "Glucose", "Hemoglobin A1c", "Creatinine", "Cholesterol Total",
    "HDL Cholesterol", "Triglycerides", "Complete Blood Count",
    "White Blood Cell Count", "Potassium",
])


# ---------------------------------------------------------------------------
# Helper: Build mock model objects with required attributes
# ---------------------------------------------------------------------------
def _build_mock_encounter(
    enc_id: uuid.UUID,
    patient_id: uuid.UUID,
    clinician_id: uuid.UUID,
    status: EncounterStatus,
    encounter_class: EncounterClass,
    reason: str,
    check_in_time: datetime,
    check_out_time: datetime | None,
) -> MagicMock:
    """
    Build a mock Encounter object with all fields needed by encounter_to_fhir.

    Uses MagicMock to simulate the SQLAlchemy model without DB dependency.
    """
    mock = MagicMock()
    mock.id = enc_id
    mock.patient_id = patient_id
    mock.clinician_id = clinician_id
    mock.status = status
    mock.encounter_class = encounter_class
    mock.reason_for_visit = reason
    mock.check_in_time = check_in_time
    mock.check_out_time = check_out_time
    return mock


def _build_mock_prescription(
    rx_id: uuid.UUID,
    patient_id: uuid.UUID,
    prescribed_by: uuid.UUID,
    status: PrescriptionStatus,
    drug_name: str,
    atc_code: str,
    dosage: str,
    frequency: str,
    route: str,
    refills_allowed: int,
    duration_days: int | None,
) -> MagicMock:
    """
    Build a mock Prescription object with all fields needed by prescription_to_fhir.
    """
    mock = MagicMock()
    mock.id = rx_id
    mock.patient_id = patient_id
    mock.prescribed_by = prescribed_by
    mock.status = status
    mock.drug_name = drug_name
    mock.atc_code = atc_code
    mock.dosage = dosage
    mock.frequency = frequency
    mock.route = route
    mock.refills_allowed = refills_allowed
    mock.duration_days = duration_days
    return mock


def _build_mock_lab_order(
    order_id: uuid.UUID,
    patient_id: uuid.UUID,
    ordered_by: uuid.UUID,
    encounter_id: uuid.UUID | None,
    status: str,
    priority: str,
    loinc_code: str,
    test_name: str,
    clinical_indication: str | None,
) -> MagicMock:
    """
    Build a mock LabOrder object with all fields needed by order_to_fhir.
    """
    mock = MagicMock()
    mock.id = order_id
    mock.patient_id = patient_id
    mock.ordered_by = ordered_by
    mock.encounter_id = encounter_id
    mock.status = status
    mock.priority = priority
    mock.loinc_code = loinc_code
    mock.test_name = test_name
    mock.clinical_indication = clinical_indication
    return mock


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------
class TestFHIRRoundTrip:
    """
    Property-based tests proving FHIR round-trip compatibility.

    The core invariant: for any valid internal model, converting to FHIR
    and parsing back preserves all semantically meaningful fields.
    """

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_encounter_fhir_roundtrip(self, data):
        """
        Property: For any Encounter model instance,
        from_fhir_encounter(encounter_to_fhir(encounter)) produces
        equivalent fields for status, encounter_class, patient_id,
        clinician_id, reason_for_visit, and check_in_time.

        **Validates: Requirements 4.1, 4.5, 11.7**
        """
        # Generate random encounter attributes
        enc_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        status = data.draw(encounter_status_strategy)
        enc_class = data.draw(encounter_class_strategy)
        reason = data.draw(reason_strategy)
        check_in = data.draw(
            st.datetimes(
                min_value=datetime(2020, 1, 1),
                max_value=datetime(2030, 12, 31),
            ).map(lambda dt: dt.replace(tzinfo=timezone.utc))
        )
        # Completed encounters have check_out_time
        check_out = None
        if status == EncounterStatus.COMPLETED:
            # Generate a check_out after check_in (strip tz for strategy, re-add after)
            check_out = data.draw(
                st.datetimes(
                    min_value=check_in.replace(tzinfo=None),
                    max_value=datetime(2030, 12, 31),
                ).map(lambda dt: dt.replace(tzinfo=timezone.utc))
            )

        # Build mock encounter and convert to FHIR
        encounter = _build_mock_encounter(
            enc_id, patient_id, clinician_id, status, enc_class,
            reason, check_in, check_out,
        )
        fhir_json = encounter_to_fhir(encounter)

        # Parse FHIR back to internal fields
        parsed = from_fhir_encounter(fhir_json)

        # INVARIANT: Round-trip preserves key fields
        assert parsed["status"] == status.value, (
            f"Status mismatch: expected '{status.value}', got '{parsed['status']}'"
        )
        assert parsed["encounter_class"] == enc_class.value, (
            f"Class mismatch: expected '{enc_class.value}', "
            f"got '{parsed['encounter_class']}'"
        )
        assert parsed["patient_id"] == str(patient_id), (
            f"Patient ID mismatch: expected '{patient_id}', "
            f"got '{parsed['patient_id']}'"
        )
        assert parsed["clinician_id"] == str(clinician_id), (
            f"Clinician ID mismatch: expected '{clinician_id}', "
            f"got '{parsed['clinician_id']}'"
        )
        assert parsed["reason_for_visit"] == reason, (
            f"Reason mismatch: expected '{reason}', "
            f"got '{parsed['reason_for_visit']}'"
        )
        assert parsed["check_in_time"] == check_in.isoformat(), (
            f"Check-in time mismatch: expected '{check_in.isoformat()}', "
            f"got '{parsed['check_in_time']}'"
        )

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_prescription_fhir_roundtrip(self, data):
        """
        Property: For any Prescription model instance,
        from_fhir_prescription(prescription_to_fhir(prescription)) produces
        equivalent fields for drug_name, atc_code, dosage, frequency,
        route, refills_allowed, duration_days, and patient_id.

        **Validates: Requirements 4.2, 4.5, 11.7**
        """
        # Generate random prescription attributes
        rx_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        prescribed_by = uuid.uuid4()
        status = data.draw(prescription_status_strategy)
        drug_name = data.draw(drug_name_strategy)
        atc_code = data.draw(atc_code_strategy)
        dosage = data.draw(dosage_strategy)
        frequency = data.draw(frequency_strategy)
        route = data.draw(route_strategy)
        refills_allowed = data.draw(st.integers(min_value=0, max_value=12))
        duration_days = data.draw(
            st.one_of(st.none(), st.integers(min_value=1, max_value=365))
        )

        # Build mock prescription and convert to FHIR
        prescription = _build_mock_prescription(
            rx_id, patient_id, prescribed_by, status, drug_name,
            atc_code, dosage, frequency, route, refills_allowed, duration_days,
        )
        fhir_json = prescription_to_fhir(prescription)

        # Parse FHIR back to internal fields
        parsed = from_fhir_prescription(fhir_json)

        # INVARIANT: Round-trip preserves medication identity
        assert parsed["drug_name"] == drug_name, (
            f"Drug name mismatch: expected '{drug_name}', "
            f"got '{parsed.get('drug_name')}'"
        )
        assert parsed["atc_code"] == atc_code, (
            f"ATC code mismatch: expected '{atc_code}', "
            f"got '{parsed.get('atc_code')}'"
        )
        assert parsed["patient_id"] == str(patient_id), (
            f"Patient ID mismatch: expected '{patient_id}', "
            f"got '{parsed.get('patient_id')}'"
        )

        # INVARIANT: Round-trip preserves dosage instructions
        assert parsed["route"] == route, (
            f"Route mismatch: expected '{route}', got '{parsed.get('route')}'"
        )
        assert parsed["frequency"] == frequency, (
            f"Frequency mismatch: expected '{frequency}', "
            f"got '{parsed.get('frequency')}'"
        )
        # Dosage is stored as string in doseQuantity.value
        assert parsed["dosage"] == dosage, (
            f"Dosage mismatch: expected '{dosage}', "
            f"got '{parsed.get('dosage')}'"
        )

        # INVARIANT: Round-trip preserves dispense request
        assert parsed["refills_allowed"] == refills_allowed, (
            f"Refills mismatch: expected {refills_allowed}, "
            f"got {parsed.get('refills_allowed')}"
        )
        if duration_days is not None:
            assert parsed.get("duration_days") == duration_days, (
                f"Duration mismatch: expected {duration_days}, "
                f"got {parsed.get('duration_days')}"
            )

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_lab_order_fhir_roundtrip(self, data):
        """
        Property: For any LabOrder model instance,
        from_fhir_order(order_to_fhir(lab_order)) produces equivalent
        fields for test_name, loinc_code, priority, and patient_id.

        **Validates: Requirements 4.3, 4.5, 11.7**
        """
        # Generate random lab order attributes
        order_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        ordered_by = uuid.uuid4()
        # Some lab orders are linked to encounters, some are standalone
        encounter_id = data.draw(
            st.one_of(st.none(), st.just(uuid.uuid4()))
        )
        priority = data.draw(lab_priority_strategy)
        status = data.draw(lab_status_strategy)
        loinc_code = data.draw(loinc_code_strategy)
        test_name = data.draw(test_name_strategy)
        clinical_indication = data.draw(
            st.one_of(st.none(), reason_strategy)
        )

        # Build mock lab order and convert to FHIR
        lab_order = _build_mock_lab_order(
            order_id, patient_id, ordered_by, encounter_id,
            status.value, priority.value, loinc_code, test_name,
            clinical_indication,
        )
        fhir_json = order_to_fhir(lab_order)

        # Parse FHIR back to internal fields
        parsed = from_fhir_order(fhir_json)

        # INVARIANT: Round-trip preserves test identification
        assert parsed["test_name"] == test_name, (
            f"Test name mismatch: expected '{test_name}', "
            f"got '{parsed.get('test_name')}'"
        )
        assert parsed["loinc_code"] == loinc_code, (
            f"LOINC code mismatch: expected '{loinc_code}', "
            f"got '{parsed.get('loinc_code')}'"
        )
        assert parsed["patient_id"] == str(patient_id), (
            f"Patient ID mismatch: expected '{patient_id}', "
            f"got '{parsed.get('patient_id')}'"
        )

        # INVARIANT: Round-trip preserves priority
        assert parsed["priority"] == priority.value, (
            f"Priority mismatch: expected '{priority.value}', "
            f"got '{parsed.get('priority')}'"
        )

        # INVARIANT: Round-trip preserves encounter link (if present)
        if encounter_id is not None:
            assert parsed.get("encounter_id") == str(encounter_id), (
                f"Encounter ID mismatch: expected '{encounter_id}', "
                f"got '{parsed.get('encounter_id')}'"
            )

        # INVARIANT: Round-trip preserves clinical indication (if present)
        if clinical_indication is not None:
            assert parsed.get("clinical_indication") == clinical_indication, (
                f"Clinical indication mismatch: expected '{clinical_indication}', "
                f"got '{parsed.get('clinical_indication')}'"
            )
