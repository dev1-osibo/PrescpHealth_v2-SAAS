"""
PrescpHealth ML Engine — Forecast Data Quality Annotation.

Annotates forecast quality based on measurement data availability.
This flag determines how the frontend displays the forecast:
    - "full_data": Full confidence chart with narrow CIs
    - "sparse_data": Chart with "limited data" warning banner
    - "prior_only": No chart — text-only message using population priors

Clinical rationale:
    A forecast based on 2 measurements over 2 weeks is fundamentally
    different from one based on 15 measurements over 2 years. The clinician
    MUST know this distinction to properly weight the AI's output.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Thresholds for data quality classification
FULL_DATA_MIN_MEASUREMENTS: int = 10
FULL_DATA_MIN_SPAN_DAYS: int = 180

SPARSE_DATA_MIN_MEASUREMENTS: int = 3
SPARSE_DATA_MIN_SPAN_DAYS: int = 30


def annotate_quality(measurement_count: int, time_span_days: int) -> str:
    """Classify forecast data quality based on measurement availability.

    This function determines how much trust the forecast engine (and the
    clinician) should place in the predictions. More data over longer
    periods yields more reliable forecasts.

    Args:
        measurement_count: Total number of measurements in history.
        time_span_days: Time span between earliest and latest measurement (days).

    Returns:
        Quality tier string:
            "full_data" — >10 measurements AND >180 days span.
                Forecast is well-supported. Show full chart.
            "sparse_data" — 3-10 measurements AND 30-180 days span.
                Forecast has limited confidence. Show chart + warning.
            "prior_only" — <3 measurements OR <30 days span.
                Insufficient data for individual forecast. Show population
                priors only with clear "insufficient data" message.
    """
    if (
        measurement_count >= FULL_DATA_MIN_MEASUREMENTS
        and time_span_days >= FULL_DATA_MIN_SPAN_DAYS
    ):
        return "full_data"

    if (
        measurement_count >= SPARSE_DATA_MIN_MEASUREMENTS
        and time_span_days >= SPARSE_DATA_MIN_SPAN_DAYS
    ):
        return "sparse_data"

    return "prior_only"
