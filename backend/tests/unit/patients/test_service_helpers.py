"""
Unit tests for patient service helper functions.

Tests the pure helper functions in the service module that don't
require database access. These are fast, isolated tests.

Validates:
- _describe_change generates correct human-readable descriptions
- PatientSearchFilters dataclass defaults are correct
"""

import pytest

from app.modules.patients.models import PatientChangeType
from app.modules.patients.search import PatientSearchFilters
from app.modules.patients.service import _describe_change


class TestDescribeChange:
    """Tests for the _describe_change helper function."""

    def test_create_description(self):
        """Create change type produces clear description."""
        result = _describe_change(PatientChangeType.CREATE, {})
        assert result == "Patient record created"

    def test_soft_delete_description(self):
        """Soft delete change type produces clear description."""
        result = _describe_change(PatientChangeType.SOFT_DELETE, {})
        assert result == "Patient record deleted"

    def test_restore_description(self):
        """Restore change type produces clear description."""
        result = _describe_change(PatientChangeType.RESTORE, {})
        assert result == "Patient record restored"

    def test_update_description_single_field(self):
        """Update with one field change shows field name."""
        changes = {"first_name": {"old": "Old", "new": "New"}}
        result = _describe_change(PatientChangeType.UPDATE, changes)
        assert "1 field(s)" in result
        assert "first_name" in result

    def test_update_description_multiple_fields(self):
        """Update with multiple field changes shows all field names."""
        changes = {
            "first_name": {"old": "Old", "new": "New"},
            "status": {"old": "Active", "new": "Inactive"},
        }
        result = _describe_change(PatientChangeType.UPDATE, changes)
        assert "2 field(s)" in result
        assert "first_name" in result
        assert "status" in result

    def test_update_description_does_not_expose_values(self):
        """Update description shows field names but NOT values (no PHI)."""
        changes = {"first_name": {"old": "RealName", "new": "NewName"}}
        result = _describe_change(PatientChangeType.UPDATE, changes)
        # Field name is shown
        assert "first_name" in result
        # But actual values are NOT shown
        assert "RealName" not in result
        assert "NewName" not in result


class TestPatientSearchFilters:
    """Tests for PatientSearchFilters dataclass defaults."""

    def test_default_filters_are_none(self):
        """All filter fields default to None (no restriction)."""
        filters = PatientSearchFilters()
        assert filters.name_query is None
        assert filters.mrn_query is None
        assert filters.status is None
        assert filters.created_after is None
        assert filters.created_before is None

    def test_include_deleted_defaults_to_false(self):
        """Soft-deleted patients are excluded by default."""
        filters = PatientSearchFilters()
        assert filters.include_deleted is False

    def test_filters_accept_values(self):
        """Filters can be constructed with specific values."""
        from app.modules.patients.models import PatientStatus

        filters = PatientSearchFilters(
            name_query="Test",
            status=PatientStatus.ACTIVE,
            include_deleted=True,
        )
        assert filters.name_query == "Test"
        assert filters.status == PatientStatus.ACTIVE
        assert filters.include_deleted is True
