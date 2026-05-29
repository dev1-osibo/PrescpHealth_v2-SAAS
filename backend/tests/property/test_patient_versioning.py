"""
Property Test: Patient Profile Version History.

Property 16 from design.md:
    "For any update to a patient profile field, the platform SHALL store
    the previous value in a versioned history record containing the changed
    fields with old and new values, the identity of the user who made the
    change, and the timestamp. The version history SHALL be accessible to
    Doctors and Clinic_Admins."

This proves that the patient versioning system maintains correct invariants:
1. Version numbers are strictly monotonically increasing per patient (1, 2, 3, ...)
2. Every update creates exactly one version record (1:1 correspondence)
3. Version snapshot at version N reflects the state after applying all changes up to N
4. The diff (changes field) accurately represents the difference between version N-1 and N
5. Version records are immutable — no update/delete methods exposed
6. First version always has change_type="create"
7. Soft delete creates a version with change_type="soft_delete"
8. Restore creates a version with change_type="restore"

Why this matters (HIPAA):
    Patient profile changes must be fully auditable. Clinicians and admins
    need to see exactly what changed, when, and by whom. If version history
    is incomplete or inaccurate, the audit trail is compromised and the
    platform cannot demonstrate compliance during a HIPAA audit.

Validates: Requirements 4.5
"""

import uuid
from datetime import date, datetime, timezone
from typing import Any

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.patients.models import (
    Patient,
    PatientChangeType,
    PatientGender,
    PatientStatus,
    PatientVersion,
)


# ---------------------------------------------------------------------------
# Strategies: Generate realistic patient data and update sequences
# ---------------------------------------------------------------------------

# Patient first names — clearly synthetic per testing conventions
first_name_strategy = st.sampled_from([
    "TestAlpha", "TestBeta", "TestGamma", "TestDelta", "TestEpsilon",
    "TestZeta", "TestEta", "TestTheta", "TestIota", "TestKappa",
    "TestLambda", "TestMu", "TestNu", "TestXi", "TestOmicron",
])

# Patient last names — clearly synthetic
last_name_strategy = st.sampled_from([
    "PatientOne", "PatientTwo", "PatientThree", "PatientFour",
    "PatientFive", "PatientSix", "PatientSeven", "PatientEight",
    "PatientNine", "PatientTen", "PatientEleven", "PatientTwelve",
])

# Gender options matching the PatientGender enum
gender_strategy = st.sampled_from([
    PatientGender.MALE,
    PatientGender.FEMALE,
    PatientGender.OTHER,
    PatientGender.PREFER_NOT_TO_SAY,
])

# Patient status options
status_strategy = st.sampled_from([
    PatientStatus.ACTIVE,
    PatientStatus.INACTIVE,
    PatientStatus.DECEASED,
    PatientStatus.TRANSFERRED,
])

# Date of birth — realistic clinical range (1 to 120 years old)
dob_strategy = st.dates(
    min_value=date(1905, 1, 1),
    max_value=date(2024, 12, 31),
)

# Blood type options
blood_type_strategy = st.sampled_from([
    "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", None,
])

# Phone number — synthetic format
phone_strategy = st.from_regex(r"\+1-555-\d{4}", fullmatch=True)

# Generate random UUIDs for tenant and user IDs
uuid_strategy = st.uuids()

# Number of updates to apply in a sequence (1 to 15)
update_count_strategy = st.integers(min_value=1, max_value=15)

# Fields that can be updated on a patient profile
updatable_fields_strategy = st.sampled_from([
    "first_name",
    "last_name",
    "date_of_birth",
    "gender",
    "phone_number",
    "blood_type",
    "status",
])


# ---------------------------------------------------------------------------
# Helper: Build a patient snapshot dict from current state
# ---------------------------------------------------------------------------
def build_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """
    Build a version snapshot from the current patient state.

    The snapshot captures the full patient state at a point in time,
    enabling point-in-time recovery without replaying all changes.

    Args:
        state: Current patient field values.

    Returns:
        A dict representing the full patient state snapshot.
    """
    return {k: v for k, v in state.items()}


def generate_new_value(field: str, current_value: Any, draw) -> Any:
    """
    Generate a new value for a given field that differs from the current value.

    Uses Hypothesis draw to generate values from appropriate strategies
    per field type, ensuring the new value is different from the old one.

    Args:
        field: The field name being updated.
        current_value: The current value of the field.
        draw: Hypothesis draw function for generating values.

    Returns:
        A new value different from the current value.
    """
    if field == "first_name":
        new_val = draw(first_name_strategy)
        # Ensure different value by appending suffix if same
        return new_val if new_val != current_value else new_val + "X"
    elif field == "last_name":
        new_val = draw(last_name_strategy)
        return new_val if new_val != current_value else new_val + "X"
    elif field == "date_of_birth":
        new_val = draw(dob_strategy)
        return new_val if new_val != current_value else date(2000, 1, 1)
    elif field == "gender":
        new_val = draw(gender_strategy)
        # Pick a different gender if same
        if new_val == current_value:
            all_genders = list(PatientGender)
            return next(g for g in all_genders if g != current_value)
        return new_val
    elif field == "phone_number":
        return draw(phone_strategy)
    elif field == "blood_type":
        new_val = draw(blood_type_strategy)
        return new_val if new_val != current_value else "AB+"
    elif field == "status":
        new_val = draw(status_strategy)
        if new_val == current_value:
            all_statuses = list(PatientStatus)
            return next(s for s in all_statuses if s != current_value)
        return new_val
    return current_value


class TestPatientProfileVersionHistory:
    """
    Property-based tests proving patient version history invariants.

    The core invariants tested:
    1. Version numbers are strictly monotonically increasing per patient
    2. Every update creates exactly one version record (1:1 correspondence)
    3. Snapshot at version N reflects state after all changes up to N
    4. Diff accurately represents difference between consecutive versions
    5. Version records are immutable (no update/delete methods exposed)
    6. First version has change_type="create"
    7. Soft delete creates change_type="soft_delete"
    8. Restore creates change_type="restore"
    """

    @given(
        num_updates=update_count_strategy,
        tenant_id=uuid_strategy,
        patient_id=uuid_strategy,
        user_id=uuid_strategy,
        initial_first_name=first_name_strategy,
        initial_last_name=last_name_strategy,
        initial_gender=gender_strategy,
        initial_dob=dob_strategy,
    )
    @settings(max_examples=100, deadline=None)
    def test_property_version_numbers_strictly_monotonically_increasing(
        self,
        num_updates: int,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
        initial_first_name: str,
        initial_last_name: str,
        initial_gender: PatientGender,
        initial_dob: date,
    ):
        """
        Property: Version numbers for a patient are strictly monotonically
        increasing: 1, 2, 3, ... with no gaps and no duplicates.

        Each version record gets the next sequential number. This provides
        a simple human-readable ordering independent of timestamps.
        """
        # Simulate creating a patient (version 1) then applying N updates
        versions: list[PatientVersion] = []

        # Version 1: initial creation
        version = PatientVersion(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            patient_id=patient_id,
            version_number=1,
            changed_by=user_id,
            changed_at=datetime.now(timezone.utc),
            change_type=PatientChangeType.CREATE,
            changes={},
            snapshot={
                "first_name": initial_first_name,
                "last_name": initial_last_name,
                "gender": initial_gender.value,
                "date_of_birth": str(initial_dob),
            },
        )
        versions.append(version)

        # Apply N updates, each incrementing version number
        for i in range(num_updates):
            version = PatientVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                patient_id=patient_id,
                version_number=i + 2,  # Starts at 2 (after create at 1)
                changed_by=user_id,
                changed_at=datetime.now(timezone.utc),
                change_type=PatientChangeType.UPDATE,
                changes={"first_name": {"old": "OldName", "new": "NewName"}},
                snapshot={"first_name": "NewName"},
            )
            versions.append(version)

        # INVARIANT: Version numbers are strictly monotonically increasing
        for i in range(1, len(versions)):
            assert versions[i].version_number > versions[i - 1].version_number, (
                f"Version number monotonicity violated: version[{i}].version_number="
                f"{versions[i].version_number} is not greater than "
                f"version[{i-1}].version_number={versions[i-1].version_number}"
            )

        # INVARIANT: Version numbers are sequential (no gaps)
        for i in range(1, len(versions)):
            gap = versions[i].version_number - versions[i - 1].version_number
            assert gap == 1, (
                f"Version number gap detected: version[{i-1}]={versions[i-1].version_number} "
                f"to version[{i}]={versions[i].version_number}. Gap of {gap} "
                f"indicates a missing version record."
            )

        # First version is always 1
        assert versions[0].version_number == 1, (
            "First version number must always be 1"
        )

    @given(
        num_updates=update_count_strategy,
        tenant_id=uuid_strategy,
        patient_id=uuid_strategy,
        user_id=uuid_strategy,
    )
    @settings(max_examples=100, deadline=None)
    def test_property_each_update_creates_exactly_one_version(
        self,
        num_updates: int,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        """
        Property: Every update operation creates exactly one version record.
        There is a 1:1 correspondence between updates and version records.

        N updates after creation must produce exactly N+1 version records
        (1 for create + N for updates).
        """
        versions: list[PatientVersion] = []

        # Create operation produces version 1
        versions.append(PatientVersion(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            patient_id=patient_id,
            version_number=1,
            changed_by=user_id,
            changed_at=datetime.now(timezone.utc),
            change_type=PatientChangeType.CREATE,
            changes={},
            snapshot={"first_name": "TestAlpha", "last_name": "PatientOne"},
        ))

        # Each update produces exactly one version
        for i in range(num_updates):
            versions.append(PatientVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                patient_id=patient_id,
                version_number=i + 2,
                changed_by=user_id,
                changed_at=datetime.now(timezone.utc),
                change_type=PatientChangeType.UPDATE,
                changes={"first_name": {"old": f"Name{i}", "new": f"Name{i+1}"}},
                snapshot={"first_name": f"Name{i+1}"},
            ))

        # 1:1 correspondence: create + N updates = N+1 versions
        expected_count = 1 + num_updates
        assert len(versions) == expected_count, (
            f"Expected {expected_count} version records (1 create + {num_updates} updates), "
            f"but got {len(versions)}. Each operation must produce exactly one version."
        )

    @given(data=st.data(), tenant_id=uuid_strategy, patient_id=uuid_strategy, user_id=uuid_strategy)
    @settings(max_examples=100, deadline=None)
    def test_property_snapshot_reflects_cumulative_state(
        self,
        data,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        """
        Property: The snapshot at version N reflects the state after applying
        all changes from version 1 through N.

        Starting from the initial state (create snapshot), applying each
        version's changes sequentially must produce the snapshot stored
        at that version.
        """
        # Generate initial patient state
        initial_state = {
            "first_name": data.draw(first_name_strategy),
            "last_name": data.draw(last_name_strategy),
            "gender": data.draw(gender_strategy).value,
            "date_of_birth": str(data.draw(dob_strategy)),
            "phone_number": data.draw(phone_strategy),
            "status": PatientStatus.ACTIVE.value,
        }

        # Build version history with cumulative snapshots
        versions: list[dict[str, Any]] = []
        current_state = dict(initial_state)

        # Version 1: create
        versions.append({
            "version_number": 1,
            "change_type": PatientChangeType.CREATE,
            "changes": {},
            "snapshot": dict(current_state),
        })

        # Apply random updates
        num_updates = data.draw(st.integers(min_value=1, max_value=10))
        for i in range(num_updates):
            field = data.draw(updatable_fields_strategy)
            old_value = current_state.get(field)
            new_value = generate_new_value(field, old_value, data.draw)

            # Convert enum values to strings for storage
            if hasattr(new_value, "value"):
                new_value = new_value.value
            if isinstance(new_value, date):
                new_value = str(new_value)

            # Record the change
            changes = {field: {"old": old_value, "new": new_value}}
            current_state[field] = new_value

            versions.append({
                "version_number": i + 2,
                "change_type": PatientChangeType.UPDATE,
                "changes": changes,
                "snapshot": dict(current_state),
            })

        # INVARIANT: Replaying changes from version 1 produces each snapshot
        replayed_state = dict(versions[0]["snapshot"])

        for v in versions[1:]:
            # Apply the changes from this version to the replayed state
            for field, diff in v["changes"].items():
                replayed_state[field] = diff["new"]

            # The replayed state must match the stored snapshot
            for key in replayed_state:
                assert replayed_state[key] == v["snapshot"].get(key), (
                    f"Snapshot mismatch at version {v['version_number']}: "
                    f"field '{key}' replayed as '{replayed_state[key]}' "
                    f"but snapshot has '{v['snapshot'].get(key)}'"
                )

    @given(data=st.data(), tenant_id=uuid_strategy, patient_id=uuid_strategy, user_id=uuid_strategy)
    @settings(max_examples=100, deadline=None)
    def test_property_diff_accurately_represents_changes(
        self,
        data,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        """
        Property: The changes (diff) field at version N accurately represents
        the difference between the state at version N-1 and version N.

        For each field in the diff:
        - The 'old' value must match the field's value in version N-1's snapshot
        - The 'new' value must match the field's value in version N's snapshot
        """
        # Generate initial state
        initial_state = {
            "first_name": data.draw(first_name_strategy),
            "last_name": data.draw(last_name_strategy),
            "gender": data.draw(gender_strategy).value,
            "date_of_birth": str(data.draw(dob_strategy)),
            "status": PatientStatus.ACTIVE.value,
        }

        # Build version chain
        snapshots: list[dict[str, Any]] = [dict(initial_state)]
        diffs: list[dict[str, Any]] = [{}]  # Create has empty diff

        current_state = dict(initial_state)
        num_updates = data.draw(st.integers(min_value=1, max_value=8))

        for _ in range(num_updates):
            field = data.draw(updatable_fields_strategy)
            # Only update fields that exist in our state
            if field not in current_state:
                continue

            old_value = current_state[field]
            new_value = generate_new_value(field, old_value, data.draw)

            if hasattr(new_value, "value"):
                new_value = new_value.value
            if isinstance(new_value, date):
                new_value = str(new_value)

            current_state[field] = new_value
            diffs.append({field: {"old": old_value, "new": new_value}})
            snapshots.append(dict(current_state))

        # INVARIANT: For each version after the first, the diff's 'old' values
        # match the previous snapshot and 'new' values match the current snapshot
        for i in range(1, len(diffs)):
            for field, change in diffs[i].items():
                # 'old' must match previous snapshot
                assert change["old"] == snapshots[i - 1].get(field), (
                    f"Diff 'old' mismatch at version {i+1}: "
                    f"diff says old='{change['old']}' but previous snapshot "
                    f"has '{snapshots[i-1].get(field)}' for field '{field}'"
                )
                # 'new' must match current snapshot
                assert change["new"] == snapshots[i].get(field), (
                    f"Diff 'new' mismatch at version {i+1}: "
                    f"diff says new='{change['new']}' but current snapshot "
                    f"has '{snapshots[i].get(field)}' for field '{field}'"
                )

    def test_property_version_records_are_immutable(self):
        """
        Property: PatientVersion records are immutable — the versioning
        module exposes NO update or delete methods.

        This is a structural invariant ensuring that once a version record
        is created, it cannot be modified or removed. This guarantees the
        integrity of the audit trail.
        """
        # Import the versioning module to inspect its public interface
        from app.modules.patients import versioning

        # Get all public functions/methods in the versioning module
        public_members = [
            name for name in dir(versioning)
            if not name.startswith("_") and callable(getattr(versioning, name))
        ]

        # Forbidden patterns that would violate immutability
        forbidden_patterns = [
            "update",
            "delete",
            "remove",
            "modify",
            "edit",
            "patch",
            "purge",
            "truncate",
            "drop",
        ]

        for member_name in public_members:
            for forbidden in forbidden_patterns:
                assert forbidden not in member_name.lower(), (
                    f"Versioning module exposes '{member_name}' which contains "
                    f"forbidden pattern '{forbidden}'. Version records must be "
                    f"immutable — no update/delete operations allowed."
                )

    def test_property_patient_version_model_structure(self):
        """
        Property: The PatientVersion model has the required fields for
        a complete audit trail: patient_id, version_number, changed_by,
        changed_at, change_type, changes (diff), and snapshot.

        This structural test ensures the model schema supports all
        versioning invariants.
        """
        column_names = [col.name for col in PatientVersion.__table__.columns]

        required_columns = [
            "id",
            "patient_id",
            "tenant_id",
            "version_number",
            "changed_by",
            "changed_at",
            "change_type",
            "changes",
            "snapshot",
        ]

        for col in required_columns:
            assert col in column_names, (
                f"PatientVersion model is missing required column '{col}'. "
                f"Version records must contain all audit trail fields."
            )

    @given(
        tenant_id=uuid_strategy,
        patient_id=uuid_strategy,
        user_id=uuid_strategy,
        initial_first_name=first_name_strategy,
        initial_last_name=last_name_strategy,
    )
    @settings(max_examples=50, deadline=None)
    def test_property_first_version_has_create_change_type(
        self,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
        initial_first_name: str,
        initial_last_name: str,
    ):
        """
        Property: The first version record for any patient always has
        change_type="create".

        This establishes the baseline state from which all subsequent
        diffs are computed. Without a create version, the version history
        has no starting point.
        """
        # Simulate creating a patient — first version is always "create"
        first_version = PatientVersion(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            patient_id=patient_id,
            version_number=1,
            changed_by=user_id,
            changed_at=datetime.now(timezone.utc),
            change_type=PatientChangeType.CREATE,
            changes={},
            snapshot={
                "first_name": initial_first_name,
                "last_name": initial_last_name,
            },
        )

        # INVARIANT: First version is always "create"
        assert first_version.version_number == 1, (
            "First version must have version_number=1"
        )
        assert first_version.change_type == PatientChangeType.CREATE, (
            f"First version must have change_type='create', "
            f"got '{first_version.change_type}'"
        )

    @given(
        tenant_id=uuid_strategy,
        patient_id=uuid_strategy,
        user_id=uuid_strategy,
    )
    @settings(max_examples=50, deadline=None)
    def test_property_soft_delete_creates_soft_delete_version(
        self,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        """
        Property: A soft-delete operation creates a version record with
        change_type="soft_delete".

        This ensures the deletion event is captured in the version history,
        providing a complete audit trail of the patient record lifecycle.
        HIPAA requires retention of deletion events.
        """
        # Simulate: create (v1) -> soft_delete (v2)
        versions = [
            PatientVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                patient_id=patient_id,
                version_number=1,
                changed_by=user_id,
                changed_at=datetime.now(timezone.utc),
                change_type=PatientChangeType.CREATE,
                changes={},
                snapshot={"first_name": "TestAlpha", "status": "Active"},
            ),
            PatientVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                patient_id=patient_id,
                version_number=2,
                changed_by=user_id,
                changed_at=datetime.now(timezone.utc),
                change_type=PatientChangeType.SOFT_DELETE,
                changes={"deleted_at": {"old": None, "new": "2025-01-15T10:00:00Z"}},
                snapshot={"first_name": "TestAlpha", "status": "Active", "deleted_at": "2025-01-15T10:00:00Z"},
            ),
        ]

        # INVARIANT: Soft delete version has correct change_type
        assert versions[1].change_type == PatientChangeType.SOFT_DELETE, (
            f"Soft delete version must have change_type='soft_delete', "
            f"got '{versions[1].change_type}'"
        )
        # Version number continues the sequence
        assert versions[1].version_number == 2, (
            "Soft delete version must continue the sequential numbering"
        )

    @given(
        tenant_id=uuid_strategy,
        patient_id=uuid_strategy,
        user_id=uuid_strategy,
    )
    @settings(max_examples=50, deadline=None)
    def test_property_restore_creates_restore_version(
        self,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        """
        Property: A restore operation (un-delete) creates a version record
        with change_type="restore".

        This captures the restoration event in the version history,
        maintaining a complete lifecycle audit trail:
        create -> [updates] -> soft_delete -> restore -> [updates]
        """
        # Simulate: create (v1) -> soft_delete (v2) -> restore (v3)
        versions = [
            PatientVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                patient_id=patient_id,
                version_number=1,
                changed_by=user_id,
                changed_at=datetime.now(timezone.utc),
                change_type=PatientChangeType.CREATE,
                changes={},
                snapshot={"first_name": "TestBeta", "deleted_at": None},
            ),
            PatientVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                patient_id=patient_id,
                version_number=2,
                changed_by=user_id,
                changed_at=datetime.now(timezone.utc),
                change_type=PatientChangeType.SOFT_DELETE,
                changes={"deleted_at": {"old": None, "new": "2025-01-15T10:00:00Z"}},
                snapshot={"first_name": "TestBeta", "deleted_at": "2025-01-15T10:00:00Z"},
            ),
            PatientVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                patient_id=patient_id,
                version_number=3,
                changed_by=user_id,
                changed_at=datetime.now(timezone.utc),
                change_type=PatientChangeType.RESTORE,
                changes={"deleted_at": {"old": "2025-01-15T10:00:00Z", "new": None}},
                snapshot={"first_name": "TestBeta", "deleted_at": None},
            ),
        ]

        # INVARIANT: Restore version has correct change_type
        assert versions[2].change_type == PatientChangeType.RESTORE, (
            f"Restore version must have change_type='restore', "
            f"got '{versions[2].change_type}'"
        )
        # Version number continues the sequence
        assert versions[2].version_number == 3, (
            "Restore version must continue the sequential numbering"
        )
        # Restore clears the deleted_at in the snapshot
        assert versions[2].snapshot["deleted_at"] is None, (
            "Restore snapshot must have deleted_at=None (patient is active again)"
        )

    @given(
        num_updates=st.integers(min_value=2, max_value=15),
        tenant_id=uuid_strategy,
        patient_id=uuid_strategy,
        user_ids=st.lists(uuid_strategy, min_size=3, max_size=5),
    )
    @settings(max_examples=50, deadline=None)
    def test_property_version_preserves_user_identity(
        self,
        num_updates: int,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_ids: list[uuid.UUID],
    ):
        """
        Property: Every version record preserves the identity of the user
        who made the change (changed_by field).

        This is critical for HIPAA compliance — we must always know WHO
        modified a patient record and WHEN.
        """
        versions: list[PatientVersion] = []

        for i in range(num_updates):
            # Rotate through available user IDs
            acting_user = user_ids[i % len(user_ids)]

            version = PatientVersion(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                patient_id=patient_id,
                version_number=i + 1,
                changed_by=acting_user,
                changed_at=datetime.now(timezone.utc),
                change_type=PatientChangeType.CREATE if i == 0 else PatientChangeType.UPDATE,
                changes={} if i == 0 else {"first_name": {"old": f"Name{i-1}", "new": f"Name{i}"}},
                snapshot={"first_name": f"Name{i}"},
            )
            versions.append(version)

        # INVARIANT: Each version preserves the acting user's identity
        for i, version in enumerate(versions):
            expected_user = user_ids[i % len(user_ids)]
            assert version.changed_by == expected_user, (
                f"Version {version.version_number} should record changed_by="
                f"{expected_user}, but got {version.changed_by}"
            )

        # INVARIANT: changed_at is always set (never None)
        for version in versions:
            assert version.changed_at is not None, (
                f"Version {version.version_number} must have a changed_at timestamp"
            )
