"""
Registration Module — Custom Exceptions
=========================================
Domain-specific exceptions for the registration module.
HTTP layer maps these to appropriate status codes.
"""


class RegistrationNotFoundError(Exception):
    """Raised when a patient record does not exist in the tenant scope."""

    def __init__(self, patient_id: str) -> None:
        """Initialise with the patient UUID (never include PHI)."""
        super().__init__(f"Patient not found: {patient_id}")
        self.patient_id = patient_id


class RegistrationIncompleteError(Exception):
    """Raised when completing registration but required fields are missing."""

    def __init__(self, missing_fields: list[str]) -> None:
        """Initialise with list of missing field names (no PHI values)."""
        super().__init__(f"Registration incomplete. Missing fields: {missing_fields}")
        self.missing_fields = missing_fields


class ConsentNotFoundError(Exception):
    """Raised when a consent record cannot be located."""

    def __init__(self, consent_id: str) -> None:
        """Initialise with the consent UUID (never include PHI)."""
        super().__init__(f"Consent record not found: {consent_id}")
        self.consent_id = consent_id


class ConsentAlreadyRevokedError(Exception):
    """Raised when attempting to revoke an already-revoked consent."""

    def __init__(self, consent_id: str) -> None:
        """Initialise with the consent UUID."""
        super().__init__(f"Consent {consent_id} has already been revoked.")
        self.consent_id = consent_id
