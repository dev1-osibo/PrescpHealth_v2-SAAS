"""
Unit tests for data sufficiency check logic.

Tests the _evaluate_disease() helper and check_data_sufficiency() flow
to verify that disease model requirements are correctly evaluated against
available measurement types.

Validates:
- Stroke model requires systolic_bp, diastolic_bp, heart_rate, smoking_status
- Type 2 diabetes accepts OR logic (blood_glucose_fasting OR hba1c)
- Overall quality is "full_data" when all diseases are sufficient
- Overall quality is "insufficient" when no diseases are sufficient
- Empty available_types returns all diseases as insufficient
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.measurements.data_sufficiency import (
    DISEASE_REQUIREMENTS,
    DataSufficiencyResult,
    _evaluate_disease,
    check_data_sufficiency,
)


# ---------------------------------------------------------------------------
# Test: Stroke requires all four mandatory measurement types
# ---------------------------------------------------------------------------
class TestStrokeRequirements:
    """Verify stroke model requires systolic_bp, diastolic_bp, heart_rate, smoking_status."""

    def test_stroke_sufficient_with_all_required(self):
        """Stroke model is sufficient when all 4 required types are present."""
        available = {"systolic_bp", "diastolic_bp", "heart_rate", "smoking_status"}
        type_ages = {t: 5 for t in available}

        result = _evaluate_disease("stroke", DISEASE_REQUIREMENTS["stroke"], available, type_ages)

        assert result.is_sufficient is True
        assert result.data_quality == "full_data"
        assert result.missing_features == []

    def test_stroke_insufficient_missing_heart_rate(self):
        """Stroke model is insufficient when heart_rate is missing."""
        available = {"systolic_bp", "diastolic_bp", "smoking_status"}
        type_ages = {t: 5 for t in available}

        result = _evaluate_disease("stroke", DISEASE_REQUIREMENTS["stroke"], available, type_ages)

        assert result.is_sufficient is False
        assert "heart_rate" in result.missing_features


# ---------------------------------------------------------------------------
# Test: Type 2 diabetes accepts OR logic for glucose/hba1c
# ---------------------------------------------------------------------------
class TestType2DiabetesOrLogic:
    """Verify type_2_diabetes accepts blood_glucose_fasting OR hba1c."""

    def test_diabetes_sufficient_with_glucose_fasting(self):
        """Diabetes model accepts blood_glucose_fasting as alternative to hba1c."""
        available = {"blood_glucose_fasting", "bmi", "waist_circumference"}
        type_ages = {t: 10 for t in available}

        result = _evaluate_disease(
            "type_2_diabetes", DISEASE_REQUIREMENTS["type_2_diabetes"], available, type_ages
        )

        assert result.is_sufficient is True
        assert result.data_quality == "full_data"

    def test_diabetes_sufficient_with_hba1c(self):
        """Diabetes model accepts hba1c as alternative to blood_glucose_fasting."""
        available = {"hba1c", "bmi", "waist_circumference"}
        type_ages = {t: 10 for t in available}

        result = _evaluate_disease(
            "type_2_diabetes", DISEASE_REQUIREMENTS["type_2_diabetes"], available, type_ages
        )

        assert result.is_sufficient is True
        assert result.data_quality == "full_data"


# ---------------------------------------------------------------------------
# Test: Overall quality levels
# ---------------------------------------------------------------------------
class TestOverallQuality:
    """Verify overall_quality computation based on disease sufficiency counts."""

    @pytest.mark.asyncio
    async def test_overall_full_data_when_all_sufficient(self):
        """overall_quality is 'full_data' when ALL disease models are sufficient."""
        all_types = {
            "systolic_bp", "diastolic_bp", "heart_rate", "smoking_status",
            "total_cholesterol", "hdl_cholesterol", "blood_glucose_fasting",
            "bmi", "waist_circumference", "creatinine", "urine_albumin",
            "fev1", "fvc", "respiratory_rate",
        }
        type_ages = {t: 5 for t in all_types}
        patient_id = uuid.uuid4()

        with patch(
            "app.modules.measurements.data_sufficiency._get_validated_types",
            new_callable=AsyncMock,
            return_value=(all_types, type_ages),
        ):
            result = await check_data_sufficiency(AsyncMock(), patient_id)

        assert result.overall_quality == "full_data"

    @pytest.mark.asyncio
    async def test_overall_insufficient_when_none_sufficient(self):
        """overall_quality is 'insufficient' when NO disease models are sufficient."""
        patient_id = uuid.uuid4()

        with patch(
            "app.modules.measurements.data_sufficiency._get_validated_types",
            new_callable=AsyncMock,
            return_value=(set(), {}),
        ):
            result = await check_data_sufficiency(AsyncMock(), patient_id)

        assert result.overall_quality == "insufficient"

    @pytest.mark.asyncio
    async def test_empty_available_types_all_diseases_insufficient(self):
        """When no measurement types are available, every disease is insufficient."""
        patient_id = uuid.uuid4()

        with patch(
            "app.modules.measurements.data_sufficiency._get_validated_types",
            new_callable=AsyncMock,
            return_value=(set(), {}),
        ):
            result = await check_data_sufficiency(AsyncMock(), patient_id)

        for disease_status in result.diseases.values():
            assert disease_status.is_sufficient is False
            assert disease_status.data_quality == "insufficient"

    @pytest.mark.asyncio
    async def test_overall_sparse_data_when_some_sufficient(self):
        """overall_quality is 'sparse_data' when SOME but not all diseases are sufficient."""
        # Provide only stroke-related types — stroke will be sufficient,
        # but other diseases (diabetes, CKD, COPD) will not be.
        partial_types = {"systolic_bp", "diastolic_bp", "heart_rate", "smoking_status"}
        type_ages = {t: 5 for t in partial_types}
        patient_id = uuid.uuid4()

        with patch(
            "app.modules.measurements.data_sufficiency._get_validated_types",
            new_callable=AsyncMock,
            return_value=(partial_types, type_ages),
        ):
            result = await check_data_sufficiency(AsyncMock(), patient_id)

        assert result.overall_quality == "sparse_data"
        # Stroke should be sufficient with these types
        assert result.diseases["stroke"].is_sufficient is True
        # Diabetes should NOT be sufficient (missing bmi, glucose/hba1c)
        assert result.diseases["type_2_diabetes"].is_sufficient is False
