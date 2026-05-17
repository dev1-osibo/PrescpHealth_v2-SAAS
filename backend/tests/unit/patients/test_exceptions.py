"""
Unit tests for patient module exceptions.

Validates that each exception:
- Has the correct HTTP status code
- Has the correct error code
- Includes appropriate details without PHI
- Inherits from the correct base exception
"""

import uuid

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.patients.exceptions import (
    DuplicateMRNError,
    PatientAlreadyDeletedError,
    PatientNotDeletedError,
    PatientNotFoundError,
    PatientVersionNotFoundError,
)


class TestPatientNotFoundError:
    """Tests for PatientNotFoundError."""

    def test_status_code_is_404(self):
        """Patient not found maps to HTTP 404."""
        patient_id = uuid.uuid4()
        exc = PatientNotFoundError(patient_id)
        assert exc.status_code == 404

    def test_inherits_from_not_found_error(self):
        """Inherits from the core NotFoundError."""
        patient_id = uuid.uuid4()
        exc = PatientNotFoundError(patient_id)
        assert isinstance(exc, NotFoundError)

    def test_details_include_patient_id(self):
        """Details include the patient_id for debugging."""
        patient_id = uuid.uuid4()
        exc = PatientNotFoundError(patient_id)
        assert exc.details == {"patient_id": str(patient_id)}

    def test_message_is_generic(self):
        """Message is generic — no PHI leaked."""
        patient_id = uuid.uuid4()
        exc = PatientNotFoundError(patient_id)
        assert exc.message == "Patient not found"


class TestPatientAlreadyDeletedError:
    """Tests for PatientAlreadyDeletedError."""

    def test_status_code_is_409(self):
        """Double-deletion maps to HTTP 409 Conflict."""
        exc = PatientAlreadyDeletedError(uuid.uuid4())
        assert exc.status_code == 409

    def test_inherits_from_conflict_error(self):
        """Inherits from the core ConflictError."""
        exc = PatientAlreadyDeletedError(uuid.uuid4())
        assert isinstance(exc, ConflictError)


class TestPatientNotDeletedError:
    """Tests for PatientNotDeletedError."""

    def test_status_code_is_409(self):
        """Restoring non-deleted patient maps to HTTP 409 Conflict."""
        exc = PatientNotDeletedError(uuid.uuid4())
        assert exc.status_code == 409


class TestDuplicateMRNError:
    """Tests for DuplicateMRNError."""

    def test_status_code_is_409(self):
        """Duplicate MRN maps to HTTP 409 Conflict."""
        exc = DuplicateMRNError("MRN-001")
        assert exc.status_code == 409

    def test_details_do_not_expose_mrn_value(self):
        """Details mention the field name but not the actual MRN value."""
        exc = DuplicateMRNError("MRN-001")
        # Only field name, not the value (defense against info leakage)
        assert exc.details == {"field": "medical_record_number"}


class TestPatientVersionNotFoundError:
    """Tests for PatientVersionNotFoundError."""

    def test_status_code_is_404(self):
        """Missing version maps to HTTP 404."""
        exc = PatientVersionNotFoundError(uuid.uuid4(), 99)
        assert exc.status_code == 404

    def test_details_include_version_number(self):
        """Details include both patient_id and version_number."""
        patient_id = uuid.uuid4()
        exc = PatientVersionNotFoundError(patient_id, 5)
        assert exc.details["patient_id"] == str(patient_id)
        assert exc.details["version_number"] == 5

    def test_message_includes_version_number(self):
        """Message mentions the version number for user clarity."""
        exc = PatientVersionNotFoundError(uuid.uuid4(), 42)
        assert "42" in exc.message
