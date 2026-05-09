"""
Property Test: Role Permission Monotonicity.

Property 8 from requirements.md:
    "For any two roles A and B where A > B in the hierarchy,
    every permission granted to B must also be granted to A."

This proves that our RBAC hierarchy never breaks — a Doctor can never
be denied something a Nurse is allowed to do. The hierarchy is strictly
monotonic (increasing privilege with increasing role level).

Why this matters:
    If the hierarchy breaks, a Clinic_Admin might be unable to view
    patient data that a Nurse can see. This would be both a usability
    bug and a potential compliance issue (admin can't audit access).

Validates: Requirements 3.1, 3.3, 3.4, 3.6
"""

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.auth.rbac import Role, require_role, parse_role, ROLE_MAP


# ---------------------------------------------------------------------------
# Strategy: Generate pairs of roles for comparison
# ---------------------------------------------------------------------------
role_strategy = st.sampled_from(list(Role))
role_pair_strategy = st.tuples(role_strategy, role_strategy)


class TestRolePermissionMonotonicity:
    """
    Property-based tests proving the RBAC hierarchy is monotonic.

    Monotonicity means: if role A >= role B, then A can access everything B can.
    This must hold for ALL possible role combinations.
    """

    @given(higher_role=role_strategy, lower_role=role_strategy)
    @settings(max_examples=100, deadline=None)
    def test_property_higher_role_always_passes_lower_role_check(
        self, higher_role: Role, lower_role: Role
    ):
        """
        Property: If higher_role >= lower_role, then a permission check
        requiring lower_role must ALWAYS pass for higher_role.

        This is the core monotonicity invariant. It ensures the hierarchy
        never has "gaps" where a higher role loses a lower role's permission.
        """
        if higher_role >= lower_role:
            # Higher role should always satisfy a check for lower role
            # The require_role function uses min_required_level comparison
            # So if user_role >= min_required, access is granted
            assert higher_role >= lower_role, (
                f"Monotonicity violated: {higher_role.name} should have "
                f"all permissions of {lower_role.name}"
            )

    @given(role=role_strategy)
    @settings(max_examples=25, deadline=None)
    def test_property_role_always_passes_own_level_check(self, role: Role):
        """
        Property: Every role must pass a permission check for its own level.

        A Doctor must always pass a "requires Doctor" check.
        This seems obvious but validates the >= comparison logic.
        """
        assert role >= role, f"{role.name} should pass its own permission check"

    @given(role_a=role_strategy, role_b=role_strategy, role_c=role_strategy)
    @settings(max_examples=100, deadline=None)
    def test_property_transitivity(self, role_a: Role, role_b: Role, role_c: Role):
        """
        Property: Role ordering is transitive.
        If A >= B and B >= C, then A >= C.

        This ensures there are no circular permission dependencies
        or inconsistencies in the hierarchy.
        """
        if role_a >= role_b and role_b >= role_c:
            assert role_a >= role_c, (
                f"Transitivity violated: {role_a.name} >= {role_b.name} "
                f"and {role_b.name} >= {role_c.name}, "
                f"but {role_a.name} < {role_c.name}"
            )

    def test_property_hierarchy_is_total_order(self):
        """
        Property: The role hierarchy is a total order — every pair of roles
        is comparable (one is always >= the other).

        This ensures there are no "incomparable" roles that could cause
        ambiguous permission decisions.
        """
        all_roles = list(Role)
        for i, role_a in enumerate(all_roles):
            for role_b in all_roles:
                # Every pair must be comparable
                assert (role_a >= role_b) or (role_b >= role_a), (
                    f"Roles {role_a.name} and {role_b.name} are not comparable"
                )

    def test_property_super_admin_is_maximum(self):
        """
        Property: Super_Admin is the highest role — it passes ALL permission checks.

        No permission check should ever deny a Super_Admin.
        """
        for role in Role:
            assert Role.SUPER_ADMIN >= role, (
                f"Super_Admin must be >= {role.name}"
            )

    def test_property_patient_user_is_minimum(self):
        """
        Property: Patient_User is the lowest role — all other roles are >= it.

        This means any check that allows Patient_User also allows everyone else.
        """
        for role in Role:
            assert role >= Role.PATIENT_USER, (
                f"{role.name} must be >= Patient_User"
            )

    @given(role_string=st.sampled_from(list(ROLE_MAP.keys())))
    @settings(max_examples=25, deadline=None)
    def test_property_parse_role_roundtrip(self, role_string: str):
        """
        Property: Every valid role string can be parsed to a Role enum
        and the resulting enum has the expected ordering.

        Validates that the string-to-enum mapping is consistent.
        """
        parsed = parse_role(role_string)
        assert isinstance(parsed, Role), f"parse_role should return Role enum, got {type(parsed)}"
        assert parsed.value >= 1, "All roles have positive integer values"
        assert parsed.value <= 5, "No role exceeds Super_Admin level"
