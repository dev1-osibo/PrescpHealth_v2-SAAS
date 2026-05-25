"""
Property Test: Measurement Deviation Flagging.

Property 15 from design.md:
    "For any new measurement where the patient has sufficient historical data
    to compute a baseline, if the new value deviates from the patient's
    personal mean by more than two standard deviations, the measurement SHALL
    be flagged for clinician review. If the deviation is within two standard
    deviations, the measurement SHALL NOT be flagged."

This proves that the deviation flagging system maintains correct invariants:
1. Values within 2σ of baseline are NOT flagged (is_flagged=False)
2. Values beyond 2σ of baseline ARE flagged (is_flagged=True)
3. The sigma_deviation is always non-negative (absolute distance)
4. The flag_reason never contains the actual measurement value (PHI safety)
5. With std=0, any value different from mean is flagged (insufficient history)

Why this matters (Clinical Safety):
    Deviation flagging catches sudden changes in a patient's measurements
    that may indicate medication non-compliance, acute illness onset, or
    device malfunction. Missing a genuine deviation could delay critical
    clinical intervention. False positives are acceptable (clinicians can
    dismiss them), but false negatives are dangerous.

Validates: Requirements 5.6
"""

import pytest
from hypothesis import given, settings, assume, strategies as st

from app.modules.measurements.validators import check_deviation


# ---------------------------------------------------------------------------
# Strategies: Generate realistic baseline statistics and measurement values
# ---------------------------------------------------------------------------

# Baseline mean — realistic clinical measurement means
# Covers a wide range to test across different measurement magnitudes
baseline_mean_strategy = st.floats(
    min_value=1.0,
    max_value=500.0,
    allow_nan=False,
    allow_infinity=False,
)

# Baseline standard deviation — must be positive for meaningful statistics
# Represents normal patient variability for a measurement type
baseline_std_strategy = st.floats(
    min_value=0.1,
    max_value=50.0,
    allow_nan=False,
    allow_infinity=False,
)


def value_within_2sigma(mean: float, std: float) -> st.SearchStrategy[float]:
    """
    Generate a value within 2 standard deviations of the mean.

    These values are within the patient's normal variability and should
    NOT be flagged. Uses a slightly tighter bound (1.9σ) to avoid
    floating-point boundary issues at exactly 2σ.
    """
    lower = mean - (1.9 * std)
    upper = mean + (1.9 * std)
    return st.floats(
        min_value=lower,
        max_value=upper,
        allow_nan=False,
        allow_infinity=False,
    )


def value_beyond_2sigma(mean: float, std: float) -> st.SearchStrategy[float]:
    """
    Generate a value beyond 2 standard deviations from the mean.

    These values represent clinically significant deviations and should
    be flagged for clinician review. Uses 2.1σ to avoid boundary issues.
    """
    # Choose either above or below the 2σ boundary
    lower_bound = mean - (10.0 * std)  # Up to 10σ below
    upper_bound = mean + (10.0 * std)  # Up to 10σ above
    below_threshold = mean - (2.1 * std)
    above_threshold = mean + (2.1 * std)

    return st.one_of(
        st.floats(
            min_value=lower_bound,
            max_value=below_threshold,
            allow_nan=False,
            allow_infinity=False,
        ),
        st.floats(
            min_value=above_threshold,
            max_value=upper_bound,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


class TestMeasurementDeviationFlagging:
    """
    Property-based tests proving measurement deviation flagging invariants.

    The core invariants tested:
    1. Within 2σ → not flagged
    2. Beyond 2σ → flagged
    3. sigma_deviation is always non-negative
    4. flag_reason never contains the actual value (PHI)
    5. With std=0, any different value is flagged
    """

    @given(
        baseline_mean=baseline_mean_strategy,
        baseline_std=baseline_std_strategy,
        data=st.data(),
    )
    @settings(max_examples=100, deadline=None)
    def test_property_within_2sigma_not_flagged(
        self,
        baseline_mean: float,
        baseline_std: float,
        data,
    ):
        """
        Property: For any value within 2σ of the patient's baseline mean,
        check_deviation returns is_flagged=False.

        Values within normal variability should not trigger clinician review.
        The 2σ threshold means ~95% of normal readings fall within this range.

        **Validates: Requirements 5.6**
        """
        value = data.draw(value_within_2sigma(baseline_mean, baseline_std))

        is_flagged, sigma_deviation, flag_reason = check_deviation(
            value, baseline_mean, baseline_std
        )

        # INVARIANT: Within 2σ means NOT flagged
        assert is_flagged is False, (
            f"Value within 2σ of baseline was incorrectly flagged. "
            f"sigma_deviation={sigma_deviation:.2f}, threshold=2.0. "
            f"Values within normal variability should not trigger review."
        )

        # When not flagged, reason should be None
        assert flag_reason is None, (
            f"flag_reason should be None when not flagged, got: '{flag_reason}'"
        )

    @given(
        baseline_mean=baseline_mean_strategy,
        baseline_std=baseline_std_strategy,
        data=st.data(),
    )
    @settings(max_examples=100, deadline=None)
    def test_property_beyond_2sigma_is_flagged(
        self,
        baseline_mean: float,
        baseline_std: float,
        data,
    ):
        """
        Property: For any value beyond 2σ of the patient's baseline mean,
        check_deviation returns is_flagged=True.

        Values outside normal variability indicate a potential clinical change
        that warrants clinician review.

        **Validates: Requirements 5.6**
        """
        value = data.draw(value_beyond_2sigma(baseline_mean, baseline_std))

        is_flagged, sigma_deviation, flag_reason = check_deviation(
            value, baseline_mean, baseline_std
        )

        # INVARIANT: Beyond 2σ means flagged
        assert is_flagged is True, (
            f"Value beyond 2σ of baseline was NOT flagged. "
            f"sigma_deviation={sigma_deviation:.2f}, threshold=2.0. "
            f"Clinically significant deviations must trigger review."
        )

        # When flagged, reason should be a non-empty string
        assert flag_reason is not None and len(flag_reason) > 0, (
            "flag_reason must be provided when measurement is flagged"
        )

    @given(
        value=st.floats(min_value=-1000.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
        baseline_mean=baseline_mean_strategy,
        baseline_std=baseline_std_strategy,
    )
    @settings(max_examples=100, deadline=None)
    def test_property_sigma_deviation_always_non_negative(
        self,
        value: float,
        baseline_mean: float,
        baseline_std: float,
    ):
        """
        Property: The sigma_deviation returned by check_deviation is always
        non-negative, regardless of whether the value is above or below the mean.

        sigma_deviation represents the absolute magnitude of deviation,
        not the direction. It's computed as |value - mean| / std.

        **Validates: Requirements 5.6**
        """
        is_flagged, sigma_deviation, flag_reason = check_deviation(
            value, baseline_mean, baseline_std
        )

        # INVARIANT: sigma_deviation is always >= 0
        assert sigma_deviation >= 0.0, (
            f"sigma_deviation must be non-negative, got {sigma_deviation}. "
            f"Deviation magnitude is always positive (absolute distance)."
        )

    @given(
        baseline_mean=baseline_mean_strategy,
        baseline_std=baseline_std_strategy,
        data=st.data(),
    )
    @settings(max_examples=100, deadline=None)
    def test_property_flag_reason_never_contains_actual_value(
        self,
        baseline_mean: float,
        baseline_std: float,
        data,
    ):
        """
        Property: The flag_reason string never contains the actual measurement
        value (PHI safety).

        Flag reasons may be stored in the database, logged, or displayed in
        dashboards. They must describe the deviation in statistical terms
        (e.g., "2.3σ above baseline") without revealing the actual value.

        **Validates: Requirements 5.6**
        """
        # Generate a value that will be flagged (beyond 2σ)
        value = data.draw(value_beyond_2sigma(baseline_mean, baseline_std))

        is_flagged, sigma_deviation, flag_reason = check_deviation(
            value, baseline_mean, baseline_std
        )

        # Only check flag_reason when the measurement is actually flagged
        if flag_reason is not None:
            value_str = str(value)
            value_formatted = f"{value:.1f}"

            # The sigma deviation value (e.g., "10.0") legitimately appears
            # in the flag_reason. We need to avoid false positives where the
            # measurement value string is a substring of the sigma display.
            sigma_rounded = round(sigma_deviation, 1)
            allowed_numbers = {
                str(sigma_rounded),
                f"{sigma_rounded:.1f}",
                str(sigma_deviation),
                "2",  # The threshold value "2" appears in ">2σ threshold"
            }

            # Use regex word boundary to check for standalone occurrence
            # This avoids false positives like "0.0" matching inside "10.0"
            import re

            if value_str not in allowed_numbers:
                pattern = re.compile(r"(?<!\d)" + re.escape(value_str) + r"(?!\d)")
                assert not pattern.search(flag_reason), (
                    f"flag_reason contains the actual value '{value_str}' — "
                    f"this is a PHI leak. Reason: '{flag_reason}'"
                )

            if value_formatted not in allowed_numbers:
                sigma_str = f"{sigma_deviation:.1f}"
                if value_formatted != sigma_str:
                    pattern = re.compile(r"(?<!\d)" + re.escape(value_formatted) + r"(?!\d)")
                    assert not pattern.search(flag_reason), (
                        f"flag_reason contains formatted value '{value_formatted}' — "
                        f"this is a PHI leak. Reason: '{flag_reason}'"
                    )

    @given(
        baseline_mean=baseline_mean_strategy,
        data=st.data(),
    )
    @settings(max_examples=50, deadline=None)
    def test_property_std_zero_flags_any_different_value(
        self,
        baseline_mean: float,
        data,
    ):
        """
        Property: With baseline_std=0 (only one prior measurement or all
        identical), any value different from the mean is flagged.

        When there's no variability data, we cannot assess whether a
        deviation is statistically significant. The safe default is to
        flag any difference for clinician review.

        **Validates: Requirements 5.6**
        """
        # Generate a value that differs from the mean
        offset = data.draw(
            st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False)
        )
        # Choose direction (above or below mean)
        direction = data.draw(st.sampled_from([1.0, -1.0]))
        value = baseline_mean + (offset * direction)

        is_flagged, sigma_deviation, flag_reason = check_deviation(
            value, baseline_mean, baseline_std=0.0
        )

        # INVARIANT: With std=0, any different value is flagged
        assert is_flagged is True, (
            f"With std=0, value different from mean should be flagged. "
            f"Value differs from mean by {abs(value - baseline_mean):.2f} "
            f"but was not flagged."
        )

    @given(baseline_mean=baseline_mean_strategy)
    @settings(max_examples=50, deadline=None)
    def test_property_std_zero_exact_match_not_flagged(
        self,
        baseline_mean: float,
    ):
        """
        Property: With baseline_std=0, a value exactly equal to the mean
        is NOT flagged (no deviation exists).

        If the value matches the only known baseline exactly, there's no
        reason to flag it — it's consistent with the patient's history.

        **Validates: Requirements 5.6**
        """
        is_flagged, sigma_deviation, flag_reason = check_deviation(
            baseline_mean, baseline_mean, baseline_std=0.0
        )

        # INVARIANT: Exact match with std=0 is not flagged
        assert is_flagged is False, (
            f"Value exactly matching mean with std=0 should NOT be flagged. "
            f"No deviation exists."
        )
        assert sigma_deviation == 0.0, (
            f"sigma_deviation should be 0.0 for exact match, got {sigma_deviation}"
        )
