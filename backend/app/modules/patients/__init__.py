"""
PrescpHealth Backend — Patient Profile Management Module.

This module handles patient demographic data, medical history, and
version-controlled profile updates. It is the central data hub that
other modules (measurements, risk engine, forecasting, AI assistant)
reference for patient context.

Key Responsibilities:
- Patient CRUD with soft-delete (HIPAA: never hard-delete patient data)
- Version history for all profile changes (audit trail)
- Search by name, risk level, disease flag, age range, biological sex
- Timeline aggregation (measurements, risk scores, alerts, AI interactions)

PHI Warning:
    This module stores Protected Health Information (PHI). All fields
    containing PHI are clearly marked in model comments. PHI must:
    - Never be logged (only log patient_id UUID)
    - Never be cached in browser-accessible storage
    - Be encrypted at rest (column-level or TDE)
    - Be soft-deleted only (7-year HIPAA retention minimum)

Dependencies:
    - app.core.base_model (Base, TenantMixin, SoftDeleteMixin)
    - app.modules.auth.models (User — for created_by, changed_by FKs)
"""

from app.modules.patients.models import Patient, PatientVersion
from app.modules.patients.service import PatientService

__all__ = ["Patient", "PatientVersion", "PatientService"]
