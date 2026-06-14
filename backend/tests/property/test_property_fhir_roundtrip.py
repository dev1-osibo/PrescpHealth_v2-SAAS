"""
Property Test: FHIR Round-Trip Compatibility (Layer 1).

Property: parse(print(record)) ≡ record for encounters, prescriptions, lab orders.

Uses Hypothesis strategies to generate valid encounter/prescription/lab order data,
converts to FHIR R4 format, parses back, and verifies key fields are preserved.

Some fields may not round-trip perfectly (computed fields, server-assigned IDs).
We test the semantically meaningful fields that MUST survive the cycle:
- status, patient_id, clinician references, codes, dates, priorities

**Validates: EMR Layer 1 — FHIR Interoperability Data Integrity**
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
# Strategies: Realistic clinical data generators
# ---------------------------------------------------------------------------
encounter_class_st = st.sampled_from([
    EncounterClass.AMBULATORY, EncounterClass.INPATIENT, EncounterClass.EMERGENCY,
])

encounter_status_st = st.sampled_from([
    EncounterStatus.PLANNED, EncounterStatus.IN_PROGRESS,
    EncounterStatus.COMPLETED, EncounterStatus.CANCELLED,
])

prescription_status_st = st.sampled_from([
    PrescriptionStatus.ACTIVE, PrescriptionStatus.COMPLETED,
    PrescriptionStatus.DISCONTINUED, PrescriptionStatus.ON_HOLD,
])

lab_priority_st = st.sampled_from([
    LabPriority.ROUTINE, LabPriority.URGENT, LabPriority.STAT,
])

lab_status_st = st.sampled_from([
    LabOrderStatus.ORDERED, LabOrderStatus.SPECIMEN_COLLECTED,
    LabOrderStatus.IN_PROGRESS, LabOrderStatus.RESULTED,
    LabOrderStatus.CANCELLED,
])

# Clinical text (no empty, no control chars)
reason_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z"),
                           whitelist_characters=" .,;:-"),
    min_size=3, max_size=80,
).filter(lambda s: s.strip())

drug_names = st.sampled_from([
    "Metformin", "Lisinopril", "Amlodipine", "Atorvastatin",
    "Paracetamol", "Amoxicillin", "Azithromycin", "Omeprazole",
])

atc_codes = st.sampled_from([
    "A10BA02", "C08CA01", "C09AA02", "C10AA05", "N02BE01",
    "J01CA04", "J01FA10", "P01BF01", "A02BC01", "C09CA01",
])

dosages = st.sampled_from(["500mg", "10mg", "5mg", "250mg", "20mg", "100mg"])
frequencies = st.sampled_from([
    "once daily", "twice daily", "three times daily", "every 8 hours",
])
routes = st.sampled_from(["oral", "IV", "topical", "inhaled", "sublingual"])

loinc_codes = st.sampled_from([
    "2345-7", "4548-4", "2160-0", "33914-3", "2093-3",
    "2085-9", "2571-8", "718-7", "6690-2", "1742-6",
])

test_names = st.sampled_from([
    "Glucose", "Hemoglobin A1c", "Creatinine", "Cholesterol Total",
    "HDL Cholesterol", "Triglycerides", "Complete Blood Count",
])

utc_datetime_st = st.datetimes(
    min_value=datetime(2020, 1, 1), max_value=datetime(2030, 12, 31),
).map(lambda dt: dt.replace(tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------
@pytest.mark.property
class TestPropertyFHIRRoundTrip:
    """
    Property-based tests proving FHIR round-trip preserves key fields.

    Core invariant: from_fhir(to_fhir(model)) preserves all semantically
    meaningful fields for encounters, prescriptions, and lab orders.
    """

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_encounter_roundtrip_preserves_fields(self, data):
        """
        Property: Encounter → FHIR R4 Encounter → internal dict preserves
        status, encounter_class, patient_id, clinician_id, reason_for_visit,
        and check_in_time.
        """
        # Generate encounter data
        enc_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        status = data.draw(encounter_status_st)
        enc_class = data.draw(encounter_class_st)
        reason = data.draw(reason_st)
        check_in = data.draw(utc_datetime_st)
        check_out = data.draw(utc_datetime_st) if status == EncounterStatus.COMPLETED else None

        # Build mock encounter
        mock_enc = MagicMock()
        mock_enc.id = enc_id
        mock_enc.patient_id = patient_id
        mock_enc.clinician_id = clinician_id
        mock_enc.status = status
        mock_enc.encounter_class = enc_class
        mock_enc.reason_for_visit = reason
        mock_enc.check_in_time = check_in
        mock_enc.check_out_time = check_out

        # Round-trip: to_fhir then from_fhir
        fhir_json = encounter_to_fhir(mock_enc)
        parsed = from_fhir_encounter(fhir_json)

        # Verify key fields preserved
        assert parsed["status"] == status.value
        assert parsed["encounter_class"] == enc_class.value
        assert parsed["patient_id"] == str(patient_id)
        assert parsed["clinician_id"] == str(clinician_id)
        assert parsed["reason_for_visit"] == reason
        assert parsed["check_in_time"] == check_in.isoformat()

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_prescription_roundtrip_preserves_fields(self, data):
        """
        Property: Prescription → FHIR R4 MedicationRequest → internal dict
        preserves drug_name, atc_code, patient_id, route, frequency, dosage,
        refills_allowed, and duration_days.
        """
        rx_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        prescribed_by = uuid.uuid4()
        status = data.draw(prescription_status_st)
        drug_name = data.draw(drug_names)
        atc_code = data.draw(atc_codes)
        dosage = data.draw(dosages)
        frequency = data.draw(frequencies)
        route = data.draw(routes)
        refills = data.draw(st.integers(min_value=0, max_value=12))
        duration = data.draw(st.one_of(st.none(), st.integers(1, 365)))

        # Build mock prescription
        mock_rx = MagicMock()
        mock_rx.id = rx_id
        mock_rx.patient_id = patient_id
        mock_rx.prescribed_by = prescribed_by
        mock_rx.status = status
        mock_rx.drug_name = drug_name
        mock_rx.atc_code = atc_code
        mock_rx.dosage = dosage
        mock_rx.frequency = frequency
        mock_rx.route = route
        mock_rx.refills_allowed = refills
        mock_rx.duration_days = duration

        # Round-trip
        fhir_json = prescription_to_fhir(mock_rx)
        parsed = from_fhir_prescription(fhir_json)

        # Verify medication identity preserved
        assert parsed["drug_name"] == drug_name
        assert parsed["atc_code"] == atc_code
        assert parsed["patient_id"] == str(patient_id)
        assert parsed["route"] == route
        assert parsed["frequency"] == frequency
        assert parsed["dosage"] == dosage
        assert parsed["refills_allowed"] == refills
        if duration is not None:
            assert parsed.get("duration_days") == duration

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_lab_order_roundtrip_preserves_fields(self, data):
        """
        Property: LabOrder → FHIR R4 ServiceRequest → internal dict preserves
        test_name, loinc_code, priority, patient_id, encounter_id, and
        clinical_indication.
        """
        order_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        ordered_by = uuid.uuid4()
        encounter_id = data.draw(st.one_of(st.none(), st.just(uuid.uuid4())))
        priority = data.draw(lab_priority_st)
        status = data.draw(lab_status_st)
        loinc_code = data.draw(loinc_codes)
        test_name = data.draw(test_names)
        indication = data.draw(st.one_of(st.none(), reason_st))

        # Build mock lab order
        mock_order = MagicMock()
        mock_order.id = order_id
        mock_order.patient_id = patient_id
        mock_order.ordered_by = ordered_by
        mock_order.encounter_id = encounter_id
        mock_order.status = status.value
        mock_order.priority = priority.value
        mock_order.loinc_code = loinc_code
        mock_order.test_name = test_name
        mock_order.clinical_indication = indication

        # Round-trip
        fhir_json = order_to_fhir(mock_order)
        parsed = from_fhir_order(fhir_json)

        # Verify test identification preserved
        assert parsed["test_name"] == test_name
        assert parsed["loinc_code"] == loinc_code
        assert parsed["patient_id"] == str(patient_id)
        assert parsed["priority"] == priority.value

        # Verify optional encounter link preserved
        if encounter_id is not None:
            assert parsed.get("encounter_id") == str(encounter_id)

        # Verify clinical indication preserved
        if indication is not None:
            assert parsed.get("clinical_indication") == indication
