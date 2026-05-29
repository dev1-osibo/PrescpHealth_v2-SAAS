"""Unit tests for app.modules.auth.rbac (Role enum, parse_role, require_role)."""

import pytest
from types import SimpleNamespace

from app.core.exceptions import AuthError, ForbiddenError
from app.modules.auth.rbac import (
    Role,
    ROLE_MAP,
    parse_role,
    require_role,
)


class TestRoleEnum:
    def test_role_hierarchy_order(self):
        assert Role.PATIENT_USER < Role.NURSE < Role.DOCTOR
        assert Role.DOCTOR < Role.CLINIC_ADMIN < Role.SUPER_ADMIN

    def test_role_values(self):
        assert int(Role.PATIENT_USER) == 1
        assert int(Role.SUPER_ADMIN) == 5

    def test_role_map_has_all_five(self):
        assert len(ROLE_MAP) == 5
        assert set(ROLE_MAP.keys()) == {
            "Patient_User", "Nurse", "Doctor", "Clinic_Admin", "Super_Admin"
        }


class TestParseRole:
    def test_valid_doctor(self):
        assert parse_role("Doctor") == Role.DOCTOR

    def test_valid_super_admin(self):
        assert parse_role("Super_Admin") == Role.SUPER_ADMIN

    def test_valid_patient_user(self):
        assert parse_role("Patient_User") == Role.PATIENT_USER

    def test_invalid_role_raises_auth_error(self):
        with pytest.raises(AuthError):
            parse_role("Hacker")

    def test_empty_string_raises_auth_error(self):
        with pytest.raises(AuthError):
            parse_role("")

    def test_case_sensitive(self):
        # "doctor" is not the same as "Doctor"
        with pytest.raises(AuthError):
            parse_role("doctor")


class TestRequireRoleDependency:
    """The require_role(...) factory returns a dependency callable."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_raises_auth_error(self):
        checker = require_role(Role.NURSE)
        request = SimpleNamespace(
            state=SimpleNamespace(),  # no user_role attr
            url=SimpleNamespace(path="/test"),
        )
        # getattr(state, "user_role", None) → None → AuthError
        with pytest.raises(AuthError):
            await checker(request)

    @pytest.mark.asyncio
    async def test_insufficient_role_raises_forbidden(self):
        checker = require_role(Role.DOCTOR)
        request = SimpleNamespace(
            state=SimpleNamespace(
                user_role="Nurse",
                user_id="u1",
                tenant_id="t1",
            ),
            url=SimpleNamespace(path="/test"),
        )
        with pytest.raises(ForbiddenError):
            await checker(request)

    @pytest.mark.asyncio
    async def test_sufficient_role_returns_user_context(self):
        checker = require_role(Role.NURSE)
        request = SimpleNamespace(
            state=SimpleNamespace(
                user_role="Doctor",
                user_id="u1",
                tenant_id="t1",
            ),
            url=SimpleNamespace(path="/test"),
        )
        result = await checker(request)
        assert result["role"] == Role.DOCTOR
        assert result["user_id"] == "u1"
        assert result["tenant_id"] == "t1"
        assert result["role_str"] == "Doctor"

    @pytest.mark.asyncio
    async def test_exact_role_match_allowed(self):
        checker = require_role(Role.CLINIC_ADMIN)
        request = SimpleNamespace(
            state=SimpleNamespace(
                user_role="Clinic_Admin",
                user_id="u1",
                tenant_id="t1",
            ),
            url=SimpleNamespace(path="/test"),
        )
        result = await checker(request)
        assert result["role"] == Role.CLINIC_ADMIN

    @pytest.mark.asyncio
    async def test_super_admin_passes_lower_role_check(self):
        checker = require_role(Role.NURSE)
        request = SimpleNamespace(
            state=SimpleNamespace(
                user_role="Super_Admin",
                user_id="u1",
                tenant_id="t1",
            ),
            url=SimpleNamespace(path="/test"),
        )
        result = await checker(request)
        assert result["role"] == Role.SUPER_ADMIN

    @pytest.mark.asyncio
    async def test_invalid_role_string_in_state_raises_auth_error(self):
        checker = require_role(Role.NURSE)
        request = SimpleNamespace(
            state=SimpleNamespace(
                user_role="Hacker",
                user_id="u1",
                tenant_id="t1",
            ),
            url=SimpleNamespace(path="/test"),
        )
        with pytest.raises(AuthError):
            await checker(request)
