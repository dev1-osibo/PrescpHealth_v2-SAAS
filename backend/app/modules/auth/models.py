"""
PrescpHealth Backend — Auth SQLAlchemy Models.

Defines the database models for authentication and session management:
- User: Core user account (credentials, role, tenant, MFA status)
- RefreshToken: Rotatable refresh tokens with family tracking
- MFAConfig: TOTP MFA configuration per user

Schema Design Decisions:
- User.email is unique per tenant (not globally) — allows same email across tenants
- RefreshToken uses token_family for rotation reuse detection
- MFAConfig is separate from User to keep User model focused
- All models use TenantMixin for RLS isolation (except Super_Admin users)

HIPAA Notes:
- Passwords stored as bcrypt hash (never plaintext, never reversible)
- Failed login attempts tracked for lockout (5 in 10 min)
- Last login timestamp for session activity monitoring
- No PHI stored in auth models (user profile is separate from patient data)
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin, TimestampMixin


# ---------------------------------------------------------------------------
# Role Enum — defines the RBAC hierarchy
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    """
    User roles in order of increasing privilege.

    Role hierarchy (higher inherits all lower permissions):
        Patient_User < Nurse < Doctor < Clinic_Admin < Super_Admin

    Per RBAC steering rule:
    - Patient_User: Self-report measurements, view own simplified risk summary
    - Nurse: Submit measurements, view patient data, acknowledge alerts
    - Doctor: Full clinical access, AI assistant, prescribe, override interactions
    - Clinic_Admin: Tenant settings, user management, population analytics
    - Super_Admin: Cross-tenant access, model deployment, system configuration
    """

    PATIENT_USER = "Patient_User"
    NURSE = "Nurse"
    DOCTOR = "Doctor"
    CLINIC_ADMIN = "Clinic_Admin"
    SUPER_ADMIN = "Super_Admin"


# ---------------------------------------------------------------------------
# User Model
# ---------------------------------------------------------------------------
class User(TenantMixin, Base):
    """
    Core user account model.

    Stores authentication credentials and role assignment.
    Does NOT store clinical/patient data — that's in the patients module.

    RLS: Tenant-scoped (users can only see other users in their tenant).
    Exception: Super_Admin can access users across tenants.
    """

    __tablename__ = "users"

    # Primary key — immutable UUID assigned at creation
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique user identifier (immutable)",
    )

    # Authentication fields
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="User email — unique per tenant, used for login",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt hash of password (cost 12, never stored plaintext)",
    )

    # Profile fields (non-PHI — this is staff info, not patient data)
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="User's display name (staff member, not patient)",
    )

    # Role and permissions
    role: Mapped[UserRole] = mapped_column(
        String(50),
        nullable=False,
        default=UserRole.NURSE,
        comment="RBAC role determining access permissions",
    )

    # Account status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether account is active (False = disabled by admin)",
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether account is locked due to failed login attempts",
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="When the account was locked (NULL if not locked)",
    )

    # Login tracking (for security monitoring, not PHI)
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Consecutive failed login attempts (resets on success)",
    )
    last_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp of last failed login attempt",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp of last successful login",
    )

    # MFA status
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether MFA (TOTP) is enabled for this user",
    )

    # Language preference (per i18n steering rule)
    preferred_language: Mapped[str] = mapped_column(
        String(10),
        default="en",
        nullable=False,
        comment="User's preferred language code (en, fr, pt, sw, ar)",
    )

    # Relationships
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    mfa_config: Mapped["MFAConfig | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Constraints
    __table_args__ = (
        # Email unique per tenant (same email can exist in different tenants)
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
    )


# ---------------------------------------------------------------------------
# Refresh Token Model
# ---------------------------------------------------------------------------
class RefreshToken(TimestampMixin, Base):
    """
    Refresh token for session continuity with rotation.

    Token Rotation Security:
    - Each refresh creates a NEW token and invalidates the old one
    - Tokens belong to a 'family' (all tokens from the same login session)
    - If a revoked token is reused, the ENTIRE family is invalidated
      (this detects token theft — attacker uses stolen token after user rotated)

    Lifecycle:
    1. Login → create token with new family_id
    2. Refresh → revoke old token, create new token with SAME family_id
    3. Reuse detected → revoke ALL tokens in that family (security breach)
    4. Logout → revoke the specific token
    5. Expiry → token becomes invalid after 7 days regardless
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # The actual token value (hashed for storage security)
    token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        comment="SHA-256 hash of the refresh token value",
    )

    # Family tracking for rotation reuse detection
    # All tokens from the same login session share a family_id
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Groups tokens from same session — reuse detection key",
    )

    # Token status
    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether this token has been revoked (rotation or logout)",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this token expires (7 days from creation)",
    )

    # Owner
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    # Metadata for security monitoring
    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Browser/client user-agent at token creation (for anomaly detection)",
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        comment="Client IP at token creation (for anomaly detection)",
    )


# ---------------------------------------------------------------------------
# MFA Configuration Model
# ---------------------------------------------------------------------------
class MFAConfig(TimestampMixin, Base):
    """
    TOTP MFA configuration for a user.

    Stores the TOTP secret and backup codes for multi-factor authentication.
    MFA is required for all clinician roles (Doctor, Nurse, Clinic_Admin)
    per HIPAA security requirements.

    The TOTP secret is stored encrypted (application-layer encryption)
    because it's equivalent to a password — if leaked, MFA is bypassed.
    """

    __tablename__ = "mfa_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Encrypted TOTP secret (decrypted only during verification)
    totp_secret_encrypted: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="TOTP secret encrypted with app encryption key (Fernet)",
    )

    # Backup codes (hashed, one-time use)
    # Stored as JSON array of hashed codes
    backup_codes_hash: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
        comment="JSON array of hashed backup codes (one-time use each)",
    )

    # Whether MFA setup is complete (secret generated AND first code verified)
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True only after user verifies first TOTP code (confirms setup)",
    )

    # Owner (one-to-one with User)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    user: Mapped["User"] = relationship(back_populates="mfa_config")
