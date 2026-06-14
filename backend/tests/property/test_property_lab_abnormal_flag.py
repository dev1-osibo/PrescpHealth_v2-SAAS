"""
Property Test: Lab Result Abnormal Flag Correctness (Property 7).

Invariant:
    is_abnormal=True iff numeric_value falls OUTSIDE the reference range.
    Boundary values (exactly at min/max) are INCLUSIVE — is_abnormal=False.
    Qualitative results (numeric_value=None) → is_abnormal=False.
    No reference range defined → is_abnormal=False.

Clinical Safety:
    False negatives (missed abnormals) delay critical treatment.
    False positives (incorrect abnormals) cause alert fatigue.
    This property ensures the flag computation is mathematically correct.

Validates: Requirement 3.6
"""

import pytest
from hypothesis import given, settings, strategies as st, assume

from app.modules.lab_orders.service_results import LabResultService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Reference ranges: low < high, bounded to physiological plausibility
_ref_range_st = st.tuples(
    st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False),
).filter(lambda t: t[0] < t[1])


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestLabAbnormalFlagProperty:
    """Property 7: is_abnormal flag correctness across all value/range combos."""

    @given(ref_range=_ref_range_st, data=st.data())
    @settings(max_examples=100, deadline=None)
    def test_property_value_below_low_flagged_abnormal(self, ref_range, data):
        """Values strictly below reference_range_low must be flagged abnormal."""
        low, high = ref_range
        value = data.draw(
            st.floats(
                min_value=0.001,
                max_value=max(0.002, low - 0.001),
                allow_nan=False,
                allow_infinity=False,
            )
        )
        assume(value < low)

        svc = LabResultService()
        result = svc._compute_abnormal_flag(value, low, high)
        assert result is True, f"{value} < {low} should be abnormal"

    @given(ref_range=_ref_range_st, value=st.floats(
        min_value=0.1, max_value=2000.0, allow_nan=False, allow_infinity=False
    ))
    @settings(max_examples=100, deadline=None)
    def test_property_value_above_high_flagged_abnormal(self, ref_range, value):
        """Values strictly above reference_range_high must be flagged abnormal."""
        low, high = ref_range
        assume(value > high)

        svc = LabResultService()
        result = svc._compute_abnormal_flag(value, low, high)
        assert result is True, f"{value} > {high} should be abnormal"

    @given(ref_range=_ref_range_st, data=st.data())
    @settings(max_examples=100, deadline=None)
    def test_property_value_inside_range_not_abnormal(self, ref_range, data):
        """Values within [low, high] (inclusive) must NOT be flagged abnormal."""
        low, high = ref_range
        value = data.draw(
            st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False)
        )

        svc = LabResultService()
        result = svc._compute_abnormal_flag(value, low, high)
        assert result is False, f"{value} in [{low}, {high}] should be normal"

    @given(ref_range=_ref_range_st)
    @settings(max_examples=50, deadline=None)
    def test_property_boundary_at_low_is_normal(self, ref_range):
        """Value exactly at reference_range_low is INCLUSIVE — not abnormal."""
        low, high = ref_range

        svc = LabResultService()
        result = svc._compute_abnormal_flag(low, low, high)
        assert result is False, f"Boundary value {low} == low should be normal"

    @given(ref_range=_ref_range_st)
    @settings(max_examples=50, deadline=None)
    def test_property_boundary_at_high_is_normal(self, ref_range):
        """Value exactly at reference_range_high is INCLUSIVE — not abnormal."""
        low, high = ref_range

        svc = LabResultService()
        result = svc._compute_abnormal_flag(high, low, high)
        assert result is False, f"Boundary value {high} == high should be normal"

    @given(ref_range=_ref_range_st)
    @settings(max_examples=50, deadline=None)
    def test_property_none_value_never_abnormal(self, ref_range):
        """Qualitative results (numeric_value=None) are never flagged abnormal."""
        low, high = ref_range

        svc = LabResultService()
        result = svc._compute_abnormal_flag(None, low, high)
        assert result is False, "None numeric_value must yield is_abnormal=False"

    @given(value=st.floats(
        min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False
    ))
    @settings(max_examples=50, deadline=None)
    def test_property_no_reference_range_never_abnormal(self, value):
        """When both reference bounds are None, result is never abnormal."""
        svc = LabResultService()
        result = svc._compute_abnormal_flag(value, None, None)
        assert result is False, "No reference range → is_abnormal=False"
