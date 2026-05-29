"""
Unit tests for feature vector extraction logic.

Tests the _compute_age_days() helper and get_feature_vector() structure
to verify correct age computation, staleness detection, and output format.

Validates:
- _compute_age_days returns correct number of days between timestamps
- _compute_age_days returns 0 for future timestamps (clock skew protection)
- Feature vector entries have expected keys (value, unit, age_days, etc.)
- Measurements older than 90 days are marked is_stale=True
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import pytest

from app.modules.measurements.feature_vector import (
    DEFAULT_STALENESS_THRESHOLD_DAYS,
    _compute_age_days,
    get_feature_vector,
)


# ---------------------------------------------------------------------------
# Test: _compute_age_days correctness
# ---------------------------------------------------------------------------
class TestComputeAgeDays:
    """Verify _compute_age_days returns correct day counts."""

    def test_returns_correct_days_for_past_timestamp(self):
        """A measurement recorded 10 days ago should return age_days=10."""
        now = datetime(2025, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
        recorded = datetime(2025, 6, 10, 12, 0, 0, tzinfo=timezone.utc)

        result = _compute_age_days(recorded, now)

        assert result == 10

    def test_returns_zero_for_future_timestamp(self):
        """Future timestamps (clock skew) should return 0, not negative."""
        now = datetime(2025, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
        future = datetime(2025, 6, 25, 12, 0, 0, tzinfo=timezone.utc)

        result = _compute_age_days(future, now)

        assert result == 0

    def test_handles_naive_datetime_as_utc(self):
        """Naive datetimes (no tzinfo) are treated as UTC for safe subtraction."""
        now = datetime(2025, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
        # Naive datetime — should be normalized to UTC internally
        recorded_naive = datetime(2025, 6, 15, 12, 0, 0)

        result = _compute_age_days(recorded_naive, now)

        assert result == 5


# ---------------------------------------------------------------------------
# Test: Feature vector structure and staleness
# ---------------------------------------------------------------------------
class TestFeatureVectorStructure:
    """Verify feature vector output format and staleness detection."""

    @pytest.mark.asyncio
    async def test_feature_vector_has_expected_keys(self):
        """Each feature entry must have value, unit, age_days, is_validated, is_stale."""
        patient_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Mock a measurement object with required attributes
        mock_measurement = SimpleNamespace(
            measurement_type="systolic_bp",
            value=120.0,
            unit="mmHg",
            recorded_at=now - timedelta(days=5),
            is_validated=True,
        )

        with patch(
            "app.modules.measurements.feature_vector.get_latest_measurements",
            new_callable=AsyncMock,
            return_value=[mock_measurement],
        ):
            result = await get_feature_vector(AsyncMock(), patient_id)

        assert "systolic_bp" in result
        entry = result["systolic_bp"]
        assert "value" in entry
        assert "unit" in entry
        assert "age_days" in entry
        assert "is_validated" in entry
        assert "is_stale" in entry
        assert entry["value"] == 120.0
        assert entry["unit"] == "mmHg"
        assert entry["is_validated"] is True

    @pytest.mark.asyncio
    async def test_measurement_older_than_90_days_is_stale(self):
        """Measurements older than DEFAULT_STALENESS_THRESHOLD_DAYS are marked stale."""
        patient_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Measurement recorded 100 days ago — should be stale
        mock_measurement = SimpleNamespace(
            measurement_type="heart_rate",
            value=72.0,
            unit="bpm",
            recorded_at=now - timedelta(days=100),
            is_validated=True,
        )

        with patch(
            "app.modules.measurements.feature_vector.get_latest_measurements",
            new_callable=AsyncMock,
            return_value=[mock_measurement],
        ):
            result = await get_feature_vector(AsyncMock(), patient_id)

        assert result["heart_rate"]["is_stale"] is True
        assert result["heart_rate"]["age_days"] >= 100

    @pytest.mark.asyncio
    async def test_feature_vector_returns_empty_dict_for_no_measurements(self):
        """Patient with no measurements should get an empty feature vector."""
        patient_id = uuid.uuid4()

        with patch(
            "app.modules.measurements.feature_vector.get_latest_measurements",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_feature_vector(AsyncMock(), patient_id)

        assert result == {}
        assert isinstance(result, dict)
