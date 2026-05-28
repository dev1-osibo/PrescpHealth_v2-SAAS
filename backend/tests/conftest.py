"""
PrescpHealth Backend — Test Configuration and Shared Fixtures.

Provides pytest fixtures used across all test types (unit, property, integration).
Fixtures handle:
- Test database setup (real PostgreSQL via prescphealth_test)
- Test Redis instance
- Async test client (for API endpoint testing via TestClient/httpx)
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
- Integration tests: Real DB (prescphealth_test), real Redis
"""

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings

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
# Test Settings — connects to the REAL test database
# ---------------------------------------------------------------------------

# JWT secret shared between test token generation and app middleware.
# Must match what the app uses to decode tokens.
TEST_JWT_SECRET = "test-secret-key-not-for-production-use-minimum-64-chars-long-here"

# Real test database — all migrations pre-applied, seed data available
TEST_DATABASE_URL = (
    "postgresql+asyncpg://postgres:2026victory@localhost:5432/prescphealth_test"
)
TEST_DATABASE_URL_SYNC = (
    "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"
)

# Test tenant UUID — consistent across all test fixtures
TEST_TENANT_UUID = "00000000-0000-0000-0000-000000000001"


def get_test_settings() -> Settings:
    """
    Create settings configured for integration testing.

    Uses the REAL test database (prescphealth_test) with all migrations
    applied. JWT secret matches what generate_test_jwt() uses so the
    app's middleware can decode test tokens correctly.
    """
    return Settings(
        app_env="testing",
        database_url=TEST_DATABASE_URL,
        database_url_sync=TEST_DATABASE_URL_SYNC,
        redis_url="redis://localhost:6379/15",  # DB 15 for test isolation
        jwt_secret_key=TEST_JWT_SECRET,
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
    Create a fresh FastAPI app instance wired to the real test database.

    Overrides get_settings() via monkeypatch so the database module,
    middleware, and all other code that calls get_settings() receives
    test configuration pointing at prescphealth_test.

    The settings cache is cleared BEFORE app creation to ensure the
    lru_cache doesn't serve stale production settings.
    """
    from app import config
    from app.core import database

    # Clear the lru_cache so our override takes effect
    config.get_settings.cache_clear()

    # Patch get_settings at the module level so ALL imports resolve to test config.
    # This covers: app.config.get_settings, app.core.database (which imports it),
    # and any middleware or router that calls get_settings().
    with patch("app.config.get_settings", return_value=get_test_settings()):
        # Also patch the reference in the database module directly,
        # since it may have already imported get_settings at module load time
        with patch.object(
            database, "get_settings", return_value=get_test_settings()
        ):
            from app.main import create_app
            test_app = create_app()

            # --- Register proper exception handlers for domain errors ---
            from app.core.exception_handlers import register_exception_handlers
            register_exception_handlers(test_app)

            # --- Add TenantMiddleware so JWT auth context flows correctly ---
            # The main app doesn't register middleware/routers yet (Task 33),
            # so we wire them here for full integration testing.
            # Import directly from the file using importlib.util to avoid
            # triggering app.core.middleware.__init__.py which imports
            # RateLimitMiddleware (requires redis package not installed in test).
            import importlib.util
            import sys
            _tenant_spec = importlib.util.spec_from_file_location(
                "app.core.middleware.tenant",
                "app/core/middleware/tenant.py",
            )
            _tenant_mod = importlib.util.module_from_spec(_tenant_spec)
            sys.modules["app.core.middleware.tenant"] = _tenant_mod
            _tenant_spec.loader.exec_module(_tenant_mod)
            test_app.add_middleware(_tenant_mod.TenantMiddleware)

            # --- Register ALL module routers for integration testing ---
            from app.modules.code_catalogs.router import router as codes_router
            from app.modules.encounters.router import router as encounters_router
            from app.modules.prescriptions.router import router as prescriptions_router
            from app.modules.lab_orders.router import router as lab_orders_router
            from app.modules.audit.router import router as audit_router
            from app.modules.patients.router import router as patients_router
            from app.modules.measurements.router import router as measurements_router
            from app.modules.measurements.router_detail import detail_router as measurements_detail_router

            test_app.include_router(codes_router)
            test_app.include_router(encounters_router)
            test_app.include_router(prescriptions_router)
            test_app.include_router(lab_orders_router)
            test_app.include_router(audit_router)
            test_app.include_router(patients_router)
            test_app.include_router(measurements_router)
            test_app.include_router(measurements_detail_router)

            return test_app


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """
    Provide an async HTTP client backed by the real test database.

    Uses httpx's ASGITransport to call the app directly (no network).
    The app's lifespan runs, which means middleware and startup hooks
    execute — giving us a true integration test environment.

    Yields:
        AsyncClient: HTTP client configured to call the test app.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Database Initialization Fixture (for router tests that need DB)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def init_test_db(app):
    """
    Initialize the async database engine for the test app.

    The code_catalogs router calls get_session_factory() which requires
    init_db() to have been called. This fixture does that setup and
    tears down the engine after the test.
    """
    from app.core import database

    # Patch get_settings inside the database module so init_db() uses test URL
    with patch.object(database, "get_settings", return_value=get_test_settings()):
        await database.init_db()

    yield

    # Cleanup: close the engine so connections don't leak between tests
    await database.close_db()


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
    return uuid.UUID(TEST_TENANT_UUID)


@pytest.fixture
def second_tenant_id() -> uuid.UUID:
    """
    Provide a second tenant UUID for cross-tenant isolation tests.

    Used to verify that RLS prevents access across tenant boundaries.
    """
    return uuid.UUID("00000000-0000-0000-0000-000000000002")


def generate_test_jwt(
    user_id: str = "00000000-0000-0000-0000-000000000099",
    tenant_id: str = TEST_TENANT_UUID,
    role: str = "Doctor",
    expired: bool = False,
) -> str:
    """
    Generate a test JWT token for authentication in tests.

    Creates a valid JWT signed with the test secret key. The secret
    matches what the app's middleware uses (via get_test_settings()),
    so tokens generated here will decode correctly in the app.

    Args:
        user_id: The user ID to embed in the token.
        tenant_id: The tenant ID to embed in the token.
        role: The user's role (Patient_User, Nurse, Doctor, Clinic_Admin, Super_Admin).
        expired: If True, generates an already-expired token.

    Returns:
        str: A signed JWT token string.
    """
    from jose import jwt

    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "iat": now,
        "exp": now if expired else datetime(2099, 1, 1, tzinfo=timezone.utc),
    }

    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


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
    return generate_test_jwt(
        role="Super_Admin", tenant_id=TEST_TENANT_UUID
    )


@pytest.fixture
def expired_token(test_tenant_id) -> str:
    """An expired JWT token for testing expiry handling."""
    return generate_test_jwt(expired=True, tenant_id=str(test_tenant_id))


@pytest.fixture
def auth_headers(doctor_token) -> dict:
    """Authorization headers with a Doctor token (most common test case)."""
    return {"Authorization": f"Bearer {doctor_token}"}
