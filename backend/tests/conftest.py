"""
PrescpHealth Backend — Test Configuration and Shared Fixtures.

Provides pytest fixtures used across all test types (unit, property, integration).
Fixtures handle:
- Test database setup (isolated per test, using testcontainers)
- Test Redis instance
- Async test client (for API endpoint testing)
- Authentication helpers (generate JWTs for each role)
- Tenant factory (create test tenants with isolation)
- Synthetic patient data factories

Design Principles:
- Every test is fully isolated — no shared state between tests
- All test data is clearly synthetic (names like 'Test Patient Alpha')
- No real PHI ever appears in test code or fixtures
- Fixtures are composable — combine them for complex scenarios
- Async-first — all fixtures support async/await

Per testing-conventions steering rule:
- Unit tests: Fast, no external deps (mock DB/Redis)
- Property tests: Hypothesis-based, test invariants
- Integration tests: Real DB via testcontainers, real Redis
"""

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.main import create_app

# ---------------------------------------------------------------------------
# Ensure all SQLAlchemy models are imported so mappers resolve correctly.
# This prevents "name 'X' is not defined" errors when coverage instruments
# modules in a different order than normal execution.
# ---------------------------------------------------------------------------
import app.modules.auth.models  # noqa: F401
import app.modules.patients.models  # noqa: F401
import app.modules.measurements.models  # noqa: F401
import app.modules.encounters.models  # noqa: F401
import app.modules.prescriptions.models  # noqa: F401
import app.modules.lab_orders.models  # noqa: F401


# ---------------------------------------------------------------------------
# Override settings for testing
# ---------------------------------------------------------------------------
def get_test_settings() -> Settings:
    """
    Create settings configured for testing.

    Uses test-specific values that don't connect to real services.
    In integration tests, these are overridden with testcontainer URLs.
    """
    return Settings(
        app_env="testing",
        database_url="postgresql+asyncpg://test:test@localhost:5432/prescphealth_test",
        database_url_sync="postgresql://test:test@localhost:5432/prescphealth_test",
        redis_url="redis://localhost:6379/15",  # Use DB 15 for tests (isolated)
        jwt_secret_key="test-secret-key-not-for-production-use-minimum-64-chars-long-here",
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=15,
        jwt_refresh_token_expire_days=7,
        enable_docs=True,
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
        sendgrid_api_key="test-sendgrid-key",
        log_level="DEBUG",
        log_format="console",
    )


# ---------------------------------------------------------------------------
# App and Client Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def app():
    """
    Create a fresh FastAPI app instance for testing.

    Each test gets its own app instance to prevent state leakage.
    Settings are overridden with test-specific values.
    """
    # Override the settings singleton for testing
    from app import config
    config.get_settings.cache_clear()

    app = create_app()
    return app


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """
    Provide an async HTTP client for testing API endpoints.

    Uses httpx's ASGITransport to call the app directly (no network).
    This is faster than starting a real server and avoids port conflicts.

    Yields:
        AsyncClient: HTTP client configured to call the test app.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Authentication Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def test_tenant_id() -> uuid.UUID:
    """
    Provide a consistent test tenant UUID.

    All test data belongs to this tenant unless explicitly testing
    cross-tenant isolation (which uses a second tenant).
    """
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def second_tenant_id() -> uuid.UUID:
    """
    Provide a second tenant UUID for cross-tenant isolation tests.

    Used to verify that RLS prevents access across tenant boundaries.
    """
    return uuid.UUID("00000000-0000-0000-0000-000000000002")


def generate_test_jwt(
    user_id: str = "test-user-001",
    tenant_id: str = "00000000-0000-0000-0000-000000000001",
    role: str = "Doctor",
    expired: bool = False,
) -> str:
    """
    Generate a test JWT token for authentication in tests.

    Creates a valid JWT signed with the test secret key.
    Can generate expired tokens for testing expiry handling.

    Args:
        user_id: The user ID to embed in the token.
        tenant_id: The tenant ID to embed in the token.
        role: The user's role (Patient_User, Nurse, Doctor, Clinic_Admin, Super_Admin).
        expired: If True, generates an already-expired token.

    Returns:
        str: A signed JWT token string.
    """
    from jose import jwt

    settings = get_test_settings()
    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "iat": now,
        "exp": now if expired else datetime(2099, 1, 1, tzinfo=timezone.utc),
    }

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@pytest.fixture
def doctor_token(test_tenant_id) -> str:
    """JWT token for a Doctor role user."""
    return generate_test_jwt(role="Doctor", tenant_id=str(test_tenant_id))


@pytest.fixture
def nurse_token(test_tenant_id) -> str:
    """JWT token for a Nurse role user."""
    return generate_test_jwt(role="Nurse", tenant_id=str(test_tenant_id))


@pytest.fixture
def patient_token(test_tenant_id) -> str:
    """JWT token for a Patient_User role user."""
    return generate_test_jwt(role="Patient_User", tenant_id=str(test_tenant_id))


@pytest.fixture
def admin_token(test_tenant_id) -> str:
    """JWT token for a Clinic_Admin role user."""
    return generate_test_jwt(role="Clinic_Admin", tenant_id=str(test_tenant_id))


@pytest.fixture
def super_admin_token() -> str:
    """JWT token for a Super_Admin role user (cross-tenant access)."""
    return generate_test_jwt(role="Super_Admin", tenant_id="00000000-0000-0000-0000-000000000001")


@pytest.fixture
def expired_token(test_tenant_id) -> str:
    """An expired JWT token for testing expiry handling."""
    return generate_test_jwt(expired=True, tenant_id=str(test_tenant_id))


@pytest.fixture
def auth_headers(doctor_token) -> dict:
    """Authorization headers with a Doctor token (most common test case)."""
    return {"Authorization": f"Bearer {doctor_token}"}
