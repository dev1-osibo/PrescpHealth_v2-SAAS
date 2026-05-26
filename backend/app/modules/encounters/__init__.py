"""
PrescpHealth Backend — Encounters Module.

This module manages patient visits (encounters) including:
- Encounter lifecycle (check-in → in-progress → completed/cancelled)
- SOAP notes (Subjective, Objective, Assessment, Plan)
- Coded diagnoses (ICD-10 validated)
- Clinical procedures (SNOMED CT coded)
- Discharge summaries

Module Structure:
- enums.py — EncounterStatus, EncounterClass
- encounter_model.py — Encounter class
- soap_note_model.py — SOAPNote class
- diagnosis_model.py — Diagnosis class
- procedure_model.py — Procedure class
- models.py — Re-export hub for all models and enums

HIPAA: All clinical data in this module is PHI. SOAP notes,
diagnoses, and procedures must be encrypted at rest and never logged.

RLS: All tables use tenant_id with Row-Level Security policies.
"""
