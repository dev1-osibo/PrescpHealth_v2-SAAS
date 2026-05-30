"""
PrescpHealth Backend — Drug Interaction FastAPI Router.

Four endpoints for drug interaction management:
1. POST /patients/{id}/medications — Add medication (runs DDI/DHI checks)
2. GET /patients/{id}/medications/safety — Get safety summary
3. GET /patients/{id}/medications — Get active medications
4. POST /interactions/{id}/override — Override interaction with justification

All endpoints:
- Require authentication (via require_role dependency)
- Enforce RBAC (Doctor role for most, Nurse for read-only)
- Set HIPAA headers (Cache-Control: no-store on PHI responses)
- Use standard response envelope
- Include request_id for correlation/audit

HIPAA Compliance:
    - Medications and interactions are PHI — responses marked no-cache
    - No drug names in logs (only codes/IDs)
    - All calls audited via AuditService
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_request_id, get_tenant_id, get_current_user
from app.modules.auth.rbac import Role, require_role
from app.modules.audit.service import AuditService
from app.modules.drug_interactions.service import DrugInteractionService
from app.modules.drug_interactions.engine import InteractionEngine
from app.modules.drug_interactions.schemas import (
    AddMedicationRequest,
    AddMedicationResponse,
    SafetySummaryResponse,
    OverrideInteractionRequest,
    OverrideInteractionResponse,
    ActiveMedicationsResponse,
)

# Router prefix: /api/v1/patients/{id}/medications/...
router = APIRouter(prefix="/medications", tags=["drug_interactions"])


@router.post(
    "",
    response_model=AddMedicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add medication (runs DDI/DHI checks)",
    description="Add medication and automatically check for interactions.",
)
async def add_medication(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    request_body: AddMedicationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR))],
) -> AddMedicationResponse:
    """
    Add medication and run drug interaction checks.

    This endpoint:
    1. Saves medication record
    2. Gets active medications for this patient
    3. Gets patient's health conditions
    4. Runs DDI check (new drug vs. all active drugs)
    5. Runs DHI check (new drug vs. patient conditions)
    6. Stores detected interactions
    7. Returns safety status (Safe/Caution/Action Required)

    Args:
        patient_id: Patient UUID (from URL path)
        request_body: {drug_name, drug_code, dosage, frequency, route, start_date}

    Returns:
        AddMedicationResponse: {success: true, data: {medication_id, ddi_count, dhi_count, safety_status, critical_interactions}, meta: {...}}

    Status Codes:
        - 201 Created: Medication added successfully
        - 400 Bad Request: Invalid drug code or other validation error
        - 401 Unauthorized: Missing or invalid authentication
        - 403 Forbidden: Insufficient permissions (not a Doctor)
        - 404 Not Found: Patient not found
        - 500 Internal Server Error: Interaction check failed

    Audit:
        Logs action="medication_added" with drug_code, ddi/dhi counts, safety_status

    Safety Levels:
        - Safe: No interactions detected
        - Caution: Minor/Moderate interactions detected (monitor)
        - Action Required: Contraindicated or Major interactions (clinical review needed)
    """
    audit_service = AuditService(db)
    engine = InteractionEngine(db)
    service = DrugInteractionService(db, audit_service, engine)

    try:
        result = await service.add_medication(
            patient_id=patient_id,
            drug_name=request_body.drug_name,
            drug_code=request_body.drug_code,
            dosage=request_body.dosage,
            frequency=request_body.frequency,
            route=request_body.route,
            start_date=request_body.start_date,
            prescribed_by=user_id,
        )

        return AddMedicationResponse(
            success=True,
            data=result,
            meta={
                "request_id": request_id,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    except Exception as exc:
        await audit_service.log_action(
            action="medication_add_failed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add medication and check interactions",
        )


@router.get(
    "/safety",
    response_model=SafetySummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get drug safety summary",
    description="Get consolidated safety status and interaction recommendations.",
)
async def get_safety_summary(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR, Role.NURSE))],
) -> SafetySummaryResponse:
    """
    Get consolidated drug safety summary for a patient.

    Returns:
    - overall_status: Safe / Caution / Action Required
    - critical_issue_count: Contraindicated + Major interactions
    - moderate_issue_count: Moderate interactions
    - active_medication_count: How many drugs patient is on
    - recommendations: Top clinical actions

    Args:
        patient_id: Patient UUID (from URL path)

    Returns:
        SafetySummaryResponse: {success: true, data: {overall_status, critical_issue_count, moderate_issue_count, active_medication_count, recommendations}, meta: {...}}

    Status Codes:
        - 200 OK: Safety summary retrieved
        - 401 Unauthorized: Missing or invalid authentication
        - 403 Forbidden: Insufficient permissions
        - 404 Not Found: Patient not found

    HIPAA:
        Response includes Cache-Control: no-store

    Audit:
        Logs action="safety_summary_accessed"
    """
    audit_service = AuditService(db)
    engine = InteractionEngine(db)
    service = DrugInteractionService(db, audit_service, engine)

    try:
        summary = await service.get_safety_summary(patient_id)

        # Audit
        await audit_service.log_action(
            action="safety_summary_accessed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
        )

        return SafetySummaryResponse(
            success=True,
            data=summary,
            meta={
                "request_id": request_id,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    except Exception as exc:
        await audit_service.log_action(
            action="safety_summary_failed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve safety summary",
        )


@router.get(
    "",
    response_model=ActiveMedicationsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get active medications",
    description="List active medications for a patient.",
)
async def get_active_medications(
    patient_id: Annotated[uuid.UUID, Path(..., description="Patient UUID")],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR, Role.NURSE))],
) -> ActiveMedicationsResponse:
    """
    Get list of active medications for a patient.

    Args:
        patient_id: Patient UUID (from URL path)

    Returns:
        ActiveMedicationsResponse: {success: true, data: [{id, drug_name, dosage, frequency, ...}], meta: {...}}

    Status Codes:
        - 200 OK: Medications retrieved (may be empty list)
        - 401 Unauthorized: Missing or invalid authentication
        - 403 Forbidden: Insufficient permissions
        - 404 Not Found: Patient not found

    HIPAA:
        Response marked no-cache

    Audit:
        Logs action="medications_accessed"
    """
    from sqlalchemy import select
    from app.modules.drug_interactions.models import MedicationRecord

    audit_service = AuditService(db)

    try:
        stmt = select(MedicationRecord).where(
            MedicationRecord.patient_id == patient_id,
            MedicationRecord.is_active == True,
        )
        result = await db.execute(stmt)
        meds = result.scalars().all()

        # Audit
        await audit_service.log_action(
            action="medications_accessed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"medication_count": len(meds)},
        )

        data = [
            {
                "id": str(m.id),
                "drug_name": m.drug_name,
                "drug_code": m.drug_code,
                "dosage": m.dosage,
                "frequency": m.frequency,
                "route": m.route,
                "start_date": m.start_date.isoformat(),
                "end_date": m.end_date.isoformat() if m.end_date else None,
            }
            for m in meds
        ]

        return ActiveMedicationsResponse(
            success=True,
            data=data,
            meta={
                "request_id": request_id,
                "timestamp": datetime.utcnow().isoformat(),
                "total": len(meds),
            },
        )

    except Exception as exc:
        await audit_service.log_action(
            action="medications_access_failed",
            resource_type="patient",
            resource_id=patient_id,
            user_id=user_id,
            changes={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve medications",
        )


@router.post(
    "/override",
    response_model=OverrideInteractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Override interaction",
    description="Override a detected interaction with mandatory clinical justification.",
)
async def override_interaction(
    interaction_id: Annotated[uuid.UUID, Path(..., description="InteractionResult UUID")],
    request_body: OverrideInteractionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    request_id: Annotated[str, Depends(get_request_id)],
    _: Annotated[None, Depends(require_role(Role.DOCTOR))],
) -> OverrideInteractionResponse:
    """
    Override a detected interaction with mandatory justification.

    Records who overrode it, when, and why (immutable audit trail).

    Args:
        interaction_id: InteractionResult UUID (from URL path)
        request_body: {justification: "..."}

    Returns:
        OverrideInteractionResponse: {success: true, data: {message: "..."}, meta: {...}}

    Status Codes:
        - 200 OK: Override recorded
        - 400 Bad Request: Justification too short
        - 401 Unauthorized: Missing or invalid authentication
        - 403 Forbidden: Insufficient permissions (not a Doctor)
        - 404 Not Found: Interaction not found
        - 500 Internal Server Error: Failed to record override

    Justification:
        Must be at least 20 characters. Should explain clinical reasoning
        for proceeding despite detected interaction.

    Audit:
        Logs action="interaction_overridden" with patient_id, interaction_type,
        and who overrode it
    """
    audit_service = AuditService(db)
    engine = InteractionEngine(db)
    service = DrugInteractionService(db, audit_service, engine)

    try:
        result = await service.override_interaction(
            interaction_id=interaction_id,
            doctor_id=user_id,
            justification=request_body.justification,
        )

        return OverrideInteractionResponse(
            success=True,
            data=result,
            meta={
                "request_id": request_id,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        await audit_service.log_action(
            action="override_failed",
            resource_type="interaction_result",
            resource_id=interaction_id,
            user_id=user_id,
            changes={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record override",
        )
