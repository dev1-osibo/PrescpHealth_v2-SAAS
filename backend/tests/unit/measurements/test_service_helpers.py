"""
Unit tests for measurement module components (service, model, schemas, router helpers, exceptions).

Tests the structural correctness of the measurement module without requiring
a database connection. Validates:
- MeasurementService has all expected public methods and dependencies
- Measurement model has correct table name, columns, and constraints
- MeasurementType and MeasurementSource enums have all expected members
- Pydantic schemas enforce validation rules (ranges, lengths)
- Router serialization helpers handle all field types correctly
- Exception classes have correct HTTP status codes and details

These are fast, isolated unit tests with no external dependencies.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.modules.measurements.exceptions import (
    MeasurementNotFoundError,
    MeasurementValidationForbiddenError,
)
from app.modules.measurements.models import (
    Measurement,
    MeasurementSource,
    MeasurementType,
)
from app.modules.measurements.router_helpers import serialize_measurement
from app.modules.measurements.schemas import (
    BulkImportRequest,
    MeasurementCreate,
    MeasurementResponse,
)
from app.modules.measurements.service import MeasurementService


# ---------------------------------------------------------------------------
# 1. MeasurementService Structure Tests
# ---------------------------------------------------------------------------
class TestMeasurementServiceStructure:
    """Verify MeasurementService has all expected public methods and dependencies."""

    def test_service_has_save_measurement_method(self):
        """Service exposes save_measurement for recording clinical data."""
        service = MeasurementService()
        assert hasattr(service, "save_measurement")
        assert callable(service.save_measurement)

    def test_service_has_validate_measurement_method(self):
        """Service exposes validate_measurement for clinician approval."""
        service = MeasurementService()
        assert hasattr(service, "validate_measurement")
        assert callable(service.validate_measurement)

    def test_service_has_bulk_import_method(self):
        """Service exposes bulk_import for CSV-style batch imports."""
        service = MeasurementService()
        assert hasattr(service, "bulk_import")
        assert callable(service.bulk_import)

    def test_service_has_get_measurement_history_method(self):
        """Service exposes get_measurement_history for time-series queries."""
        service = MeasurementService()
        assert hasattr(service, "get_measurement_history")
        assert callable(service.get_measurement_history)

    def test_service_has_get_latest_measurements_method(self):
        """Service exposes get_latest_measurements for risk engine feature extraction."""
        service = MeasurementService()
        assert hasattr(service, "get_latest_measurements")
        assert callable(service.get_latest_measurements)

    def test_service_has_compute_baseline_method(self):
        """Service exposes compute_baseline for deviation detection."""
        service = MeasurementService()
        assert hasattr(service, "compute_baseline")
        assert callable(service.compute_baseline)

    def test_service_initializes_with_audit_service(self):
        """Service creates an AuditService dependency on initialization."""
        service = MeasurementService()
        # _audit is the internal AuditService instance
        assert hasattr(service, "_audit")
        assert service._audit is not None


# ---------------------------------------------------------------------------
# 2. Measurement Model Tests
# ---------------------------------------------------------------------------
class TestMeasurementModel:
    """Verify Measurement model has correct table name, columns, and constraints."""

    def test_table_name_is_measurements(self):
        """Model maps to the 'measurements' database table."""
        assert Measurement.__tablename__ == "measurements"

    def test_model_has_id_column(self):
        """Model has a UUID primary key column."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "id" in columns

    def test_model_has_patient_id_column(self):
        """Model has patient_id FK for patient association."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "patient_id" in columns

    def test_model_has_measurement_type_column(self):
        """Model has measurement_type for identifying the vital sign type."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "measurement_type" in columns

    def test_model_has_value_column(self):
        """Model has value column for the numeric reading (PHI)."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "value" in columns

    def test_model_has_unit_column(self):
        """Model has unit column for self-documenting records."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "unit" in columns

    def test_model_has_recorded_at_column(self):
        """Model has recorded_at for when the measurement was taken."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "recorded_at" in columns

    def test_model_has_recorded_by_column(self):
        """Model has recorded_by for provenance tracking."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "recorded_by" in columns

    def test_model_has_source_column(self):
        """Model has source column for data provenance."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "source" in columns

    def test_model_has_is_validated_column(self):
        """Model has is_validated for clinician approval status."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "is_validated" in columns

    def test_model_has_is_flagged_column(self):
        """Model has is_flagged for deviation detection."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "is_flagged" in columns

    def test_model_has_notes_column(self):
        """Model has notes column for clinician annotations (PHI)."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "notes" in columns

    def test_model_has_tenant_id_column(self):
        """Model has tenant_id from TenantMixin for RLS isolation."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "tenant_id" in columns

    def test_model_has_created_at_column(self):
        """Model has created_at from TimestampMixin."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "created_at" in columns

    def test_model_has_updated_at_column(self):
        """Model has updated_at from TimestampMixin."""
        columns = {c.name for c in Measurement.__table__.columns}
        assert "updated_at" in columns

    def test_idempotency_constraint_exists(self):
        """Unique constraint on (patient_id, measurement_type, recorded_at, value) exists."""
        constraints = Measurement.__table__.constraints
        unique_constraints = [
            c for c in constraints
            if hasattr(c, "name") and c.name == "uq_measurement_idempotency"
        ]
        assert len(unique_constraints) == 1

    def test_idempotency_constraint_columns(self):
        """Idempotency constraint covers the correct four columns."""
        constraints = Measurement.__table__.constraints
        uq = next(
            c for c in constraints
            if hasattr(c, "name") and c.name == "uq_measurement_idempotency"
        )
        column_names = {col.name for col in uq.columns}
        assert column_names == {"patient_id", "measurement_type", "recorded_at", "value"}


class TestMeasurementTypeEnum:
    """Verify MeasurementType enum has all 22 expected clinical measurement types."""

    EXPECTED_TYPES = [
        "SYSTOLIC_BP", "DIASTOLIC_BP", "HEART_RATE",
        "BMI", "BLOOD_GLUCOSE_FASTING", "BLOOD_GLUCOSE_RANDOM", "HBA1C",
        "TOTAL_CHOLESTEROL", "HDL_CHOLESTEROL", "LDL_CHOLESTEROL", "TRIGLYCERIDES",
        "CREATININE", "EGFR", "URINE_ALBUMIN",
        "FEV1", "FVC", "SPO2", "RESPIRATORY_RATE",
        "WEIGHT", "HEIGHT", "WAIST_CIRCUMFERENCE",
        "SMOKING_STATUS",
    ]

    def test_enum_has_22_members(self):
        """MeasurementType enum has exactly 22 clinical measurement types."""
        assert len(MeasurementType) == 22

    @pytest.mark.parametrize("type_name", EXPECTED_TYPES)
    def test_enum_has_expected_type(self, type_name):
        """Each expected measurement type exists in the enum."""
        assert hasattr(MeasurementType, type_name)


class TestMeasurementSourceEnum:
    """Verify MeasurementSource enum has all 4 expected data sources."""

    def test_enum_has_4_members(self):
        """MeasurementSource enum has exactly 4 provenance sources."""
        assert len(MeasurementSource) == 4

    def test_has_manual_source(self):
        """Manual source for clinician-entered measurements."""
        assert MeasurementSource.MANUAL.value == "manual"

    def test_has_device_source(self):
        """Device source for connected medical device imports."""
        assert MeasurementSource.DEVICE.value == "device"

    def test_has_import_source(self):
        """Import source for CSV bulk imports."""
        assert MeasurementSource.IMPORT.value == "import"

    def test_has_patient_portal_source(self):
        """Patient portal source for self-reported measurements."""
        assert MeasurementSource.PATIENT_PORTAL.value == "patient_portal"


# ---------------------------------------------------------------------------
# 3. Schemas Tests
# ---------------------------------------------------------------------------
class TestMeasurementCreateSchema:
    """Verify MeasurementCreate schema enforces validation rules."""

    def test_valid_measurement_create(self):
        """Valid input passes schema validation."""
        data = MeasurementCreate(
            measurement_type=MeasurementType.SYSTOLIC_BP,
            value=120.0,
            unit="mmHg",
            recorded_at=datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
            source=MeasurementSource.MANUAL,
        )
        assert data.value == 120.0
        assert data.measurement_type == MeasurementType.SYSTOLIC_BP

    def test_rejects_negative_value(self):
        """Negative measurement values are rejected (ge=0 constraint)."""
        with pytest.raises(PydanticValidationError):
            MeasurementCreate(
                measurement_type=MeasurementType.HEART_RATE,
                value=-1.0,
                unit="bpm",
                recorded_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
                source=MeasurementSource.MANUAL,
            )

    def test_rejects_value_above_10000(self):
        """Values above 10000 are rejected (le=10000 constraint)."""
        with pytest.raises(PydanticValidationError):
            MeasurementCreate(
                measurement_type=MeasurementType.WEIGHT,
                value=10001.0,
                unit="kg",
                recorded_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
                source=MeasurementSource.MANUAL,
            )

    def test_requires_measurement_type(self):
        """measurement_type is a required field."""
        with pytest.raises(PydanticValidationError):
            MeasurementCreate(
                value=120.0,
                unit="mmHg",
                recorded_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
                source=MeasurementSource.MANUAL,
            )

    def test_requires_value(self):
        """value is a required field."""
        with pytest.raises(PydanticValidationError):
            MeasurementCreate(
                measurement_type=MeasurementType.SYSTOLIC_BP,
                unit="mmHg",
                recorded_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
                source=MeasurementSource.MANUAL,
            )

    def test_requires_unit(self):
        """unit is a required field."""
        with pytest.raises(PydanticValidationError):
            MeasurementCreate(
                measurement_type=MeasurementType.SYSTOLIC_BP,
                value=120.0,
                recorded_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
                source=MeasurementSource.MANUAL,
            )

    def test_requires_recorded_at(self):
        """recorded_at is a required field."""
        with pytest.raises(PydanticValidationError):
            MeasurementCreate(
                measurement_type=MeasurementType.SYSTOLIC_BP,
                value=120.0,
                unit="mmHg",
                source=MeasurementSource.MANUAL,
            )

    def test_requires_source(self):
        """source is a required field."""
        with pytest.raises(PydanticValidationError):
            MeasurementCreate(
                measurement_type=MeasurementType.SYSTOLIC_BP,
                value=120.0,
                unit="mmHg",
                recorded_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
            )


class TestBulkImportRequestSchema:
    """Verify BulkImportRequest enforces list size constraints."""

    def _make_item(self):
        """Create a valid BulkImportItem dict for testing."""
        return {
            "measurement_type": "systolic_bp",
            "value": 120.0,
            "unit": "mmHg",
            "recorded_at": "2025-01-15T10:30:00Z",
        }

    def test_valid_single_item(self):
        """A request with 1 item is valid (min_length=1)."""
        request = BulkImportRequest(measurements=[self._make_item()])
        assert len(request.measurements) == 1

    def test_requires_at_least_one_item(self):
        """Empty measurements list is rejected (min_length=1)."""
        with pytest.raises(PydanticValidationError):
            BulkImportRequest(measurements=[])

    def test_enforces_max_500_items(self):
        """More than 500 items are rejected (max_length=500)."""
        items = [self._make_item() for _ in range(501)]
        with pytest.raises(PydanticValidationError):
            BulkImportRequest(measurements=items)

    def test_accepts_500_items(self):
        """Exactly 500 items is valid (boundary value)."""
        items = [self._make_item() for _ in range(500)]
        request = BulkImportRequest(measurements=items)
        assert len(request.measurements) == 500


class TestMeasurementResponseSchema:
    """Verify MeasurementResponse schema configuration."""

    def test_has_from_attributes_config(self):
        """MeasurementResponse has from_attributes=True for ORM model conversion."""
        assert MeasurementResponse.model_config.get("from_attributes") is True


# ---------------------------------------------------------------------------
# 4. Router Helpers Tests (serialize_measurement)
# ---------------------------------------------------------------------------
class TestSerializeMeasurement:
    """Verify serialize_measurement handles all field types correctly."""

    def _make_mock_measurement(self):
        """Create a mock Measurement with all fields populated."""
        measurement = MagicMock(spec=Measurement)
        measurement.id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        measurement.tenant_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        measurement.patient_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        measurement.measurement_type = "systolic_bp"
        measurement.value = 120.0
        measurement.unit = "mmHg"
        measurement.recorded_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        measurement.recorded_by = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
        measurement.source = "manual"
        measurement.is_validated = True
        measurement.validated_by = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
        measurement.validated_at = datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
        measurement.is_flagged = False
        measurement.flag_reason = None
        measurement.notes = "Normal reading"
        measurement.created_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        measurement.updated_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        return measurement

    def test_serializes_uuid_fields_as_strings(self):
        """UUID fields (id, tenant_id, patient_id, recorded_by) are serialized to strings."""
        measurement = self._make_mock_measurement()
        result = serialize_measurement(measurement)

        assert result["id"] == "12345678-1234-5678-1234-567812345678"
        assert result["tenant_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        assert result["patient_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        assert result["recorded_by"] == "cccccccc-cccc-cccc-cccc-cccccccccccc"

    def test_serializes_datetime_fields_as_iso_strings(self):
        """Datetime fields are serialized to ISO-8601 format."""
        measurement = self._make_mock_measurement()
        result = serialize_measurement(measurement)

        assert "2025-01-15" in result["recorded_at"]
        assert "10:30:00" in result["recorded_at"]
        assert "2025-01-15" in result["validated_at"]

    def test_serializes_numeric_value(self):
        """Numeric value passes through unchanged."""
        measurement = self._make_mock_measurement()
        result = serialize_measurement(measurement)

        assert result["value"] == 120.0

    def test_serializes_boolean_fields(self):
        """Boolean fields (is_validated, is_flagged) pass through unchanged."""
        measurement = self._make_mock_measurement()
        result = serialize_measurement(measurement)

        assert result["is_validated"] is True
        assert result["is_flagged"] is False

    def test_serializes_string_fields(self):
        """String fields (measurement_type, unit, source, notes) pass through."""
        measurement = self._make_mock_measurement()
        result = serialize_measurement(measurement)

        assert result["measurement_type"] == "systolic_bp"
        assert result["unit"] == "mmHg"
        assert result["source"] == "manual"
        assert result["notes"] == "Normal reading"

    def test_handles_none_validated_by(self):
        """None validated_by is serialized as None (not validated yet)."""
        measurement = self._make_mock_measurement()
        measurement.validated_by = None
        result = serialize_measurement(measurement)

        assert result["validated_by"] is None

    def test_handles_none_validated_at(self):
        """None validated_at is serialized as None."""
        measurement = self._make_mock_measurement()
        measurement.validated_at = None
        result = serialize_measurement(measurement)

        assert result["validated_at"] is None

    def test_handles_none_flag_reason(self):
        """None flag_reason is serialized as None (not flagged)."""
        measurement = self._make_mock_measurement()
        measurement.flag_reason = None
        result = serialize_measurement(measurement)

        assert result["flag_reason"] is None

    def test_handles_none_notes(self):
        """None notes is serialized as None (no clinician annotation)."""
        measurement = self._make_mock_measurement()
        measurement.notes = None
        result = serialize_measurement(measurement)

        assert result["notes"] is None


# ---------------------------------------------------------------------------
# 5. Exceptions Tests
# ---------------------------------------------------------------------------
class TestMeasurementNotFoundError:
    """Verify MeasurementNotFoundError has correct status code and details."""

    def test_status_code_is_404(self):
        """Measurement not found maps to HTTP 404."""
        measurement_id = uuid.uuid4()
        exc = MeasurementNotFoundError(measurement_id)
        assert exc.status_code == 404

    def test_details_include_measurement_id(self):
        """Details include the measurement_id for debugging (UUID is not PHI alone)."""
        measurement_id = uuid.uuid4()
        exc = MeasurementNotFoundError(measurement_id)
        assert exc.details == {"measurement_id": str(measurement_id)}

    def test_message_is_generic(self):
        """Message is generic — no PHI leaked in error text."""
        measurement_id = uuid.uuid4()
        exc = MeasurementNotFoundError(measurement_id)
        assert exc.message == "Measurement not found"

    def test_inherits_from_not_found_error(self):
        """Inherits from the core NotFoundError base class."""
        from app.core.exceptions import NotFoundError
        measurement_id = uuid.uuid4()
        exc = MeasurementNotFoundError(measurement_id)
        assert isinstance(exc, NotFoundError)


class TestMeasurementValidationForbiddenError:
    """Verify MeasurementValidationForbiddenError has correct status code and details."""

    def test_status_code_is_403(self):
        """Forbidden validation attempt maps to HTTP 403."""
        exc = MeasurementValidationForbiddenError()
        assert exc.status_code == 403

    def test_message_describes_restriction(self):
        """Message explains that only clinicians can validate."""
        exc = MeasurementValidationForbiddenError()
        assert "clinician" in exc.message.lower()

    def test_details_include_reason(self):
        """Details include the reason for the denial."""
        exc = MeasurementValidationForbiddenError()
        assert exc.details == {"reason": "insufficient_role"}

    def test_inherits_from_forbidden_error(self):
        """Inherits from the core ForbiddenError base class."""
        from app.core.exceptions import ForbiddenError
        exc = MeasurementValidationForbiddenError()
        assert isinstance(exc, ForbiddenError)
