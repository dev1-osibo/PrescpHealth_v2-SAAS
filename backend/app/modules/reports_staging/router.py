"""
PrescpHealth Backend — Reports FastAPI Router.

Exposes the report generation and CSV export API endpoints with:
  - RBAC enforcement via require_role
  - Cache-Control: no-store on all responses (PHI)
  - Standard response envelope on JSON endpoints
  - StreamingResponse for CSV exports (no body buffering)

All responses set Cache-Control: no-store because report payloads
and CSV exports contain PHI (patient records, clinical measurements).
"""
import uuid
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id
from app.core.audit import AuditService
from app.modules.auth.rbac import Role, require_role
from app.modules.reports_staging.exceptions import ReportError
from app.modules.reports_staging.schemas import ReportRequest, ReferralRequest, ReportTaskResponse
from app.modules.reports_staging.service import ReportService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["reports"])

_NO_STORE = "no-store"
_ESTIMATED_PDF_SECONDS = 10


def _build_service(
    db: AsyncSession,
    current_user: dict,
    request_id: str,
) -> ReportService:
    """Construct ReportService with all required dependencies."""
    tenant_id = uuid.UUID(current_user["tenant_id"])
    user_id = uuid.UUID(current_user["user_id"])
    audit_service = AuditService(db=db, tenant_id=tenant_id)
    return ReportService(
        db=db,
        audit_service=audit_service,
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def _meta(request_id: str) -> dict:
    """Build standard response meta block."""
    return {"request_id": request_id, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post(
    "/api/v1/patients/{patient_id}/reports/clinical",
    response_model=ReportTaskResponse,
    dependencies=[Depends(require_role(Role.DOCTOR))],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request clinical summary PDF generation",
)
async def request_clinical_report(
    patient_id: uuid.UUID,
    body: ReportRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> ReportTaskResponse:
    """
    Enqueue generation of a clinical summary PDF for the specified patient.

    Returns 202 Accepted with a task_id to poll for completion.
    PHI: response contains only UUIDs — Cache-Control: no-store set.

    Args:
        patient_id: Path parameter — UUID of the target patient.
        body: Request body containing optional section overrides.
    """
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_service(db, current_user, request_id)

    try:
        task_id = await svc.request_clinical_report(
            patient_id=patient_id,
            sections=body.include_sections,
        )
        return ReportTaskResponse(
            success=True,
            data={"task_id": task_id, "estimated_seconds": _ESTIMATED_PDF_SECONDS},
            meta=_meta(request_id),
        )
    except ReportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except Exception as exc:
        logger.error(
            "clinical_report_request_error",
            patient_id=str(patient_id),
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue clinical report",
        )


@router.post(
    "/api/v1/patients/{patient_id}/reports/referral",
    response_model=ReportTaskResponse,
    dependencies=[Depends(require_role(Role.DOCTOR))],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request referral letter PDF generation",
)
async def request_referral_report(
    patient_id: uuid.UUID,
    body: ReferralRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> ReportTaskResponse:
    """
    Enqueue generation of a referral letter PDF for the specified patient.

    Returns 202 Accepted with a task_id to poll for completion.

    Args:
        patient_id: Path parameter — UUID of the patient being referred.
        body: Referral details including physician and reason.
    """
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_service(db, current_user, request_id)

    try:
        task_id = await svc.request_referral_report(
            patient_id=patient_id,
            referring_physician=body.referring_physician,
            referral_reason=body.referral_reason,
        )
        return ReportTaskResponse(
            success=True,
            data={"task_id": task_id, "estimated_seconds": _ESTIMATED_PDF_SECONDS},
            meta=_meta(request_id),
        )
    except ReportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except Exception as exc:
        logger.error(
            "referral_report_request_error",
            patient_id=str(patient_id),
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue referral report",
        )


@router.get(
    "/api/v1/patients/{patient_id}/export/measurements",
    dependencies=[Depends(require_role(Role.DOCTOR))],
    summary="Stream patient measurements as CSV",
)
async def export_measurements(
    patient_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> StreamingResponse:
    """
    Stream all measurements for a patient as a downloadable CSV file.

    Rows are flushed to the client incrementally via StreamingResponse;
    large datasets do not buffer in server memory.

    Args:
        patient_id: UUID of the patient whose measurements to export.
    """
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_service(db, current_user, request_id)

    try:
        generator = await svc.stream_measurements_csv(patient_id=patient_id)
        return StreamingResponse(
            content=generator,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="measurements_{patient_id}.csv"',
                "Cache-Control": _NO_STORE,
            },
        )
    except Exception as exc:
        logger.error(
            "measurements_export_error",
            patient_id=str(patient_id),
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stream measurements export",
        )


@router.get(
    "/api/v1/population/export",
    dependencies=[Depends(require_role(Role.CLINIC_ADMIN))],
    summary="Stream population risk snapshot as CSV",
)
async def export_population(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> StreamingResponse:
    """
    Stream the full tenant population risk snapshot as a downloadable CSV file.

    Each row represents one patient's latest risk score entry.
    Restricted to Clinic_Admin and above.

    Returns a streaming CSV with headers: patient_id, disease, score, stratum, computed_at.
    """
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_service(db, current_user, request_id)

    try:
        generator = await svc.stream_population_csv()
        return StreamingResponse(
            content=generator,
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="population_export.csv"',
                "Cache-Control": _NO_STORE,
            },
        )
    except Exception as exc:
        logger.error(
            "population_export_error",
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stream population export",
        )
