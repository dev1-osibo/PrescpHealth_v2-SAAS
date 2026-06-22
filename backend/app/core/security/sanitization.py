"""
PrescpHealth Backend — Input Sanitization Utilities.

Provides functions to detect and neutralize dangerous input patterns:
- HTML/script tag stripping (XSS prevention)
- SQL injection pattern detection
- UUID format validation for path parameters

Why application-layer sanitization in addition to RLS and parameterized queries:
    Defense-in-depth. Even though SQLAlchemy uses parameterized queries and
    RLS enforces tenant isolation at DB level, catching malicious input at
    the API boundary provides an additional safety layer and enables logging
    of attack attempts for security monitoring.

HIPAA NOTE:
    Sanitized values are NEVER logged — only the fact that sanitization
    occurred (boolean flag). This prevents PHI leakage through security logs.
"""

from __future__ import annotations

import re
from uuid import UUID

# ---------------------------------------------------------------------------
# Regex patterns for detecting malicious input
# ---------------------------------------------------------------------------

# HTML tags including self-closing and script tags
_HTML_TAG_PATTERN = re.compile(r"<[^>]*>", re.IGNORECASE)

# Script tag content (captures everything between <script> tags)
_SCRIPT_PATTERN = re.compile(
    r"<script[\s\S]*?>[\s\S]*?</script>", re.IGNORECASE
)

# Common SQL injection patterns — not exhaustive but catches obvious attacks
# Each pattern targets a specific injection technique
_SQL_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"';\s*DROP", re.IGNORECASE),        # '; DROP TABLE
    re.compile(r"\bOR\s+1\s*=\s*1\b", re.IGNORECASE),  # OR 1=1
    re.compile(r"\bUNION\s+SELECT\b", re.IGNORECASE),   # UNION SELECT
    re.compile(r"--\s*$", re.MULTILINE),            # SQL comment at end
    re.compile(r"/\*.*?\*/", re.DOTALL),            # Block comments /* */
    re.compile(r"<script", re.IGNORECASE),          # Script tag injection
    re.compile(r"javascript:", re.IGNORECASE),      # JS protocol handler
]

# UUID v4 format: 8-4-4-4-12 hexadecimal characters
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def sanitize_string(value: str) -> str:
    """
    Strip dangerous content from user-provided text input.

    Removes:
    - Script tags and their content (XSS vector)
    - All HTML tags (potential XSS through event handlers)
    - Leading/trailing whitespace

    Does NOT modify:
    - Normal text content
    - Numbers, punctuation, unicode characters
    - Medical terminology or clinical notes content

    Args:
        value: Raw user input string.

    Returns:
        str: Sanitized string with dangerous patterns removed.

    Example:
        >>> sanitize_string("<script>alert('xss')</script>Hello")
        'Hello'
        >>> sanitize_string("Normal clinical note")
        'Normal clinical note'
    """
    # First pass: remove full script blocks (content between tags)
    cleaned = _SCRIPT_PATTERN.sub("", value)
    # Second pass: remove remaining HTML tags (img, div, etc.)
    cleaned = _HTML_TAG_PATTERN.sub("", cleaned)
    # Trim whitespace
    return cleaned.strip()


def validate_uuid(value: str) -> UUID:
    """
    Validate and parse a UUID string from path parameters.

    Rejects any string that isn't a valid UUID format. This prevents
    path traversal and injection attacks through UUID path params.

    Args:
        value: String that should be a UUID (e.g., from URL path).

    Returns:
        UUID: Parsed UUID object if valid.

    Raises:
        ValueError: If the string is not a valid UUID format.

    Example:
        >>> validate_uuid("550e8400-e29b-41d4-a716-446655440000")
        UUID('550e8400-e29b-41d4-a716-446655440000')
        >>> validate_uuid("not-a-uuid")
        ValueError: Invalid UUID format
    """
    if not _UUID_PATTERN.match(value):
        raise ValueError("Invalid UUID format: expected UUID, got non-UUID string")
    return UUID(value)


def check_sql_injection(value: str) -> bool:
    """
    Detect common SQL injection patterns in user input.

    Returns True if suspicious patterns are detected. This is a
    heuristic check — not a replacement for parameterized queries.
    Use it for logging/alerting on potential attack attempts.

    Detected patterns:
    - '; DROP (statement termination + destructive command)
    - OR 1=1 (tautology injection)
    - UNION SELECT (data exfiltration)
    - -- (SQL line comment)
    - /* */ (SQL block comment)
    - <script (embedded JavaScript)
    - javascript: (protocol handler injection)

    Args:
        value: User input to check.

    Returns:
        bool: True if suspicious patterns detected, False if clean.

    Example:
        >>> check_sql_injection("'; DROP TABLE patients; --")
        True
        >>> check_sql_injection("Normal search term")
        False
    """
    for pattern in _SQL_INJECTION_PATTERNS:
        if pattern.search(value):
            return True
    return False
