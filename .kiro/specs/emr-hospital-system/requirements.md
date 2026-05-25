# Requirements Document

## Introduction

This document defines the requirements for the EMR Hospital System feature of PrescpHealth. The system extends the existing AI-powered clinical decision support platform into a full Electronic Medical Record (EMR/EHR) system suitable for standalone deployment in clinics across Africa and underserved communities, or as an AI prediction engine integrating with existing EMR systems via FHIR R4. The feature is organized into three layers: Core Clinical Workflow (immediate), Operational Features (post-AI modules), and Advanced Operations (post-frontend).

## Glossary

- **EMR_System**: The Electronic Medical Record system encompassing all clinical workflow, operational, and advanced modules defined in this specification
- **Encounter_Service**: The module responsible for managing patient visits, check-ins, SOAP notes, diagnoses, procedures, and discharge summaries
- **Prescription_Service**: The module responsible for writing, tracking, and managing medication prescriptions including refills and e-prescribing
- **Lab_Order_Service**: The module responsible for ordering laboratory tests, tracking specimen collection, and linking results to patient measurements
- **Appointment_Service**: The module responsible for scheduling, rescheduling, canceling, and managing patient appointments
- **Referral_Service**: The module responsible for creating, tracking, and completing specialist referrals across facilities
- **Document_Service**: The module responsible for uploading, categorizing, and linking clinical documents and attachments to patients and visits
- **Registration_Service**: The module responsible for patient intake workflows including consent capture and identity verification
- **Billing_Service**: The module responsible for invoice generation, insurance claims processing, and payment tracking
- **Bed_Management_Service**: The module responsible for ward assignments, bed availability tracking, nursing notes, and discharge planning
- **FHIR_API_Service**: The module responsible for exposing and consuming FHIR R4 resources for interoperability with external EMR systems
- **Integration_Service**: The module responsible for connectors to external systems including OpenMRS, DHIS2, and generic FHIR-compliant EMRs
- **Clinician**: A user with the Doctor or Nurse role who provides clinical care
- **SOAP_Note**: A structured clinical note format consisting of Subjective, Objective, Assessment, and Plan sections
- **ICD_10**: The International Classification of Diseases, 10th Revision, used for coding diagnoses
- **ATC**: The Anatomical Therapeutic Chemical classification system used for coding drugs
- **LOINC**: Logical Observation Identifiers Names and Codes, used for coding laboratory tests and clinical observations
- **FHIR_R4**: Fast Healthcare Interoperability Resources Release 4, the standard for exchanging healthcare information electronically
- **RLS**: Row-Level Security, the PostgreSQL mechanism enforcing tenant data isolation at the database level
- **NHIS**: National Health Insurance Scheme (Nigeria)
- **NHIF**: National Hospital Insurance Fund (Kenya)

## Requirements

### Requirement 1: Patient Visit and Encounter Management

**User Story:** As a Clinician, I want to record patient visits with structured clinical notes and coded diagnoses, so that I can maintain a complete medical record for each patient encounter.

#### Acceptance Criteria

1. WHEN a patient arrives at the clinic, THE Encounter_Service SHALL create a new encounter record containing patient_id, check_in_time, reason_for_visit, and assigned_clinician_id
2. WHILE an encounter is in progress, THE Encounter_Service SHALL allow the assigned Clinician to record SOAP notes with separate Subjective, Objective, Assessment, and Plan sections
3. WHEN a Clinician enters a diagnosis, THE Encounter_Service SHALL validate the diagnosis code against the ICD-10 code set and reject codes not present in the ICD-10 catalog
4. WHEN a Clinician records a procedure, THE Encounter_Service SHALL store the procedure code, description, and performing clinician identity
5. WHEN a Clinician completes an encounter, THE Encounter_Service SHALL generate a discharge summary containing diagnoses, procedures performed, prescriptions issued, follow-up instructions, and next appointment recommendation
6. WHEN a diagnosis is recorded for an encounter, THE Encounter_Service SHALL update the patient chronic_conditions JSONB field in the existing Patient model if the diagnosis represents a chronic condition
7. THE Encounter_Service SHALL link each encounter to the existing Patient model via patient_id and enforce tenant isolation using RLS
8. WHEN an encounter is created, THE Encounter_Service SHALL map the encounter data to a FHIR R4 Encounter resource structure for interoperability readiness

### Requirement 2: Prescription and Medication Management

**User Story:** As a Doctor, I want to write and manage prescriptions with standardized drug coding, so that I can track active medications and prepare for e-prescribing integration.

#### Acceptance Criteria

1. WHEN a Doctor writes a prescription, THE Prescription_Service SHALL record the drug name, ATC code, dosage, frequency, duration, route of administration, and prescribing clinician identity
2. THE Prescription_Service SHALL validate the ATC code against the ATC classification catalog and reject codes not present in the catalog
3. WHEN a prescription is written, THE Prescription_Service SHALL invoke the existing Drug Interaction engine to check for drug-drug and drug-health interactions before confirming the prescription
4. WHEN a drug interaction with severity "Contraindicated" is detected, THE Prescription_Service SHALL block the prescription and require the Doctor to acknowledge the interaction with a documented justification before proceeding
5. WHILE a prescription is active, THE Prescription_Service SHALL track the prescription status as one of: active, completed, discontinued, or on_hold
6. WHEN a Doctor discontinues a prescription, THE Prescription_Service SHALL record the discontinuation reason, date, and discontinuing clinician identity
7. WHEN a patient requests a refill, THE Prescription_Service SHALL verify the prescription allows refills, check remaining refill count, and create a new dispensing record
8. THE Prescription_Service SHALL map prescription data to a FHIR R4 MedicationRequest resource structure for e-prescribing readiness
9. THE Prescription_Service SHALL enforce tenant isolation using RLS and link prescriptions to both the patient and the originating encounter

### Requirement 3: Laboratory Order Management

**User Story:** As a Clinician, I want to order lab tests and track their status from order to result, so that I can monitor diagnostic workflows and integrate results into the patient record.

#### Acceptance Criteria

1. WHEN a Clinician orders a lab test, THE Lab_Order_Service SHALL record the test name, LOINC code, ordering clinician, clinical indication, and priority level (routine, urgent, stat)
2. THE Lab_Order_Service SHALL validate the LOINC code against the LOINC catalog and reject codes not present in the catalog
3. THE Lab_Order_Service SHALL track each lab order through the statuses: ordered, specimen_collected, in_progress, resulted, cancelled
4. WHEN a lab result is received, THE Lab_Order_Service SHALL store the result value, units, reference range, abnormal flag, and resulted_at timestamp
5. WHEN a lab result is received, THE Lab_Order_Service SHALL create a corresponding record in the existing Measurement model to feed into the risk computation pipeline
6. WHEN a lab result value falls outside the reference range, THE Lab_Order_Service SHALL flag the result as abnormal and generate an alert via the existing Alert system
7. THE Lab_Order_Service SHALL map lab orders and results to FHIR R4 DiagnosticReport and Observation resource structures for external lab integration readiness
8. THE Lab_Order_Service SHALL enforce tenant isolation using RLS and link lab orders to both the patient and the originating encounter

### Requirement 4: FHIR R4 Data Model Compatibility

**User Story:** As a system integrator, I want all clinical data models to map cleanly to FHIR R4 resources, so that the system can interoperate with external EMR systems and health information exchanges.

#### Acceptance Criteria

1. THE EMR_System SHALL design the Encounter data model to map to the FHIR R4 Encounter resource including status, class, type, subject, participant, period, and reasonCode fields
2. THE EMR_System SHALL design the Prescription data model to map to the FHIR R4 MedicationRequest resource including status, intent, medicationCodeableConcept, subject, dosageInstruction, and dispenseRequest fields
3. THE EMR_System SHALL design the Lab Order data model to map to the FHIR R4 ServiceRequest resource and results to DiagnosticReport and Observation resources
4. THE EMR_System SHALL design the Patient data model extensions to remain compatible with the FHIR R4 Patient resource including identifier, name, telecom, gender, birthDate, and address fields
5. WHEN clinical data is created or updated, THE EMR_System SHALL store a FHIR-compatible JSON representation alongside the relational data to enable future FHIR API exposure without data transformation
6. THE EMR_System SHALL use FHIR R4 value sets for coded fields: ICD-10 for conditions, ATC for medications, LOINC for observations, and SNOMED CT for procedures where applicable

### Requirement 5: Appointment Scheduling

**User Story:** As a Clinic Administrator, I want to manage patient appointments with scheduling, reminders, and waitlist capabilities, so that clinic operations run efficiently and patients receive timely care.

#### Acceptance Criteria

1. WHEN a staff member books an appointment, THE Appointment_Service SHALL record the patient_id, clinician_id, appointment_type, scheduled_datetime, duration_minutes, and reason
2. WHEN a staff member reschedules an appointment, THE Appointment_Service SHALL update the scheduled_datetime, record the rescheduling reason, and notify the patient via the configured notification channel
3. WHEN a staff member cancels an appointment, THE Appointment_Service SHALL record the cancellation reason, update the status to cancelled, and offer the slot to the next patient on the waitlist
4. WHEN a recurring appointment pattern is configured, THE Appointment_Service SHALL generate individual appointment instances for the specified recurrence period (daily, weekly, biweekly, monthly)
5. WHEN an appointment is scheduled, THE Appointment_Service SHALL send a reminder notification to the patient 24 hours before the appointment via SMS or email based on patient preference
6. WHILE a clinician's schedule is full, THE Appointment_Service SHALL allow patients to join a waitlist and notify them when a slot becomes available
7. THE Appointment_Service SHALL provide a calendar view of appointments filterable by clinician, date range, and appointment type
8. THE Appointment_Service SHALL enforce tenant isolation using RLS and prevent double-booking of the same clinician at overlapping time slots

### Requirement 6: Specialist Referral Management

**User Story:** As a Doctor, I want to refer patients to specialists and track referral outcomes, so that I can coordinate care across providers and facilities.

#### Acceptance Criteria

1. WHEN a Doctor creates a referral, THE Referral_Service SHALL record the referring clinician, receiving specialist or facility, clinical reason, urgency level, and relevant clinical summary
2. THE Referral_Service SHALL track each referral through the statuses: pending, accepted, scheduled, completed, declined
3. WHEN a referral is created, THE Referral_Service SHALL generate a referral letter containing patient demographics, relevant medical history, current medications, recent lab results, and the clinical question for the specialist
4. WHEN a referral is to an external facility, THE Referral_Service SHALL record the receiving facility identifier and support inter-facility referral tracking
5. WHEN a specialist completes a referral, THE Referral_Service SHALL allow recording of the specialist findings, recommendations, and follow-up plan back to the referring Doctor
6. THE Referral_Service SHALL enforce tenant isolation using RLS and link referrals to both the patient and the originating encounter

### Requirement 7: Clinical Document and Attachment Management

**User Story:** As a Clinician, I want to upload and manage clinical documents such as scans, external reports, and consent forms, so that all relevant patient information is accessible in one place.

#### Acceptance Criteria

1. WHEN a user uploads a document, THE Document_Service SHALL store the file with metadata including document_type, upload_date, uploader_identity, file_size, and MIME type
2. THE Document_Service SHALL validate uploaded files against allowed MIME types (PDF, JPEG, PNG, TIFF, DICOM) and reject files exceeding 25 MB in size
3. THE Document_Service SHALL categorize documents by type: lab_report, imaging, consent_form, referral_letter, discharge_summary, insurance_card, identification, and other
4. WHEN a document is uploaded, THE Document_Service SHALL link the document to the relevant patient and optionally to a specific encounter
5. THE Document_Service SHALL encrypt stored documents at rest and serve them only to authorized users with appropriate role permissions
6. THE Document_Service SHALL enforce tenant isolation using RLS and provide document search by patient, type, and date range

### Requirement 8: Patient Registration Workflow

**User Story:** As a front-desk staff member, I want a structured patient intake workflow with consent capture and identity verification, so that new patients are registered completely and compliantly.

#### Acceptance Criteria

1. WHEN a new patient arrives, THE Registration_Service SHALL present a structured intake form capturing demographics, emergency contacts, medical history, allergies, current medications, and insurance information
2. WHEN a patient completes intake, THE Registration_Service SHALL capture informed consent with the patient's digital signature, consent type, and timestamp
3. WHEN identity verification is required, THE Registration_Service SHALL support capture of government-issued ID (photo upload) and record the verification status
4. WHEN insurance information is provided, THE Registration_Service SHALL capture the insurance provider, policy number, and card image
5. WHEN registration is complete, THE Registration_Service SHALL create a Patient record in the existing Patient model with all captured demographics and medical history
6. THE Registration_Service SHALL support partial registration allowing patients to complete remaining fields at subsequent visits
7. THE Registration_Service SHALL enforce tenant isolation using RLS and generate a unique medical record number per tenant

### Requirement 9: Billing and Insurance Claims

**User Story:** As a Clinic Administrator, I want to generate invoices and process insurance claims, so that the clinic can track revenue and manage reimbursements.

#### Acceptance Criteria

1. WHEN an encounter is completed, THE Billing_Service SHALL generate an invoice containing all billable items: consultation fees, procedures performed, lab tests ordered, and medications dispensed
2. THE Billing_Service SHALL support insurance claim generation for NHIS (Nigeria) and NHIF (Kenya) with the required claim format and coding
3. WHEN a payment is received, THE Billing_Service SHALL record the payment amount, method (cash, card, mobile money, insurance), and issue a receipt
4. THE Billing_Service SHALL track invoice status as: draft, sent, partially_paid, paid, overdue, or written_off
5. WHEN an insurance claim is submitted, THE Billing_Service SHALL track the claim status as: submitted, under_review, approved, partially_approved, denied, or paid
6. IF a claim is denied, THEN THE Billing_Service SHALL record the denial reason and allow resubmission with corrections
7. THE Billing_Service SHALL enforce tenant isolation using RLS and link invoices to the originating encounter and patient

### Requirement 10: Inpatient and Bed Management

**User Story:** As a Nurse, I want to manage ward assignments and track inpatient care activities, so that admitted patients receive coordinated care with proper documentation.

#### Acceptance Criteria

1. WHEN a patient is admitted, THE Bed_Management_Service SHALL assign the patient to an available bed in the appropriate ward and record the admission date, admitting clinician, and admission diagnosis
2. THE Bed_Management_Service SHALL maintain real-time bed availability showing occupied, available, reserved, and maintenance status per ward
3. WHILE a patient is admitted, THE Bed_Management_Service SHALL allow Nurses to record nursing notes with timestamp, note content, and recording nurse identity
4. WHILE a patient is admitted, THE Bed_Management_Service SHALL allow Nurses to chart vitals at configurable intervals and feed the vitals into the existing Measurement model
5. WHEN a Doctor initiates discharge, THE Bed_Management_Service SHALL generate a discharge plan containing discharge diagnosis, medications at discharge, follow-up appointments, and patient instructions
6. WHEN a patient is discharged, THE Bed_Management_Service SHALL update bed status to available and record the discharge date, discharge type (routine, against_medical_advice, transfer, deceased), and length of stay
7. THE Bed_Management_Service SHALL enforce tenant isolation using RLS and link admissions to the patient and the admitting encounter

### Requirement 11: FHIR R4 API Endpoints

**User Story:** As a system integrator, I want full FHIR R4 API endpoints for reading and writing clinical resources, so that external EMR systems can exchange data with PrescpHealth.

#### Acceptance Criteria

1. THE FHIR_API_Service SHALL expose RESTful endpoints for FHIR R4 resources: Patient, Encounter, Observation, MedicationRequest, DiagnosticReport, ServiceRequest, and Condition
2. THE FHIR_API_Service SHALL support FHIR search parameters for each resource type including _id, patient, date, status, and code
3. WHEN an external system sends a FHIR resource via POST or PUT, THE FHIR_API_Service SHALL validate the resource against the FHIR R4 schema and reject non-conformant resources with an OperationOutcome response
4. THE FHIR_API_Service SHALL support bulk data export using the FHIR Bulk Data Access specification for population-level data exchange
5. WHEN a clinical resource is created or updated internally, THE FHIR_API_Service SHALL support subscription notifications to registered external systems via webhooks
6. THE FHIR_API_Service SHALL authenticate external system requests using OAuth 2.0 client credentials and enforce tenant-scoped access
7. THE FHIR_API_Service SHALL parse incoming FHIR JSON resources into internal data models and print internal data models back to valid FHIR JSON (round-trip compatibility)

### Requirement 12: External EMR Integration

**User Story:** As a system administrator, I want connectors for OpenMRS, DHIS2, and generic FHIR-compliant systems, so that PrescpHealth can exchange data with existing health information systems in the region.

#### Acceptance Criteria

1. THE Integration_Service SHALL provide a connector for OpenMRS that synchronizes patient demographics, encounters, and observations bidirectionally
2. THE Integration_Service SHALL provide a connector for DHIS2 that exports aggregate health indicators and program data in the DHIS2-compatible format
3. THE Integration_Service SHALL provide a generic FHIR connector that communicates with any FHIR R4-compliant system using standard FHIR operations (read, search, create, update)
4. WHEN synchronization is triggered, THE Integration_Service SHALL perform conflict resolution using last-write-wins with full audit trail of conflicts detected and resolutions applied
5. IF an external system is unreachable during synchronization, THEN THE Integration_Service SHALL queue the pending changes and retry with exponential backoff (30 seconds, 2 minutes, 8 minutes, maximum 5 retries)
6. THE Integration_Service SHALL log all data exchanges with the external system identifier, direction (inbound or outbound), resource type, and outcome (success or failure) without logging PHI content
7. THE Integration_Service SHALL enforce tenant isolation ensuring each connector instance operates within a single tenant boundary

### Requirement 13: Multi-Tenant and Compliance Infrastructure

**User Story:** As a Super Admin, I want the EMR system to enforce multi-tenancy, HIPAA compliance, and comprehensive audit trails, so that each clinic's data is isolated and all access is traceable.

#### Acceptance Criteria

1. THE EMR_System SHALL enforce PostgreSQL Row-Level Security on every new table with tenant_id, following the same RLS pattern as existing modules (auth, audit, patients, measurements)
2. THE EMR_System SHALL log all create, read, update, and delete operations on clinical data to the existing AuditService with the action, resource_type, resource_id, user_id, and tenant_id
3. THE EMR_System SHALL apply soft-delete with 7-year retention on all clinical records and anonymize PHI fields upon soft deletion
4. THE EMR_System SHALL set Cache-Control headers to "no-store, no-cache, must-revalidate" on all API responses containing PHI
5. THE EMR_System SHALL validate all user input at the API boundary using Pydantic schemas and reject inputs that do not match expected patterns
6. THE EMR_System SHALL use the existing RBAC system to enforce role-based access: Doctors have full clinical access, Nurses have read and limited write access, Clinic_Admins have operational access, and Patient_Users have read-only access to their own records

### Requirement 14: Performance and Offline Capability

**User Story:** As a Clinician working in a low-bandwidth environment, I want the system to perform well on 3G connections and support basic offline access, so that I can continue providing care regardless of network conditions.

#### Acceptance Criteria

1. THE EMR_System SHALL return API responses for simple read operations within 200 milliseconds at the 95th percentile
2. THE EMR_System SHALL return API responses for list and search operations within 300 milliseconds at the 95th percentile
3. THE EMR_System SHALL use cursor-based pagination with a default page size of 25 and maximum of 100 records per response to minimize payload size
4. THE EMR_System SHALL compress all API responses using gzip or brotli encoding to reduce bandwidth consumption
5. WHILE the network connection is unavailable, THE EMR_System patient portal SHALL serve cached patient demographic and appointment data via service worker for read-only access
6. WHEN network connectivity is restored, THE EMR_System patient portal SHALL synchronize any queued actions with the server and resolve conflicts using server-authoritative timestamps
7. THE EMR_System SHALL implement database indexes on all foreign key columns and frequently queried fields to maintain query performance within budget

### Requirement 15: Internationalization

**User Story:** As a Clinician in a francophone or lusophone African country, I want the system to display in my preferred language, so that I can use the system effectively without language barriers.

#### Acceptance Criteria

1. THE EMR_System SHALL support English, French, and Portuguese as display languages from initial deployment
2. THE EMR_System SHALL use translation keys for all user-facing strings and resolve the display language based on the user's language preference stored in their profile
3. WHEN a translation key has no translation in the user's preferred language, THE EMR_System SHALL fall back to the English translation
4. THE EMR_System SHALL display clinical terminology (drug names, condition names, lab test names) using locale-specific display names mapped from their canonical codes (ATC, ICD-10, LOINC)
5. THE EMR_System SHALL format dates, times, and numbers according to the user's locale preference while storing all timestamps in UTC internally
6. THE EMR_System SHALL send notification content (SMS, email) in the recipient's preferred language using locale-specific notification templates

### Requirement 16: Integration with Existing Modules

**User Story:** As a developer, I want the EMR modules to integrate seamlessly with existing PrescpHealth modules, so that clinical data flows through the established pipelines for risk prediction and alerting.

#### Acceptance Criteria

1. WHEN a lab result is recorded, THE Lab_Order_Service SHALL create a Measurement record in the existing Measurement model with the appropriate measurement_type, value, and recorded_at fields
2. WHEN a prescription is written, THE Prescription_Service SHALL invoke the existing Drug Interaction engine check_ddi and check_dhi functions with the new medication and the patient's active medication list
3. WHEN a chronic condition diagnosis is recorded in an encounter, THE Encounter_Service SHALL update the patient's chronic_conditions JSONB field in the existing Patient model
4. THE EMR_System SHALL use the existing AuthService for authentication and the existing RBAC system for authorization on all new endpoints
5. THE EMR_System SHALL use the existing AuditService to log all clinical data access and modifications
6. WHEN a measurement is created from a lab result or inpatient vitals charting, THE EMR_System SHALL publish a MeasurementSaved domain event to trigger the existing risk computation pipeline
