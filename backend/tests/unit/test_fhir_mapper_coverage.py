"""
Coverage tests: FHIR mapper uncovered branches across encounters, lab_orders,
and prescriptions modules.

Targets:
  - encounters/fhir_mapper.py lines 195-232, 241  (from_fhir_encounter + _format_dt)
  - lab_orders/fhir_mapper.py lines 105, 165, 204-238, 247
      (encounter/indication branches, abnormal flag, from_fhir_order, _format_dt)
  - prescriptions/fhir_mapper.py lines 140-193   (from_fhir_prescription)

All functions are pure transforms (no DB) — no mocking of async infrastructure.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared helper: build mock ORM-like object from kwargs
# ---------------------------------------------------------------------------
def _obj(**kw):
    """Return a MagicMock with attributes set from kwargs."""
    obj = MagicMock()
    for k, v in kw.items():
        setattr(obj, k, v)
    return obj


# ===========================================================================
# encounters/fhir_mapper.py — from_fhir_encounter + _format_dt
# ===========================================================================
class TestEncounterFromFhir:
    """Verify from_fhir_encounter parses all supported FHIR Encounter fields."""

    def test_from_fhir_encounter_extracts_status(self):
        """from_fhir_encounter extracts status from FHIR JSON."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        fhir = {"status": "finished"}
        result = from_fhir_encounter(fhir)

        assert result["status"] == "finished"

    def test_from_fhir_encounter_maps_amb_class(self):
        """from_fhir_encounter maps FHIR class code AMB to 'ambulatory'."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        fhir = {"class": {"code": "AMB"}}
        result = from_fhir_encounter(fhir)

        assert result["encounter_class"] == "ambulatory"

    def test_from_fhir_encounter_maps_imp_class(self):
        """from_fhir_encounter maps IMP to 'inpatient'."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        fhir = {"class": {"code": "IMP"}}
        result = from_fhir_encounter(fhir)

        assert result["encounter_class"] == "inpatient"

    def test_from_fhir_encounter_maps_emer_class(self):
        """from_fhir_encounter maps EMER to 'emergency'."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        fhir = {"class": {"code": "EMER"}}
        result = from_fhir_encounter(fhir)

        assert result["encounter_class"] == "emergency"

    def test_from_fhir_encounter_unknown_class_defaults_ambulatory(self):
        """from_fhir_encounter defaults to 'ambulatory' for unrecognised class code."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        fhir = {"class": {"code": "UNKNOWN_CODE"}}
        result = from_fhir_encounter(fhir)

        assert result["encounter_class"] == "ambulatory"

    def test_from_fhir_encounter_extracts_patient_id(self):
        """from_fhir_encounter strips 'Patient/' prefix from subject reference."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        patient_id = str(uuid.uuid4())
        fhir = {"subject": {"reference": f"Patient/{patient_id}"}}
        result = from_fhir_encounter(fhir)

        assert result["patient_id"] == patient_id

    def test_from_fhir_encounter_extracts_clinician_id(self):
        """from_fhir_encounter strips 'Practitioner/' prefix from participant reference."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        clinician_id = str(uuid.uuid4())
        fhir = {
            "participant": [
                {"individual": {"reference": f"Practitioner/{clinician_id}"}}
            ]
        }
        result = from_fhir_encounter(fhir)

        assert result["clinician_id"] == clinician_id

    def test_from_fhir_encounter_extracts_reason_for_visit(self):
        """from_fhir_encounter extracts chief complaint from reasonCode[0].text."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        fhir = {"reasonCode": [{"text": "Chest pain evaluation"}]}
        result = from_fhir_encounter(fhir)

        assert result["reason_for_visit"] == "Chest pain evaluation"

    def test_from_fhir_encounter_extracts_check_in_time(self):
        """from_fhir_encounter extracts period.start as check_in_time."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        ts = "2025-08-01T09:00:00+00:00"
        fhir = {"period": {"start": ts}}
        result = from_fhir_encounter(fhir)

        assert result["check_in_time"] == ts

    def test_from_fhir_encounter_empty_json(self):
        """from_fhir_encounter returns dict with default encounter_class for empty input."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        result = from_fhir_encounter({})

        # Default class code falls back to AMB → ambulatory
        assert result["encounter_class"] == "ambulatory"
        # No other keys extracted from empty dict
        assert "status" not in result

    def test_from_fhir_encounter_full_payload(self):
        """from_fhir_encounter correctly parses a complete representative FHIR Encounter."""
        from app.modules.encounters.fhir_mapper import from_fhir_encounter

        patient_id = str(uuid.uuid4())
        clinician_id = str(uuid.uuid4())
        fhir = {
            "status": "in-progress",
            "class": {"code": "AMB"},
            "subject": {"reference": f"Patient/{patient_id}"},
            "participant": [{"individual": {"reference": f"Practitioner/{clinician_id}"}}],
            "reasonCode": [{"text": "Annual wellness visit"}],
            "period": {"start": "2025-08-01T08:00:00Z"},
        }
        result = from_fhir_encounter(fhir)

        assert result["status"] == "in-progress"
        assert result["encounter_class"] == "ambulatory"
        assert result["patient_id"] == patient_id
        assert result["clinician_id"] == clinician_id
        assert result["reason_for_visit"] == "Annual wellness visit"
        assert result["check_in_time"] == "2025-08-01T08:00:00Z"


class TestEncounterFormatDt:
    """Verify _format_dt helper handles datetime and None correctly."""

    def test_format_dt_none_returns_none(self):
        """_format_dt returns None when passed None."""
        from app.modules.encounters.fhir_mapper import _format_dt

        assert _format_dt(None) is None

    def test_format_dt_returns_iso_string(self):
        """_format_dt converts a datetime to ISO-8601 string."""
        from app.modules.encounters.fhir_mapper import _format_dt

        ts = datetime(2025, 8, 1, 9, 0, 0, tzinfo=timezone.utc)
        result = _format_dt(ts)

        assert isinstance(result, str)
        assert "2025-08-01" in result


# ===========================================================================
# lab_orders/fhir_mapper.py — uncovered branches and functions
# ===========================================================================
class TestLabOrderToFhirBranches:
    """Verify order_to_fhir covers the encounter_id and clinical_indication branches."""

    def test_order_to_fhir_with_encounter_id(self):
        """order_to_fhir includes encounter reference when encounter_id is set."""
        from app.modules.lab_orders.fhir_mapper import order_to_fhir

        enc_id = uuid.uuid4()
        lab_order = _obj(
            id=uuid.uuid4(),
            status="ordered",
            priority="routine",
            loinc_code="2093-3",
            test_name="Total Cholesterol",
            patient_id=uuid.uuid4(),
            ordered_by=uuid.uuid4(),
            encounter_id=enc_id,
            clinical_indication=None,
        )

        result = order_to_fhir(lab_order)

        assert "encounter" in result
        assert f"Encounter/{enc_id}" == result["encounter"]["reference"]

    def test_order_to_fhir_with_clinical_indication(self):
        """order_to_fhir includes reasonCode when clinical_indication is set."""
        from app.modules.lab_orders.fhir_mapper import order_to_fhir

        lab_order = _obj(
            id=uuid.uuid4(),
            status="in_progress",
            priority="urgent",
            loinc_code="718-7",
            test_name="Hemoglobin",
            patient_id=uuid.uuid4(),
            ordered_by=uuid.uuid4(),
            encounter_id=None,
            clinical_indication="Suspected anaemia",
        )

        result = order_to_fhir(lab_order)

        assert "reasonCode" in result
        assert result["reasonCode"][0]["text"] == "Suspected anaemia"

    def test_order_to_fhir_without_optional_fields(self):
        """order_to_fhir produces clean ServiceRequest with no optional extras."""
        from app.modules.lab_orders.fhir_mapper import order_to_fhir

        lab_order = _obj(
            id=uuid.uuid4(),
            status="resulted",
            priority="stat",
            loinc_code="2160-0",
            test_name="Creatinine",
            patient_id=uuid.uuid4(),
            ordered_by=uuid.uuid4(),
            encounter_id=None,
            clinical_indication=None,
        )

        result = order_to_fhir(lab_order)

        assert result["resourceType"] == "ServiceRequest"
        assert result["status"] == "completed"  # resulted → completed
        assert result["priority"] == "stat"
        assert "encounter" not in result
        assert "reasonCode" not in result


class TestLabResultToFhirAbnormal:
    """Verify result_to_fhir covers the abnormal flag interpretation branch."""

    def test_result_to_fhir_abnormal_flag(self):
        """result_to_fhir includes FHIR interpretation when is_abnormal is True."""
        from app.modules.lab_orders.fhir_mapper import result_to_fhir

        lab_result = _obj(
            id=uuid.uuid4(),
            value="9.5",
            numeric_value=9.5,
            unit="g/dL",
            reference_range_low=11.5,
            reference_range_high=16.5,
            is_abnormal=True,
            resulted_at=datetime.now(timezone.utc),
        )

        result = result_to_fhir(lab_result)

        assert "contained" in result
        observation = result["contained"][0]
        assert "interpretation" in observation
        assert observation["interpretation"][0]["coding"][0]["code"] == "A"

    def test_result_to_fhir_normal_no_interpretation(self):
        """result_to_fhir omits interpretation block for normal results."""
        from app.modules.lab_orders.fhir_mapper import result_to_fhir

        lab_result = _obj(
            id=uuid.uuid4(),
            value="14.0",
            numeric_value=14.0,
            unit="g/dL",
            reference_range_low=11.5,
            reference_range_high=16.5,
            is_abnormal=False,
            resulted_at=datetime.now(timezone.utc),
        )

        result = result_to_fhir(lab_result)

        observation = result["contained"][0]
        assert "interpretation" not in observation

    def test_result_to_fhir_with_reference_ranges(self):
        """result_to_fhir includes both low and high reference range bounds."""
        from app.modules.lab_orders.fhir_mapper import result_to_fhir

        lab_result = _obj(
            id=uuid.uuid4(),
            value="140",
            numeric_value=140.0,
            unit="mg/dL",
            reference_range_low=70.0,
            reference_range_high=100.0,
            is_abnormal=True,
            resulted_at=None,
        )

        result = result_to_fhir(lab_result)

        observation = result["contained"][0]
        assert "referenceRange" in observation
        ref_range = observation["referenceRange"][0]
        assert "low" in ref_range
        assert "high" in ref_range
        assert ref_range["low"]["value"] == 70.0
        assert ref_range["high"]["value"] == 100.0

    def test_result_to_fhir_only_low_range(self):
        """result_to_fhir includes referenceRange with only low bound."""
        from app.modules.lab_orders.fhir_mapper import result_to_fhir

        lab_result = _obj(
            id=uuid.uuid4(),
            value="5.0",
            numeric_value=5.0,
            unit="mmol/L",
            reference_range_low=3.5,
            reference_range_high=None,
            is_abnormal=False,
            resulted_at=None,
        )

        result = result_to_fhir(lab_result)

        observation = result["contained"][0]
        assert "referenceRange" in observation
        ref_range = observation["referenceRange"][0]
        assert "low" in ref_range
        assert "high" not in ref_range


class TestFromFhirOrder:
    """Verify from_fhir_order parses all FHIR ServiceRequest fields."""

    def test_from_fhir_order_extracts_priority(self):
        """from_fhir_order reverse-maps FHIR priority to internal value."""
        from app.modules.lab_orders.fhir_mapper import from_fhir_order

        result = from_fhir_order({"priority": "urgent"})

        assert result["priority"] == "urgent"

    def test_from_fhir_order_extracts_test_name_and_loinc(self):
        """from_fhir_order extracts test_name and loinc_code from code element."""
        from app.modules.lab_orders.fhir_mapper import from_fhir_order

        fhir = {
            "code": {
                "text": "Haemoglobin A1c",
                "coding": [{"code": "4548-4"}],
            }
        }
        result = from_fhir_order(fhir)

        assert result["test_name"] == "Haemoglobin A1c"
        assert result["loinc_code"] == "4548-4"

    def test_from_fhir_order_extracts_patient_id(self):
        """from_fhir_order strips 'Patient/' prefix from subject reference."""
        from app.modules.lab_orders.fhir_mapper import from_fhir_order

        patient_id = str(uuid.uuid4())
        fhir = {"subject": {"reference": f"Patient/{patient_id}"}}
        result = from_fhir_order(fhir)

        assert result["patient_id"] == patient_id

    def test_from_fhir_order_extracts_encounter_id(self):
        """from_fhir_order strips 'Encounter/' prefix from encounter reference."""
        from app.modules.lab_orders.fhir_mapper import from_fhir_order

        encounter_id = str(uuid.uuid4())
        fhir = {"encounter": {"reference": f"Encounter/{encounter_id}"}}
        result = from_fhir_order(fhir)

        assert result["encounter_id"] == encounter_id

    def test_from_fhir_order_extracts_clinical_indication(self):
        """from_fhir_order extracts clinical_indication from reasonCode[0].text."""
        from app.modules.lab_orders.fhir_mapper import from_fhir_order

        fhir = {"reasonCode": [{"text": "Monitoring diabetes control"}]}
        result = from_fhir_order(fhir)

        assert result["clinical_indication"] == "Monitoring diabetes control"

    def test_from_fhir_order_full_payload(self):
        """from_fhir_order parses a complete representative ServiceRequest."""
        from app.modules.lab_orders.fhir_mapper import from_fhir_order

        patient_id = str(uuid.uuid4())
        encounter_id = str(uuid.uuid4())
        fhir = {
            "priority": "routine",
            "code": {
                "text": "Blood Glucose",
                "coding": [{"code": "2345-7"}],
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "encounter": {"reference": f"Encounter/{encounter_id}"},
            "reasonCode": [{"text": "Diabetes monitoring"}],
        }
        result = from_fhir_order(fhir)

        assert result["priority"] == "routine"
        assert result["test_name"] == "Blood Glucose"
        assert result["loinc_code"] == "2345-7"
        assert result["patient_id"] == patient_id
        assert result["encounter_id"] == encounter_id
        assert result["clinical_indication"] == "Diabetes monitoring"

    def test_from_fhir_order_empty_json(self):
        """from_fhir_order returns empty dict for empty FHIR JSON."""
        from app.modules.lab_orders.fhir_mapper import from_fhir_order

        result = from_fhir_order({})

        assert isinstance(result, dict)


class TestLabOrderFormatDt:
    """Verify lab_orders _format_dt handles None and datetime correctly."""

    def test_format_dt_none_returns_none(self):
        """_format_dt returns None when passed None."""
        from app.modules.lab_orders.fhir_mapper import _format_dt

        assert _format_dt(None) is None

    def test_format_dt_returns_iso_string(self):
        """_format_dt returns ISO-8601 string for a datetime value."""
        from app.modules.lab_orders.fhir_mapper import _format_dt

        ts = datetime(2025, 6, 15, 14, 30, tzinfo=timezone.utc)
        result = _format_dt(ts)

        assert "2025-06-15" in result
        assert isinstance(result, str)


# ===========================================================================
# prescriptions/fhir_mapper.py — from_fhir_prescription
# ===========================================================================
class TestFromFhirPrescription:
    """Verify from_fhir_prescription parses all supported FHIR MedicationRequest fields."""

    def test_from_fhir_prescription_extracts_status(self):
        """from_fhir_prescription reverse-maps FHIR status to internal value."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        result = from_fhir_prescription({"status": "active"})

        assert result["status"] == "active"

    def test_from_fhir_prescription_maps_stopped_to_discontinued(self):
        """from_fhir_prescription maps FHIR 'stopped' back to 'discontinued'."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        result = from_fhir_prescription({"status": "stopped"})

        assert result["status"] == "discontinued"

    def test_from_fhir_prescription_extracts_drug_name(self):
        """from_fhir_prescription extracts drug_name from medicationCodeableConcept.text."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        fhir = {
            "medicationCodeableConcept": {
                "text": "Metformin",
                "coding": [{"code": "A10BA02"}],
            }
        }
        result = from_fhir_prescription(fhir)

        assert result["drug_name"] == "Metformin"
        assert result["atc_code"] == "A10BA02"

    def test_from_fhir_prescription_extracts_patient_id(self):
        """from_fhir_prescription strips 'Patient/' prefix from subject reference."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        patient_id = str(uuid.uuid4())
        fhir = {"subject": {"reference": f"Patient/{patient_id}"}}
        result = from_fhir_prescription(fhir)

        assert result["patient_id"] == patient_id

    def test_from_fhir_prescription_extracts_route(self):
        """from_fhir_prescription extracts route from dosageInstruction."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        fhir = {
            "dosageInstruction": [
                {
                    "route": {
                        "coding": [{"display": "oral"}]
                    }
                }
            ]
        }
        result = from_fhir_prescription(fhir)

        assert result["route"] == "oral"

    def test_from_fhir_prescription_extracts_frequency(self):
        """from_fhir_prescription extracts frequency from dosage timing."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        fhir = {
            "dosageInstruction": [
                {
                    "timing": {"code": {"text": "twice daily"}}
                }
            ]
        }
        result = from_fhir_prescription(fhir)

        assert result["frequency"] == "twice daily"

    def test_from_fhir_prescription_extracts_dose(self):
        """from_fhir_prescription extracts dosage from doseAndRate."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        fhir = {
            "dosageInstruction": [
                {
                    "doseAndRate": [
                        {"doseQuantity": {"value": 500}}
                    ]
                }
            ]
        }
        result = from_fhir_prescription(fhir)

        assert result["dosage"] == "500"

    def test_from_fhir_prescription_extracts_refills(self):
        """from_fhir_prescription extracts refills_allowed from dispenseRequest."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        fhir = {"dispenseRequest": {"numberOfRepeatsAllowed": 3}}
        result = from_fhir_prescription(fhir)

        assert result["refills_allowed"] == 3

    def test_from_fhir_prescription_extracts_duration(self):
        """from_fhir_prescription extracts duration_days from expectedSupplyDuration."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        fhir = {
            "dispenseRequest": {
                "numberOfRepeatsAllowed": 0,
                "expectedSupplyDuration": {"value": 30},
            }
        }
        result = from_fhir_prescription(fhir)

        assert result["duration_days"] == 30

    def test_from_fhir_prescription_full_payload(self):
        """from_fhir_prescription parses a complete representative MedicationRequest."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        patient_id = str(uuid.uuid4())
        fhir = {
            "status": "active",
            "medicationCodeableConcept": {
                "text": "Amlodipine",
                "coding": [{"code": "C08CA01"}],
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "dosageInstruction": [
                {
                    "route": {"coding": [{"display": "oral"}]},
                    "timing": {"code": {"text": "once daily"}},
                    "doseAndRate": [{"doseQuantity": {"value": 5}}],
                }
            ],
            "dispenseRequest": {
                "numberOfRepeatsAllowed": 5,
                "expectedSupplyDuration": {"value": 90},
            },
        }
        result = from_fhir_prescription(fhir)

        assert result["status"] == "active"
        assert result["drug_name"] == "Amlodipine"
        assert result["atc_code"] == "C08CA01"
        assert result["patient_id"] == patient_id
        assert result["route"] == "oral"
        assert result["frequency"] == "once daily"
        assert result["dosage"] == "5"
        assert result["refills_allowed"] == 5
        assert result["duration_days"] == 90

    def test_from_fhir_prescription_empty_json(self):
        """from_fhir_prescription returns empty dict for empty FHIR JSON."""
        from app.modules.prescriptions.fhir_mapper import from_fhir_prescription

        result = from_fhir_prescription({})

        assert isinstance(result, dict)
