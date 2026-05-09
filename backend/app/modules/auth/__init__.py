"""
PrescpHealth Backend — Authentication Module.

Handles all authentication and session management:
- User registration and credential storage
- JWT access token issuance (15-minute expiry)
- Refresh token rotation with reuse detection
- MFA (TOTP-based) for clinician roles
- Account lockout after failed attempts
- RBAC role hierarchy and permission enforcement

Security Architecture:
- Passwords hashed with bcrypt (cost 12)
- JWT signed with HS256 (symmetric — single service)
- Refresh tokens rotated on every use (detect reuse = revoke family)
- Account locked after 5 failed attempts in 10-minute window
- MFA required for all clinician roles (Doctor, Nurse, Clinic_Admin)

HIPAA Compliance:
- Session timeout: 30 minutes of inactivity
- Access tokens short-lived (15 min) to limit exposure window
- All auth events logged to audit trail (login, logout, MFA, lockout)
- No PHI in JWT claims (only user_id, tenant_id, role)
"""

from app.modules.auth.models import User, RefreshToken, MFAConfig

__all__ = ["User", "RefreshToken", "MFAConfig"]
