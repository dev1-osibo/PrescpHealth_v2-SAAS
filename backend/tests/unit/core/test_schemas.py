"""
Unit tests for Pydantic schema instantiation and validation.

Tests that core request schemas can be instantiated with valid data
and that their field validation rules work correctly. This exercises
the schema code paths (field validators, defaults, type coercion)
without requiring a database or API call.

Validates:
- MeasurementCreate accepts valid clinical measurement data
- PatientCreate accepts valid patient registration data
- EncounterCreate accepts valid encounter check-in data
- PrescriptionCreate accepts valid prescription data
"""

import uuid
from datetime import date, datetime, timezone

import pytest

from app.modules.measurements.schemas import MeasurementCreate
from app.modules.measurements.models import MeasurementSource, MeasurementType
from app.modules.patients.schemas import PatientCreate
from app.modules.patients.enums import PatientGender
from app.modules.encounters.schemas import EncounterCreate
from app.modules.encounters.enums import EncounterClass
from app.modules.prescriptions.schemas import PrescriptionCreate


# ---------------------------------------------------------------------------
# Test: MeasurementCreate schema with valid data
# ---------------------------------------------------------------------------
class TestMeasurementCreateSchema:
    """Verify MeasurementCreate instantiates correctly with valid input."""

    def test_valid_systolic_bp_measurement(self):
        """MeasurementCreate accepts a valid systolic BP reading."""
        schema = MeasurementCreate(
            measurement_type=MeasurementType.SYSTOLIC_BP,
            value=120.0,
            unit="mmHg",
            recorded_at=datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
            source=MeasurementSource.MANUAL,
        )

        assert schema.measurement_type == MeasurementType.SYSTOLIC_BP
        assert schema.value == 120.0
        assert schema.unit == "mmHg"
        assert schema.source == MeasurementSource.MANUAL
        assert schema.notes is None  # Optional field defaults to None

    def test_rejects_negative_value(self):
        """MeasurementCreate rejects value below 0 (ge=0 constraint)."""
        with pytest.raises(Exception):
            MeasurementCreate(
                measurement_type=MeasurementType.HEART_RATE,
                value=-5.0,
                unit="bpm",
                recorded_at=datetime.now(timezone.utc),
                source=MeasurementSource.DEVICE,
            )


# ---------------------------------------------------------------------------
# Test: PatientCreate schema with valid data
# ---------------------------------------------------------------------------
class TestPatientCreateSchema:
    """Verify PatientCreate instantiates correctly with valid input."""

    def test_valid_patient_creation(self):
        """PatientCreate accepts valid synthetic patient data."""
        schema = PatientCreate(
            medical_record_number="MRN-TEST-001",
            first_name="Test Patient",
            last_name="Alpha",
            date_of_birth=date(1985, 3, 15),
            gender=PatientGender.MALE,
        )

        assert schema.medical_record_number == "MRN-TEST-001"
        assert schema.first_name == "Test Patient"
        assert schema.last_name == "Alpha"
        assert schema.date_of_birth == date(1985, 3, 15)
        assert schema.gender == PatientGender.MALE
        # Optional fields default to None
        assert schema.phone_number is None
        assert schema.allergies is None

    def test_rejects_empty_first_name(self):
        """PatientCreate rejects empty first_name (min_length=1)."""
        with pytest.raises(Exception):
            PatientCreate(
                medical_record_number="MRN-TEST-002",
                first_name="",
                last_name="Beta",
                date_of_birth=date(1990, 1, 1),
                gender=PatientGender.FEMALE,
            )


# ---------------------------------------------------------------------------
# Test: EncounterCreate schema with valid data
# ---------------------------------------------------------------------------
class TestEncounterCreateSchema:
    """Verify EncounterCreate instantiates correctly with valid input."""

    def test_valid_encounter_creation(self):
        """EncounterCreate accepts valid encounter check-in data."""
        patient_id = uuid.uuid4()
        schema = EncounterCreate(
            patient_id=patient_id,
            reason_for_visit="Routine follow-up for hypertension management",
            encounter_class=EncounterClass.AMBULATORY,
        )

        assert schema.patient_id == patient_id
        assert schema.reason_for_visit == "Routine follow-up for hypertension management"
        assert schema.encounter_class == EncounterClass.AMBULATORY

    def test_defaults_to_ambulatory(self):
        """EncounterCreate defaults encounter_class to AMBULATORY."""
        schema = EncounterCreate(
            patient_id=uuid.uuid4(),
            reason_for_visit="Annual checkup",
        )

        assert schema.encounter_class == EncounterClass.AMBULATORY


# ---------------------------------------------------------------------------
# Test: PrescriptionCreate schema with valid data
# ---------------------------------------------------------------------------
class TestPrescriptionCreateSchema:
    """Verify PrescriptionCreate instantiates correctly with valid input."""

    def test_valid_prescription_creation(self):
        """PrescriptionCreate accepts valid prescription data."""
        patient_id = uuid.uuid4()
        schema = PrescriptionCreate(
            patient_id=patient_id,
            drug_name="Metformin",
            atc_code="A10BA02",
            dosage="500mg",
            frequency="twice daily",
            route="oral",
            refills_allowed=3,
        )

        assert schema.patient_id == patient_id
        assert schema.drug_name == "Metformin"
        assert schema.atc_code == "A10BA02"
        assert schema.dosage == "500mg"
        assert schema.frequency == "twice daily"
        assert schema.route == "oral"
        assert schema.refills_allowed == 3
        assert schema.interaction_acknowledged is False
        assert schema.duration_days is None

    def test_rejects_excessive_refills(self):
        """PrescriptionCreate rejects refills_allowed > 12 (le=12)."""
        with pytest.raises(Exception):
            PrescriptionCreate(
                patient_id=uuid.uuid4(),
                drug_name="Lisinopril",
                atc_code="C09AA03",
                dosage="10mg",
                frequency="once daily",
                route="oral",
                refills_allowed=99,
            )
