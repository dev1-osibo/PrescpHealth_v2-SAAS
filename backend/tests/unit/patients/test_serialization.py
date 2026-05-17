"""
Unit tests for patient serialization helpers.

Tests the snapshot and diff computation logic that underpins
the patient versioning system. These are pure functions with
no database dependency — fast and isolated.

Validates:
- serialize_value handles all Python types correctly
- patient_to_snapshot captures all expected fields
- compute_diff correctly identifies changed fields
- compute_diff returns empty dict when nothing changed
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.modules.patients.models import PatientGender, PatientStatus
from app.modules.patients.serialization import (
    SNAPSHOT_FIELDS,
    compute_diff,
    patient_to_snapshot,
    serialize_value,
)


class TestSerializeValue:
    """Tests for the serialize_value helper function."""

    def test_serialize_none_returns_none(self):
        """None values pass through unchanged for JSON compatibility."""
        assert serialize_value(None) is None

    def test_serialize_string_returns_string(self):
        """Plain strings pass through unchanged."""
        assert serialize_value("hello") == "hello"

    def test_serialize_int_returns_int(self):
        """Integers pass through unchanged."""
        assert serialize_value(42) == 42

    def test_serialize_list_returns_list(self):
        """Lists pass through unchanged (already JSON-compatible)."""
        data = ["Penicillin", "Latex"]
        assert serialize_value(data) == ["Penicillin", "Latex"]

    def test_serialize_dict_returns_dict(self):
        """Dicts pass through unchanged (already JSON-compatible)."""
        data = {"street": "123 Main St", "city": "Lagos"}
        assert serialize_value(data) == data

    def test_serialize_date_returns_iso_string(self):
        """Date objects are serialized to ISO-8601 strings."""
        d = date(1990, 5, 15)
        assert serialize_value(d) == "1990-05-15"

    def test_serialize_datetime_returns_iso_string(self):
        """Datetime objects are serialized to ISO-8601 strings."""
        dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = serialize_value(dt)
        assert "2025-01-15" in result
        assert "10:30:00" in result

    def test_serialize_uuid_returns_string(self):
        """UUID objects are serialized to their string representation."""
        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert serialize_value(uid) == "12345678-1234-5678-1234-567812345678"

    def test_serialize_enum_returns_value(self):
        """Enum types are serialized to their .value string."""
        assert serialize_value(PatientGender.MALE) == "Male"
        assert serialize_value(PatientStatus.ACTIVE) == "Active"


class TestPatientToSnapshot:
    """Tests for the patient_to_snapshot function."""

    def _make_mock_patient(self):
        """Create a mock Patient with all snapshot fields populated."""
        patient = MagicMock()
        patient.medical_record_number = "MRN-001"
        patient.first_name = "Test"
        patient.last_name = "Patient"
        patient.date_of_birth = date(1990, 1, 1)
        patient.gender = PatientGender.MALE
        patient.phone_number = "+1234567890"
        patient.email = "test@example.com"
        patient.address = {"city": "Lagos"}
        patient.emergency_contact = {"name": "Contact"}
        patient.blood_type = "O+"
        patient.allergies = ["Penicillin"]
        patient.chronic_conditions = []
        patient.current_medications = []
        patient.insurance_info = None
        patient.notes = "Test notes"
        patient.status = PatientStatus.ACTIVE
        patient.created_by = uuid.uuid4()
        patient.deleted_at = None
        return patient

    def test_snapshot_includes_all_fields(self):
        """Snapshot captures every field defined in SNAPSHOT_FIELDS."""
        patient = self._make_mock_patient()
        snapshot = patient_to_snapshot(patient)

        for field in SNAPSHOT_FIELDS:
            assert field in snapshot, f"Missing field: {field}"

    def test_snapshot_serializes_enum_values(self):
        """Enum fields are serialized to their string values."""
        patient = self._make_mock_patient()
        snapshot = patient_to_snapshot(patient)

        assert snapshot["gender"] == "Male"
        assert snapshot["status"] == "Active"

    def test_snapshot_serializes_date(self):
        """Date fields are serialized to ISO strings."""
        patient = self._make_mock_patient()
        snapshot = patient_to_snapshot(patient)

        assert snapshot["date_of_birth"] == "1990-01-01"

    def test_snapshot_handles_none_fields(self):
        """None fields are preserved as None in the snapshot."""
        patient = self._make_mock_patient()
        patient.insurance_info = None
        patient.deleted_at = None
        snapshot = patient_to_snapshot(patient)

        assert snapshot["insurance_info"] is None
        assert snapshot["deleted_at"] is None


class TestComputeDiff:
    """Tests for the compute_diff function."""

    def test_no_changes_returns_empty_dict(self):
        """When snapshots are identical, diff is empty."""
        snapshot = {"first_name": "Test", "last_name": "Patient", "status": "Active"}
        result = compute_diff(snapshot, snapshot)
        assert result == {}

    def test_single_field_change_detected(self):
        """A single field change is correctly captured in the diff."""
        old = {"first_name": "Test", "last_name": "Old", "status": "Active"}
        new = {"first_name": "Test", "last_name": "New", "status": "Active"}
        result = compute_diff(old, new)

        assert "last_name" in result
        assert result["last_name"] == {"old": "Old", "new": "New"}
        assert "first_name" not in result

    def test_multiple_field_changes_detected(self):
        """Multiple field changes are all captured."""
        old = {"first_name": "Old", "status": "Active", "notes": "old note"}
        new = {"first_name": "New", "status": "Inactive", "notes": "new note"}
        result = compute_diff(old, new)

        assert len(result) == 3
        assert "first_name" in result
        assert "status" in result
        assert "notes" in result

    def test_none_to_value_change_detected(self):
        """Changing from None to a value is captured."""
        old = {"phone_number": None, "email": "test@test.com"}
        new = {"phone_number": "+1234567890", "email": "test@test.com"}
        result = compute_diff(old, new)

        assert "phone_number" in result
        assert result["phone_number"] == {"old": None, "new": "+1234567890"}

    def test_value_to_none_change_detected(self):
        """Changing from a value to None is captured."""
        old = {"notes": "some notes", "email": "test@test.com"}
        new = {"notes": None, "email": "test@test.com"}
        result = compute_diff(old, new)

        assert "notes" in result
        assert result["notes"] == {"old": "some notes", "new": None}
