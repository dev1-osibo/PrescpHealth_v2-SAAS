"""
Unit tests for app.core.logging_setup.

Tests that logging configuration:
- Accepts both JSON and console formats
- Honors specified log levels
- Quiets noisy third-party loggers
- Doesn't crash on subsequent reconfiguration
"""

import logging

import pytest
import structlog

from app.core.logging_setup import configure_logging


def test_configure_logging_json_format_does_not_raise():
    """configure_logging with json format completes successfully."""
    configure_logging(log_level="INFO", log_format="json")


def test_configure_logging_console_format_does_not_raise():
    """configure_logging with console format completes successfully."""
    configure_logging(log_level="DEBUG", log_format="console")


def test_configure_logging_sets_root_level_info():
    """Root logger is set to INFO when log_level=INFO."""
    configure_logging(log_level="INFO", log_format="json")
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_sets_root_level_debug():
    """Root logger is set to DEBUG when log_level=DEBUG."""
    configure_logging(log_level="DEBUG", log_format="json")
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_sets_root_level_error():
    """Root logger is set to ERROR when log_level=ERROR."""
    configure_logging(log_level="ERROR", log_format="json")
    assert logging.getLogger().level == logging.ERROR


def test_configure_logging_defaults_to_info_for_unknown_level():
    """Unknown level falls back to INFO."""
    configure_logging(log_level="NONSENSE", log_format="json")
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_quiets_uvicorn_access():
    """uvicorn.access logger is set to WARNING."""
    configure_logging(log_level="INFO", log_format="json")
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


def test_configure_logging_quiets_sqlalchemy_engine():
    """sqlalchemy.engine logger is set to WARNING."""
    configure_logging(log_level="INFO", log_format="json")
    assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING


def test_configure_logging_clears_existing_handlers():
    """Existing root handlers are cleared before adding new ones."""
    root = logging.getLogger()
    # Add a fake handler
    fake = logging.StreamHandler()
    root.addHandler(fake)
    count_before = len(root.handlers)

    configure_logging(log_level="INFO", log_format="json")

    # After configure, only one handler should remain (the new structlog one)
    assert len(root.handlers) == 1
    assert fake not in root.handlers


def test_configure_logging_is_idempotent():
    """Calling configure_logging twice does not raise or leak handlers."""
    configure_logging(log_level="INFO", log_format="json")
    configure_logging(log_level="DEBUG", log_format="console")
    # Should have exactly one handler (cleared each time)
    assert len(logging.getLogger().handlers) == 1


def test_configure_logging_structlog_get_logger_returns_logger():
    """After configuration, structlog.get_logger returns a usable logger."""
    configure_logging(log_level="INFO", log_format="json")
    logger = structlog.get_logger("test_module")
    # Must not raise
    logger.info("test_event", key="value")


def test_configure_logging_lowercase_level_works():
    """log_level accepts lowercase strings (gets upper()'d)."""
    configure_logging(log_level="warning", log_format="json")
    assert logging.getLogger().level == logging.WARNING
