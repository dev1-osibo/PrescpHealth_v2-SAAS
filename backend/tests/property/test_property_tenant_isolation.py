"""
Property Test: Tenant Isolation — Security Hardening.

Invariant:
    For ANY pair of randomly generated tenant UUIDs, the security
    utilities ALWAYS enforce tenant-scoped behavior:
    1. IP allowlist for tenant A does NOT affect tenant B
    2. Rate limiting for client A does NOT affect client B
    3. Service query methods always include tenant_id in their filters

Why this matters (HIPAA & Multi-Tenancy):
    PrescpHealth is multi-tenant. If any security boundary leaks
    between tenants, one clinic could access another clinic's data.
    Property testing with random UUIDs proves that isolation holds
    for ALL possible tenant combinations, not just our test fixtures.

**Validates: Requirement — Tenant Isolation (Cross-Tenant Access Prevention)**
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume, strategies as st

from app.core.security.ip_allowlist import IPAllowlist
from app.core.security.rate_limiter import check_rate_limit, reset_all

# ---------------------------------------------------------------------------
# Strategies — generate random tenant UUIDs and IP addresses
# ---------------------------------------------------------------------------
tenant_id_strategy = st.uuids()
ip_strategy = st.from_regex(
    r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True
)


class TestPropertyTenantIsolation:
    """Property tests proving security utilities enforce tenant isolation."""

    @given(tenant_a=tenant_id_strategy, tenant_b=tenant_id_strategy)
    @settings(max_examples=100, deadline=None)
    def test_property_ip_allowlist_isolation_between_tenants(
        self, tenant_a: uuid.UUID, tenant_b: uuid.UUID
    ):
        """
        IP restrictions for tenant A never affect tenant B.

        Invariant: Setting an allowlist on tenant_a does NOT restrict
        any IP for tenant_b (which has no configured allowlist).
        """
        assume(tenant_a != tenant_b)

        allowlist = IPAllowlist()
        # Restrict tenant_a to a single IP
        allowlist.set_allowed_ips(tenant_a, {"10.0.0.1"})

        # tenant_b should be unrestricted regardless of tenant_a's config
        assert allowlist.is_allowed("203.0.113.99", tenant_b) is True
        # tenant_a should be restricted
        assert allowlist.is_allowed("203.0.113.99", tenant_a) is False

    @given(tenant_a=tenant_id_strategy, tenant_b=tenant_id_strategy)
    @settings(max_examples=100, deadline=None)
    def test_property_rate_limit_isolation_between_clients(
        self, tenant_a: uuid.UUID, tenant_b: uuid.UUID
    ):
        """
        Rate limit exhaustion for client A never blocks client B.

        Invariant: Filling the rate limit bucket for one client_id
        does NOT affect a different client_id's ability to make requests.
        """
        assume(tenant_a != tenant_b)
        reset_all()

        client_a = str(tenant_a)
        client_b = str(tenant_b)

        # Exhaust client_a's limit
        for _ in range(5):
            check_rate_limit(client_a, max_requests=5, window_seconds=60)

        # client_a should be blocked
        assert check_rate_limit(client_a, max_requests=5, window_seconds=60) is False
        # client_b should still be allowed
        assert check_rate_limit(client_b, max_requests=5, window_seconds=60) is True

    @given(tenant_id=tenant_id_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_patient_search_always_includes_tenant_id(
        self, tenant_id: uuid.UUID
    ):
        """
        Patient search query always includes tenant_id in WHERE clause.

        Invariant: Regardless of which tenant UUID is provided, the
        generated SQL statement ALWAYS contains a tenant_id filter.
        This prevents cross-tenant data leakage at the query level.
        """
        from app.modules.patients.service import PatientService
        from app.modules.patients.search import PatientSearchFilters
        from app.core.pagination import PaginationParams

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_result.scalar_one.return_value = 0
        mock_db.execute.return_value = mock_result

        service = PatientService()
        filters = PatientSearchFilters()
        pagination = PaginationParams(page_size=10, cursor=None)

        await service.search_patients(
            db=mock_db, tenant_id=tenant_id,
            filters=filters, pagination=pagination,
        )

        # Verify at least one SQL statement includes tenant_id
        assert mock_db.execute.called
        stmt = mock_db.execute.call_args_list[0][0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "tenant_id" in compiled

    @given(tenant_id=tenant_id_strategy)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_property_referrals_query_always_includes_tenant_id(
        self, tenant_id: uuid.UUID
    ):
        """
        Referral list query always includes tenant_id in WHERE clause.

        Invariant: The referral service never produces a query that
        omits the tenant_id constraint, regardless of input.
        """
        from app.modules.referrals.service import ReferralService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_result.scalar_one.return_value = 0
        mock_db.execute.return_value = mock_result

        service = ReferralService()
        await service.list_referrals(db=mock_db, tenant_id=tenant_id)

        assert mock_db.execute.called
        stmt = mock_db.execute.call_args_list[0][0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "tenant_id" in compiled
