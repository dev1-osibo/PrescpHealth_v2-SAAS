"""
PrescpHealth Backend — Risk Engine Custom Exceptions.

Domain-specific exceptions for the risk engine module.
Allow callers to distinguish different failure modes without parsing error strings.

Design:
    - Inherit from base Exception
    - Each exception represents a specific error condition
    - Include error code and context for logging/troubleshooting
    - Never expose internal details to API clients (use FastAPI error handlers)

HIPAA:
    Exception messages must not contain PHI.
    Log errors with only opaque IDs (patient_id UUID, not names/scores).
"""


class RiskEngineError(Exception):
    """
    Base exception for risk engine errors.

    All risk engine exceptions inherit from this for easy catching.
    """

    def __init__(self, code: str, message: str, context: dict | None = None):
        """
        Initialize exception with code, message, and optional context.

        Args:
            code: Machine-readable error code (e.g., "insufficient_data")
            message: Human-readable error message (no PHI)
            context: Optional dict with additional context for logging
        """
        self.code = code
        self.message = message
        self.context = context or {}
        super().__init__(self.message)


class InsufficientDataError(RiskEngineError):
    """
    Raised when a patient lacks sufficient measurement data for risk computation.

    Triggered when:
    - Patient has no validated measurements at all
    - Patient has data for <3 diseases (can't compute meaningful scores)
    - Measurement data is stale (>90 days old)

    Handled by:
    - Risk service returns "insufficient data" message to UI
    - UI prompts clinician to enter more measurements before retrying
    """

    def __init__(self, patient_id: str, reason: str):
        super().__init__(
            code="insufficient_data",
            message=f"Patient has insufficient data for risk computation: {reason}",
            context={"patient_id": patient_id, "reason": reason},
        )


class MLEngineError(RiskEngineError):
    """
    Raised when the ML pipeline fails (model not found, inference error, etc.).

    Triggered by:
    - Model artifact not found at artifact_path (S3 error, missing file)
    - Model inference timeout (>30 seconds)
    - OOM or GPU failure during model loading
    - Input feature shape mismatch (wrong number of features)

    Handled by:
    - Celery task retries up to 3 times with exponential backoff
    - After 3 failures, computation marked as failed in DB
    - Clinician sees "computation failed, please retry" message
    """

    def __init__(self, model_version: str, error_detail: str):
        super().__init__(
            code="ml_engine_error",
            message=f"ML engine failed for model {model_version}: {error_detail}",
            context={"model_version": model_version, "error_detail": error_detail},
        )


class ModelVersionNotFoundError(RiskEngineError):
    """
    Raised when a model version doesn't exist in the registry.

    Triggered by:
    - Requesting computation with a retired model version
    - Trying to rollback to a model version that was never deployed
    - Database record deleted but code still references it

    Handled by:
    - Fall back to latest active model version
    - Log warning with model_version attempted, model_version used
    """

    def __init__(self, disease: str, version: str):
        super().__init__(
            code="model_version_not_found",
            message=f"Model version {disease}:{version} not found in registry",
            context={"disease": disease, "version": version},
        )


class DataSufficiencyCheckError(RiskEngineError):
    """
    Raised when data sufficiency check itself fails (not about insufficient data).

    Triggered by:
    - Database query error when fetching measurements
    - Corrupted measurement records
    - Missing foreign key references

    Handled by:
    - Celery task retries
    - User sees "computation failed, please try again" message
    """

    def __init__(self, patient_id: str, reason: str):
        super().__init__(
            code="data_sufficiency_check_error",
            message=f"Error checking data sufficiency for patient: {reason}",
            context={"patient_id": patient_id, "reason": reason},
        )


class ComputationTimeoutError(RiskEngineError):
    """
    Raised when risk computation exceeds time limit.

    Triggered by:
    - Celery task runs >30 seconds
    - Network I/O blocked (S3, Redis, DB)
    - Hung process or deadlock

    Handled by:
    - Celery automatically kills task after time_limit
    - Task marked as failed
    - Celery retry happens automatically (up to 3 times)
    """

    def __init__(self, computation_id: str, elapsed_seconds: float):
        super().__init__(
            code="computation_timeout",
            message=f"Risk computation timed out after {elapsed_seconds:.1f} seconds",
            context={"computation_id": computation_id, "elapsed_seconds": elapsed_seconds},
        )
