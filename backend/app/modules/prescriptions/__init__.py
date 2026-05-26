"""
PrescpHealth Backend — Prescriptions Module.

Manages medication prescriptions including writing, tracking, refilling,
and discontinuation. Integrates with the Drug Interaction engine to check
for drug-drug and drug-health interactions before confirming prescriptions.

Module Structure:
    - enums.py: PrescriptionStatus enum
    - prescription_model.py: Prescription SQLAlchemy model
    - dispensing_model.py: Dispensing SQLAlchemy model
    - models.py: Re-export hub for all models and enums
    - service.py: PrescriptionService (business logic orchestration)
    - service_refill.py: Refill processing logic
    - fhir_mapper.py: FHIR R4 MedicationRequest mapping
    - schemas.py: Pydantic request/response schemas
    - router.py: FastAPI endpoints

Dependencies:
    - app.core.base_model (Base, TenantMixin)
    - app.modules.patients (Patient FK)
    - app.modules.encounters (Encounter FK)
    - app.modules.code_catalogs (ATC code validation)
    - app.modules.drug_interactions (DDI/DHI checks)

HIPAA:
    - Drug names, dosages, and frequencies are PHI
    - All access logged via AuditService
    - RLS enforces tenant isolation at database level
"""
