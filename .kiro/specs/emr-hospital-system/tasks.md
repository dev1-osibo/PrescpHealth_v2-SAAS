# Implementation Plan: EMR Hospital System

## Overview

This plan breaks the EMR Hospital System into three deployment layers following the design's layered architecture. Layer 1 (Core Clinical Workflow) ships first with encounters, prescriptions, and lab orders. Layer 2 (Operational Features) adds appointments, referrals, documents, and registration. Layer 3 (Advanced Operations) adds billing, bed management, FHIR API, and external integrations. Each module follows the established FastAPI + SQLAlchemy async + PostgreSQL RLS pattern under `backend/app/modules/`. All code uses Python with heavy commenting and extreme modularity per project conventions.

## Tasks

- [ ] 1. Code catalogs and shared reference data
  - [x] 1.1 Create code catalog model and Alembic migration
    - Create `backend/app/modules/code_catalogs/models.py` with `CodeCatalog` model
    - Generate Alembic migration for `code_catalogs` table (shared, NOT tenant-scoped)
    - Add unique constraint `(catalog_type, code)` and GIN trigram index on `display_name_en`
    - _Requirements: 1.3, 2.2, 3.2, 4.6_

  - [~] 1.2 Implement code catalog service and validation helpers
    - Create `backend/app/modules/code_catalogs/service.py` with `CodeCatalogService`
    - `validate_code(catalog_type, code)` → accept if exists and is_active=True, reject otherwise
    - `lookup_code(catalog_type, code)` → return display name in requested locale
    - `search_codes(catalog_type, query, locale)` → fuzzy search by display name
    - Create `backend/app/modules/code_catalogs/seed.py` with ICD-10, ATC, LOINC seed data
    - _Requirements: 1.3, 2.2, 3.2, 4.6, 15.4_

  - [~] 1.3 Create code catalog schemas and router
    - Create `backend/app/modules/code_catalogs/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/code_catalogs/router.py` with endpoints:
      - `GET /api/v1/codes/{catalog_type}/validate/{code}`
      - `GET /api/v1/codes/{catalog_type}/search`
    - No RBAC restriction on code lookup (read-only reference data)
    - _Requirements: 1.3, 2.2, 3.2, 4.6_

- [ ] 2. Encounters module (Layer 1 — Core Clinical)
  - [~] 2.1 Create encounter SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/encounters/models.py` with `Encounter`, `SOAPNote`, `Diagnosis`, `Procedure` models
    - Create `backend/app/modules/encounters/__init__.py` and `enums.py` with `EncounterStatus`, `EncounterClass`
    - Generate Alembic migration for `encounters`, `soap_notes`, `diagnoses`, `procedures` tables with RLS
    - Add indexes: `(tenant_id, patient_id, check_in_time DESC)`, `(tenant_id, clinician_id, status)`
    - _Requirements: 1.1, 1.7, 13.1_

  - [~] 2.2 Implement encounter service with SOAP notes, diagnoses, and discharge
    - Create `backend/app/modules/encounters/service.py` with `EncounterService`
    - Create `backend/app/modules/encounters/service_soap.py` with SOAP note CRUD
    - Create `backend/app/modules/encounters/service_diagnosis.py` with ICD-10 validation and chronic condition sync
    - Generate discharge summary on encounter completion, publish `EncounterCompleted` event
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 16.3_

  - [~] 2.3 Create encounter FHIR mapper
    - Create `backend/app/modules/encounters/fhir_mapper.py` with `to_fhir()` and `from_fhir()`
    - Map internal Encounter to FHIR R4 Encounter resource (status, class, type, subject, participant, period, reasonCode)
    - Store computed `fhir_json` on encounter creation/update
    - _Requirements: 1.8, 4.1, 4.5_

  - [~] 2.4 Create encounter schemas and router
    - Create `backend/app/modules/encounters/schemas.py` with Pydantic request/response schemas
    - Create `backend/app/modules/encounters/router.py`: `POST /encounters`, `GET /encounters`
    - Create `backend/app/modules/encounters/router_detail.py`: `GET/PUT /encounters/{id}`, SOAP notes, diagnoses, procedures, discharge
    - Apply RBAC: create/update/discharge = Doctor, SOAP/diagnoses = Doctor, read = Doctor/Nurse
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 13.6_

- [ ] 3. Prescriptions module (Layer 1 — Core Clinical)
  - [~] 3.1 Create prescription SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/prescriptions/models.py` with `Prescription`, `Dispensing` models
    - Create `backend/app/modules/prescriptions/__init__.py` and `enums.py` with `PrescriptionStatus`
    - Generate Alembic migration for `prescriptions`, `dispensings` tables with RLS policies
    - Add indexes: `(tenant_id, patient_id, status)`, `(encounter_id)`
    - _Requirements: 2.1, 2.9, 13.1_

  - [~] 3.2 Implement prescription service with DDI integration and refill logic
    - Create `backend/app/modules/prescriptions/service.py` with `PrescriptionService`
    - Validate ATC code via CodeCatalogService, invoke existing `check_ddi()`/`check_dhi()`
    - Block Contraindicated interactions unless acknowledged with justification
    - Create `backend/app/modules/prescriptions/service_refill.py` for refill processing
    - Publish `PrescriptionWritten` domain event
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 16.2_

  - [~] 3.3 Create prescription FHIR mapper
    - Create `backend/app/modules/prescriptions/fhir_mapper.py` with `to_fhir()` and `from_fhir()`
    - Map to FHIR R4 MedicationRequest (status, intent, medicationCodeableConcept, dosageInstruction)
    - _Requirements: 2.8, 4.2, 4.5_

  - [~] 3.4 Create prescription schemas and router
    - Create `backend/app/modules/prescriptions/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/prescriptions/router.py`: `POST /prescriptions`, `GET /prescriptions`, `GET /prescriptions/{id}`, `PUT /prescriptions/{id}/status`, `POST /prescriptions/{id}/refill`, `GET /patients/{id}/prescriptions`
    - Apply RBAC: write/discontinue/refill = Doctor, read = Doctor/Nurse
    - _Requirements: 2.1, 2.5, 2.7, 13.6_

- [ ] 4. Lab orders module (Layer 1 — Core Clinical)
  - [~] 4.1 Create lab order SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/lab_orders/models.py` with `LabOrder`, `LabResult` models
    - Create `backend/app/modules/lab_orders/__init__.py` and `enums.py` with `LabOrderStatus`, `Priority`
    - Generate Alembic migration for `lab_orders`, `lab_results` tables with RLS policies
    - Add indexes: `(tenant_id, patient_id, status)`, `(encounter_id)`, `(tenant_id, status, priority)`
    - _Requirements: 3.1, 3.8, 13.1_

  - [~] 4.2 Implement lab order service with measurement integration
    - Create `backend/app/modules/lab_orders/service.py` with `LabOrderService`
    - Validate LOINC code via CodeCatalogService, handle status transitions
    - Create `backend/app/modules/lab_orders/service_results.py`:
      - Record result, compute is_abnormal flag, create Measurement record
      - Publish `MeasurementSaved` event, trigger alert if abnormal
    - Publish `LabResultReceived` domain event
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 16.1, 16.6_

  - [~] 4.3 Create lab order FHIR mapper
    - Create `backend/app/modules/lab_orders/fhir_mapper.py`
    - `order_to_fhir()` → FHIR R4 ServiceRequest
    - `result_to_fhir()` → FHIR R4 DiagnosticReport + Observation
    - `from_fhir_order()` / `from_fhir_result()` → parse back to internal models
    - _Requirements: 3.7, 4.3, 4.5_

  - [~] 4.4 Create lab order schemas and router
    - Create `backend/app/modules/lab_orders/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/lab_orders/router.py`: `POST /lab-orders`, `GET /lab-orders`, `GET /lab-orders/{id}`, `PUT /lab-orders/{id}/status`, `POST /lab-orders/{id}/results`, `GET /patients/{id}/lab-orders`
    - Apply RBAC: create = Doctor/Nurse, result = Doctor/Nurse, status = Nurse, read = Doctor/Nurse
    - _Requirements: 3.1, 3.3, 3.4, 13.6_

- [ ] 5. Layer 1 property tests and unit tests
  - [ ]* 5.1 Write property test for code catalog validation
    - **Property 1: Code Catalog Validation**
    - Test that valid ICD-10/ATC/LOINC codes are accepted and invalid codes are rejected
    - **Validates: Requirements 1.3, 2.2, 3.2, 4.6**

  - [ ]* 5.2 Write property test for FHIR round-trip compatibility
    - **Property 2: FHIR Round-Trip Compatibility**
    - Test that `parse(print(record)) ≡ record` for encounters, prescriptions, lab orders
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5, 11.7**

  - [ ]* 5.3 Write property test for discharge summary completeness
    - **Property 3: Discharge Summary Completeness**
    - Test that all diagnoses, procedures, prescriptions appear in discharge summary
    - **Validates: Requirements 1.5**

  - [ ]* 5.4 Write property test for chronic condition synchronization
    - **Property 4: Chronic Condition Synchronization**
    - Test that chronic diagnoses update patient record, non-chronic do not
    - **Validates: Requirements 1.6, 16.3**

  - [ ]* 5.5 Write property test for contraindicated interaction blocks prescription
    - **Property 5: Contraindicated Interaction Blocks Prescription**
    - Test that Contraindicated DDI blocks prescription without acknowledgment
    - **Validates: Requirements 2.4, 16.2**

  - [ ]* 5.6 Write property test for prescription refill guard
    - **Property 6: Prescription Refill Guard**
    - Test refill succeeds iff refills_remaining > 0 and status=active, decrements by 1
    - **Validates: Requirements 2.7**

  - [ ]* 5.7 Write property test for lab result abnormal flag correctness
    - **Property 7: Lab Result Abnormal Flag Correctness**
    - Test is_abnormal=True iff value outside reference range
    - **Validates: Requirements 3.6**

  - [ ]* 5.8 Write property test for lab result to measurement pipeline
    - **Property 8: Lab Result to Measurement Pipeline**
    - Test that lab results create Measurement records and trigger MeasurementSaved event
    - **Validates: Requirements 3.5, 16.1, 16.6**

  - [ ]* 5.9 Write unit tests for encounters module
    - Test encounter creation, SOAP note CRUD, status transitions
    - Test ICD-10 validation rejection for invalid codes
    - Test discharge summary generation completeness
    - _Requirements: 1.1, 1.2, 1.3, 1.5_

  - [ ]* 5.10 Write unit tests for prescriptions module
    - Test DDI override flow with justification recording
    - Test prescription status lifecycle (active → discontinued/completed/on_hold)
    - Test refill with exhausted count rejection
    - _Requirements: 2.1, 2.4, 2.5, 2.7_

  - [ ]* 5.11 Write unit tests for lab orders module
    - Test LOINC validation, status transitions (ordered → specimen_collected → resulted)
    - Test abnormal result alert generation
    - Test measurement creation from lab result
    - _Requirements: 3.1, 3.3, 3.5, 3.6_

- [~] 6. Checkpoint — Verify Layer 1 (Core Clinical Workflow)
  - Ensure all tests pass, ask the user if questions arise.
  - Verify encounters, prescriptions, and lab orders work end-to-end
  - Verify code catalog validation rejects invalid codes
  - Verify FHIR mappers produce valid JSON

- [ ] 7. Appointments module (Layer 2 — Operational Features)
  - [~] 7.1 Create appointment SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/appointments/models.py` with `Appointment`, `Waitlist` models
    - Create `backend/app/modules/appointments/__init__.py` and `enums.py` with `AppointmentStatus`, `AppointmentType`
    - Generate Alembic migration for `appointments`, `waitlist` tables with RLS policies
    - Add exclusion constraint preventing overlapping times for same clinician
    - Add indexes: `(tenant_id, clinician_id, scheduled_start)`, `(tenant_id, patient_id)`
    - _Requirements: 5.1, 5.8, 13.1_

  - [~] 7.2 Implement appointment service with conflict detection and recurrence
    - Create `backend/app/modules/appointments/service.py` with `AppointmentService`:
      - `book_appointment(data)` → check for double-booking, create appointment
      - `reschedule(appointment_id, new_time)` → update time, record reason
      - `cancel(appointment_id, reason)` → cancel, offer slot to waitlist
    - Create `backend/app/modules/appointments/service_waitlist.py` for waitlist management
    - Create `backend/app/modules/appointments/service_recurrence.py` for recurring generation
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.8_

  - [~] 7.3 Create appointment schemas and router
    - Create `backend/app/modules/appointments/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/appointments/router.py`: `POST /appointments`, `GET /appointments`, `GET /appointments/{id}`, `PUT /appointments/{id}`, `DELETE /appointments/{id}`, `POST /appointments/waitlist`, `GET /patients/{id}/appointments`
    - Apply RBAC: book/reschedule/cancel = Nurse/Clinic_Admin, read = all clinical roles
    - _Requirements: 5.1, 5.7, 13.6_

- [ ] 8. Referrals module (Layer 2 — Operational Features)
  - [~] 8.1 Create referral SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/referrals/models.py` with `Referral` model
    - Create `backend/app/modules/referrals/__init__.py` and `enums.py` with `ReferralStatus`, `Urgency`
    - Generate Alembic migration for `referrals` table with RLS policies
    - Add indexes: `(tenant_id, patient_id, status)`, `(tenant_id, referring_clinician_id)`
    - _Requirements: 6.1, 6.6, 13.1_

  - [~] 8.2 Implement referral service
    - Create `backend/app/modules/referrals/service.py` with `ReferralService`:
      - `create_referral(data)` → generate referral letter with clinical summary
      - `update_status(referral_id, new_status)` → handle status transitions
      - `record_completion(referral_id, findings)` → record specialist findings and recommendations
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [~] 8.3 Create referral schemas and router
    - Create `backend/app/modules/referrals/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/referrals/router.py`: `POST /referrals`, `GET /referrals`, `GET /referrals/{id}`, `PUT /referrals/{id}/status`, `POST /referrals/{id}/completion`
    - Apply RBAC: create/complete = Doctor, read = Doctor/Nurse
    - _Requirements: 6.1, 6.2, 6.5, 13.6_

- [ ] 9. Documents module (Layer 2 — Operational Features)
  - [~] 9.1 Create document SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/documents/models.py` with `Document` model
    - Create `backend/app/modules/documents/__init__.py` and `enums.py` with `DocumentType`
    - Generate Alembic migration for `documents` table with RLS policies
    - Add indexes: `(tenant_id, patient_id, document_type)`, `(tenant_id, created_at DESC)`
    - _Requirements: 7.1, 7.6, 13.1_

  - [~] 9.2 Implement document service with S3 storage
    - Create `backend/app/modules/documents/storage.py` with S3/object storage abstraction
    - Create `backend/app/modules/documents/service.py` with `DocumentService`:
      - `upload_document(file, metadata)` → validate MIME type and size, encrypt, store in S3, save metadata
      - `download_document(document_id)` → verify authorization, serve file
      - `search_documents(patient_id, filters)` → search by type, date range
    - Validate: allowed MIME types (PDF, JPEG, PNG, TIFF, DICOM), max 25 MB
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [~] 9.3 Create document schemas and router
    - Create `backend/app/modules/documents/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/documents/router.py`: `POST /documents`, `GET /documents`, `GET /documents/{id}`, `GET /documents/{id}/download`, `GET /patients/{id}/documents`
    - Apply RBAC: upload = Doctor/Nurse/Clinic_Admin, read/download = Doctor/Nurse
    - _Requirements: 7.1, 7.4, 7.6, 13.6_

- [ ] 10. Registration module (Layer 2 — Operational Features)
  - [~] 10.1 Create registration SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/registration/models.py` with `Consent`, `IdentityVerification` models
    - Create `backend/app/modules/registration/__init__.py`
    - Generate Alembic migration for `consents`, `identity_verifications` tables with RLS policies
    - _Requirements: 8.2, 8.3, 8.7, 13.1_

  - [~] 10.2 Implement registration service with consent capture
    - Create `backend/app/modules/registration/service.py` with `RegistrationService`:
      - `start_intake(data)` → create partial registration record
      - `update_registration(id, data)` → update fields for partial completion
      - `complete_registration(id)` → finalize, create Patient record in existing Patient model
      - Generate unique medical record number per tenant
    - Create `backend/app/modules/registration/service_consent.py`:
      - `capture_consent(patient_id, consent_data)` → store digital signature, type, timestamp
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [~] 10.3 Create registration schemas and router
    - Create `backend/app/modules/registration/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/registration/router.py`: `POST /registration/intake`, `PUT /registration/{id}`, `POST /registration/{id}/consent`, `POST /registration/{id}/identity`, `POST /registration/{id}/complete`
    - Apply RBAC: all endpoints = Nurse/Clinic_Admin
    - _Requirements: 8.1, 8.2, 8.5, 8.6, 13.6_

- [ ] 11. Layer 2 property tests and unit tests
  - [ ]* 11.1 Write property test for appointment double-booking prevention
    - **Property 9: Appointment Double-Booking Prevention**
    - Test that overlapping appointments for same clinician are always rejected
    - **Validates: Requirements 5.8**

  - [ ]* 11.2 Write property test for recurring appointment generation
    - **Property 10: Recurring Appointment Generation**
    - Test correct number of instances generated with correct scheduled_start values
    - **Validates: Requirements 5.4**

  - [ ]* 11.3 Write property test for document upload validation
    - **Property 11: Document Upload Validation**
    - Test accept iff MIME type in allowed set AND size ≤ 25 MB
    - **Validates: Requirements 7.2**

  - [ ]* 11.4 Write property test for EMR tenant isolation
    - **Property 14: EMR Tenant Isolation**
    - Test that API requests for tenant T1 return zero records belonging to T2
    - **Validates: Requirements 1.7, 2.9, 3.8, 5.8, 6.6, 7.6, 8.7, 9.7, 10.7, 13.1**

  - [ ]* 11.5 Write unit tests for appointments module
    - Test double-booking rejection, waitlist promotion on cancellation
    - Test recurring appointment generation (daily, weekly, biweekly, monthly)
    - Test reminder scheduling (24h before)
    - _Requirements: 5.1, 5.3, 5.4, 5.5, 5.6, 5.8_

  - [ ]* 11.6 Write unit tests for referrals module
    - Test referral letter generation with clinical summary
    - Test status transitions (pending → accepted → scheduled → completed)
    - Test specialist findings recording
    - _Requirements: 6.1, 6.2, 6.3, 6.5_

  - [ ]* 11.7 Write unit tests for documents module
    - Test MIME type validation (accept PDF/JPEG/PNG/TIFF/DICOM, reject others)
    - Test file size rejection (>25 MB)
    - Test document search by type and date range
    - _Requirements: 7.1, 7.2, 7.3, 7.6_

  - [ ]* 11.8 Write unit tests for registration module
    - Test partial registration workflow (complete over multiple visits)
    - Test consent capture with digital signature
    - Test MRN generation uniqueness per tenant
    - _Requirements: 8.1, 8.2, 8.5, 8.6, 8.7_

- [~] 12. Checkpoint — Verify Layer 2 (Operational Features)
  - Ensure all tests pass, ask the user if questions arise.
  - Verify appointments with conflict detection work end-to-end
  - Verify referrals, documents, and registration workflows complete successfully
  - Verify tenant isolation across all Layer 2 modules

- [ ] 13. Billing module (Layer 3 — Advanced Operations)
  - [~] 13.1 Create billing SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/billing/models.py` with `Invoice`, `InvoiceLineItem`, `Payment`, `InsuranceClaim` models
    - Create `backend/app/modules/billing/__init__.py` and `enums.py` with `InvoiceStatus`, `ClaimStatus`, `PaymentMethod`
    - Generate Alembic migration for `invoices`, `invoice_line_items`, `payments`, `insurance_claims` tables with RLS
    - _Requirements: 9.1, 9.7, 13.1_

  - [~] 13.2 Implement billing service with claims processing
    - Create `backend/app/modules/billing/service.py` with `BillingService`:
      - `generate_invoice(encounter_id)` → create invoice with line items from encounter (consultation, procedures, labs, meds)
      - `record_payment(invoice_id, payment_data)` → record payment, update invoice status
      - `get_invoice_detail(invoice_id)` → return invoice with line items and payments
    - Create `backend/app/modules/billing/service_claims.py`:
      - `submit_claim(invoice_id, insurance_data)` → generate NHIS/NHIF claim
      - `update_claim_status(claim_id, status, reason)` → handle approval/denial
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [~] 13.3 Create billing schemas and router
    - Create `backend/app/modules/billing/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/billing/router.py`: `POST /invoices`, `GET /invoices`, `GET /invoices/{id}`, `POST /invoices/{id}/payments`, `POST /insurance-claims`, `GET /insurance-claims`, `PUT /insurance-claims/{id}/status`
    - Apply RBAC: all endpoints = Clinic_Admin
    - _Requirements: 9.1, 9.3, 9.5, 13.6_

- [ ] 14. Bed management module (Layer 3 — Advanced Operations)
  - [~] 14.1 Create bed management SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/bed_management/models.py` with `Ward`, `Bed`, `Admission`, `NursingNote` models
    - Create `backend/app/modules/bed_management/__init__.py` and `enums.py` with `BedStatus`, `DischargeType`
    - Generate Alembic migration for `wards`, `beds`, `admissions`, `nursing_notes` tables with RLS
    - Add unique constraint `(tenant_id, ward_id, bed_number)` on beds
    - Add indexes: `(tenant_id, status)` on admissions, `(bed_id, status)` on admissions
    - _Requirements: 10.1, 10.2, 10.7, 13.1_

  - [~] 14.2 Implement bed management service with vitals charting
    - Create `backend/app/modules/bed_management/service.py` with `BedManagementService`:
      - `admit_patient(data)` → assign bed, update bed status to occupied, record admission
      - `discharge_patient(admission_id, discharge_data)` → generate discharge plan, update bed to available
      - `get_bed_availability(ward_id)` → real-time bed status per ward
    - Create `backend/app/modules/bed_management/service_nursing.py`:
      - `add_nursing_note(admission_id, content)` → record nursing note
      - `chart_vitals(admission_id, vitals_data)` → create Measurement records, publish `MeasurementSaved` events
    - Publish `PatientAdmitted` and `PatientDischarged` domain events
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 16.6_

  - [~] 14.3 Create bed management schemas and router
    - Create `backend/app/modules/bed_management/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/bed_management/router.py`: `POST /admissions`, `GET /beds`, `GET /admissions/{id}`, `POST /admissions/{id}/nursing-notes`, `POST /admissions/{id}/vitals`, `POST /admissions/{id}/discharge`
    - Apply RBAC: admit/discharge = Doctor, nursing notes/vitals = Nurse, bed status = Nurse/Doctor
    - _Requirements: 10.1, 10.3, 10.4, 10.5, 13.6_

- [ ] 15. FHIR API module (Layer 3 — Advanced Operations)
  - [~] 15.1 Implement FHIR service with validation and search
    - Create `backend/app/modules/fhir_api/service.py` with `FHIRService`:
      - `validate_resource(resource_type, fhir_json)` → validate against FHIR R4 schema
      - `parse_to_internal(resource_type, fhir_json)` → convert FHIR to internal model
      - `print_to_fhir(resource_type, internal_record)` → convert internal to FHIR JSON
    - Create `backend/app/modules/fhir_api/validator.py` with FHIR R4 schema validation
    - Create `backend/app/modules/fhir_api/search.py` with FHIR search parameter parsing (_id, patient, date, status, code)
    - Create `backend/app/modules/fhir_api/__init__.py`
    - _Requirements: 11.1, 11.2, 11.3, 11.7_

  - [~] 15.2 Implement FHIR router with OAuth and subscriptions
    - Create `backend/app/modules/fhir_api/router.py`: `GET /fhir/r4/{resourceType}`, `GET /fhir/r4/{resourceType}/{id}`, `POST /fhir/r4/{resourceType}`, `PUT /fhir/r4/{resourceType}/{id}`
    - Create `backend/app/modules/fhir_api/router_bulk.py`: `GET /fhir/r4/$export` for bulk data export
    - Create `backend/app/modules/fhir_api/subscriptions.py` for webhook subscription management
    - Create `backend/app/modules/fhir_api/auth_oauth.py` with OAuth 2.0 client credentials for external systems
    - _Requirements: 11.1, 11.4, 11.5, 11.6_

- [ ] 16. Integration module (Layer 3 — Advanced Operations)
  - [~] 16.1 Create integration SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/integrations/models.py` with `SyncLog`, `ConnectorConfig` models
    - Create `backend/app/modules/integrations/__init__.py`
    - Generate Alembic migration for `sync_logs`, `connector_configs` tables with RLS
    - _Requirements: 12.6, 12.7, 13.1_

  - [~] 16.2 Implement integration connectors and sync engine
    - Create `backend/app/modules/integrations/connectors/openmrs.py` — OpenMRS bidirectional sync
    - Create `backend/app/modules/integrations/connectors/dhis2.py` — DHIS2 aggregate export
    - Create `backend/app/modules/integrations/connectors/generic_fhir.py` — generic FHIR R4 connector
    - Create `backend/app/modules/integrations/sync_engine.py`:
      - Conflict resolution (last-write-wins with audit trail)
      - Retry with exponential backoff (30s, 2min, 8min, max 5 retries)
    - Create `backend/app/modules/integrations/tasks.py` with Celery tasks for async sync
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [~] 16.3 Create integration service, schemas, and router
    - Create `backend/app/modules/integrations/service.py` with `IntegrationService`
    - Create `backend/app/modules/integrations/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/integrations/router.py`: connector management endpoints
    - Apply RBAC: all endpoints = Clinic_Admin/Super_Admin
    - _Requirements: 12.1, 12.6, 12.7, 13.6_

- [ ] 17. Layer 3 property tests and unit tests
  - [ ]* 17.1 Write property test for invoice total consistency
    - **Property 12: Invoice Total Consistency**
    - Test that total_amount equals sum of all line_items[].total_price
    - **Validates: Requirements 9.1**

  - [ ]* 17.2 Write property test for bed status consistency
    - **Property 13: Bed Status Consistency**
    - Test bed status transitions: occupied after admission, available after discharge, reject admission to occupied/maintenance beds
    - **Validates: Requirements 10.1, 10.2, 10.6**

  - [ ]* 17.3 Write property test for translation fallback
    - **Property 15: Translation Fallback**
    - Test that missing translations fall back to English, never return raw keys
    - **Validates: Requirements 15.3**

  - [ ]* 17.4 Write unit tests for billing module
    - Test invoice generation from encounter with all billable items
    - Test payment recording and invoice status updates
    - Test insurance claim submission and denial/resubmission flow
    - _Requirements: 9.1, 9.3, 9.5, 9.6_

  - [ ]* 17.5 Write unit tests for bed management module
    - Test admission to available bed, rejection of occupied bed
    - Test nursing note recording, vitals charting → Measurement creation
    - Test discharge plan generation and bed status update
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [ ]* 17.6 Write unit tests for FHIR API module
    - Test FHIR resource validation (accept valid, reject with OperationOutcome)
    - Test search parameter parsing (_id, patient, date, status, code)
    - Test bulk data export endpoint
    - Test OAuth 2.0 client credentials authentication
    - _Requirements: 11.1, 11.2, 11.3, 11.6_

  - [ ]* 17.7 Write unit tests for integration module
    - Test connector configuration and management
    - Test conflict resolution (last-write-wins with audit trail)
    - Test retry with exponential backoff on unreachable systems
    - Test sync log recording without PHI
    - _Requirements: 12.1, 12.4, 12.5, 12.6_

- [~] 18. Checkpoint — Verify Layer 3 (Advanced Operations)
  - Ensure all tests pass, ask the user if questions arise.
  - Verify billing generates correct invoices from encounters
  - Verify bed management tracks admissions and discharges correctly
  - Verify FHIR API validates and serves resources
  - Verify integration connectors handle sync and retry logic

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation per layer
- Property tests validate the 15 correctness properties from the design document
- Unit tests validate specific examples and edge cases per module
- Layer 1 depends on existing modules (patients, measurements, drug_interactions, alerts)
- Layer 2 depends on Layer 1 (encounters) for referrals and documents linking
- Layer 3 depends on Layer 1 (encounters, prescriptions, lab_orders) for billing and FHIR
- Code catalogs (task 1) must be implemented first as all Layer 1 modules depend on code validation
- All modules enforce RLS tenant isolation following the existing pattern
- FHIR mappers store computed JSON on write to avoid runtime transformation overhead

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1", "3.1", "4.1"] },
    { "id": 3, "tasks": ["2.2", "3.2", "4.2"] },
    { "id": 4, "tasks": ["2.3", "2.4", "3.3", "3.4", "4.3", "4.4"] },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "5.8", "5.9", "5.10", "5.11"] },
    { "id": 6, "tasks": ["7.1", "8.1", "9.1", "10.1"] },
    { "id": 7, "tasks": ["7.2", "8.2", "9.2", "10.2"] },
    { "id": 8, "tasks": ["7.3", "8.3", "9.3", "10.3"] },
    { "id": 9, "tasks": ["11.1", "11.2", "11.3", "11.4", "11.5", "11.6", "11.7", "11.8"] },
    { "id": 10, "tasks": ["13.1", "14.1", "16.1"] },
    { "id": 11, "tasks": ["13.2", "14.2", "15.1", "16.2"] },
    { "id": 12, "tasks": ["13.3", "14.3", "15.2", "16.3"] },
    { "id": 13, "tasks": ["17.1", "17.2", "17.3", "17.4", "17.5", "17.6", "17.7"] }
  ]
}
```
