"""
PrescpHealth Backend — FHIR OAuth 2.0 Client Credentials (STUB).

Validates the format of OAuth 2.0 Bearer tokens for FHIR API access.
This is a STUB implementation — it does NOT issue real tokens or validate
against a real authorization server.

Production implementation would:
    1. Validate JWT signature against public key from auth server.
    2. Check token scope includes `system/read` or `system/write`.
    3. Extract client_id and map it to a tenant context.

HIPAA:
    Tokens are validated by structure only — never logged or stored.
    Client IDs are UUIDs and are logged (non-PHI).
"""

import re
import uuid
from typing import Optional

import structlog
from fastapi import HTTPException, Request

logger = structlog.get_logger(__name__)

# STUB: Simulated valid client credentials (would come from DB in production)
_STUB_VALID_CLIENTS: set[str] = {
    "00000000-0000-0000-0000-000000000001",  # Test external system client
}

# Bearer token format: "Bearer {base64url.base64url.base64url}" (JWT)
_BEARER_RE = re.compile(r"^Bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+$")


class OAuthTokenInfo:
    """
    Parsed OAuth token context extracted from the Bearer token.

    In production, this would come from JWT claims decoded from the token.
    In the stub, we return a fixed test context.
    """

    def __init__(
        self,
        client_id: str,
        tenant_id: uuid.UUID,
        scopes: list[str],
    ) -> None:
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.scopes = scopes


def validate_oauth_token(authorization_header: Optional[str]) -> OAuthTokenInfo:
    """
    Validate an OAuth 2.0 Bearer token for FHIR API access.

    STUB: Checks that the header is present and matches Bearer JWT format.
    Does NOT validate the signature or claims in production-level depth.

    Args:
        authorization_header: The raw Authorization header value.

    Returns:
        OAuthTokenInfo with client context.

    Raises:
        HTTPException(401): If the token is missing or malformed.
        HTTPException(403): If the client is not authorized (stub only).
    """
    if not authorization_header:
        logger.warning("oauth_missing_authorization_header")
        raise HTTPException(status_code=401, detail="Authorization header required")

    # Validate Bearer JWT format (structural check only)
    if not _BEARER_RE.match(authorization_header):
        logger.warning("oauth_malformed_bearer_token")
        raise HTTPException(status_code=401, detail="Malformed Bearer token")

    # STUB: Extract fake client_id from the static stub list
    # Production: decode JWT, validate signature, extract sub/client_id claim
    stub_client_id = "00000000-0000-0000-0000-000000000001"
    stub_tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000099")

    logger.info("oauth_token_validated_stub", client_id=stub_client_id)

    return OAuthTokenInfo(
        client_id=stub_client_id,
        tenant_id=stub_tenant_id,
        scopes=["system/Encounter.read", "system/Patient.read", "system/write"],
    )


async def get_fhir_auth(request: Request) -> OAuthTokenInfo:
    """
    FastAPI dependency for FHIR OAuth 2.0 authentication.

    Extracts the Authorization header and validates the token.
    Use as a Depends() in FHIR route definitions.

    Args:
        request: FastAPI Request object.

    Returns:
        OAuthTokenInfo with authenticated client context.

    Raises:
        HTTPException(401): If authentication fails.
    """
    auth_header = request.headers.get("Authorization")
    return validate_oauth_token(auth_header)
