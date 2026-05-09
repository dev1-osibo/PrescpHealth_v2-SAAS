# =============================================================================
# backend/app/core/logging_setup.py
# =============================================================================
# Structured logging configuration using structlog.
#
# All logs in PrescpHealth are structured JSON in production, enabling:
#   - Machine-parseable log aggregation (ELK, CloudWatch, Datadog)
#   - Correlation ID tracing across request -> task -> event chains
#   - Filtering by tenant_id, user_id, module, action
#   - Performance tracking via duration_ms fields
#
# In development, logs use a human-readable console format for easier debugging.
#
# HIPAA COMPLIANCE:
#   - NEVER log PHI (patient names, measurements, diagnoses, risk scores)
#   - Only log opaque IDs (patient_id UUID) and action metadata
#   - Debug level disabled in production (may accidentally contain PHI)
#
# Requirements: 21.4 (no PHI in logs), observability steering rule
# =============================================================================

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """
    Configure structlog for the entire application.

    Sets up structured logging with either JSON output (production) or
    colored console output (development). Integrates with Python stdlib
    logging so third-party libraries (uvicorn, sqlalchemy) also emit
    structured logs.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                   Use INFO in production, DEBUG only in development.
        log_format: Output format -- "json" for production, "console" for dev.

    Side Effects:
        - Configures the global structlog settings
        - Configures Python stdlib logging root handler
        - All subsequent log calls use the configured format
    """
    # Shared processors applied to every log event regardless of format.
    # These add context that is critical for debugging and tracing.
    shared_processors: list[structlog.types.Processor] = [
        # Add log level as a string field (e.g., "info", "error")
        structlog.stdlib.add_log_level,
        # Add logger name for identifying which module emitted the log
        structlog.stdlib.add_logger_name,
        # Add ISO-8601 timestamp for temporal ordering
        structlog.processors.TimeStamper(fmt="iso"),
        # Add call site info (file, function, line) -- useful for debugging
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        ),
        # Merge any thread-local or context-local variables into the event
        structlog.contextvars.merge_contextvars,
        # Format exceptions as structured data (not raw tracebacks in output)
        structlog.processors.format_exc_info,
        # Unpack positional args into the event string
        structlog.processors.UnicodeDecoder(),
    ]

    # Choose renderer based on environment:
    # - JSON for production (machine-parseable, log aggregation friendly)
    # - Console for development (colored, human-readable)
    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog globally
    structlog.configure(
        processors=[
            # Filter by log level early to avoid processing discarded events
            structlog.stdlib.filter_by_level,
            *shared_processors,
            # Prepare event dict for stdlib logging integration
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        # Use stdlib logger as the underlying logger (integrates with uvicorn etc.)
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Cache logger instances for performance (avoid re-creation per call)
        cache_logger_on_first_use=True,
    )

    # Configure Python stdlib logging to use structlog formatter.
    # This ensures uvicorn, sqlalchemy, and other libraries also emit
    # structured logs in the same format.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Set up root handler writing to stdout (container-friendly -- no file I/O)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Quiet down noisy third-party loggers that spam at INFO level
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
