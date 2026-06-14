# Appointments Module (Staging)

Handles appointment booking, scheduling, waitlist management, and recurring appointment generation.

## Module Structure

| File | Purpose |
|------|---------|
| `enums.py` | `AppointmentType`, `AppointmentStatus`, `WaitlistStatus` |
| `exceptions.py` | `AppointmentNotFoundError`, `DoubleBookingError`, `InvalidAppointmentStateError` |
| `models.py` | `Appointment`, `Waitlist` SQLAlchemy ORM models |
| `schemas.py` | Pydantic request/response schemas |
| `service.py` | `AppointmentService` — booking, rescheduling, check-in, completion |
| `service_waitlist.py` | `WaitlistService` — add/promote waitlist entries |
| `service_recurrence.py` | `RecurrenceService` — generate recurring appointment series |
| `router.py` | FastAPI router — 7 endpoints |

## Migration
`0018_appointments_tables.py` — creates `appointments` and `waitlist` tables.

## Endpoints

| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| POST | `/api/v1/appointments` | Nurse, Clinic_Admin | Book appointment |
| GET | `/api/v1/appointments` | Doctor, Nurse, Clinic_Admin | List with filters |
| GET | `/api/v1/appointments/{id}` | Doctor, Nurse, Clinic_Admin | Get detail |
| PUT | `/api/v1/appointments/{id}` | Nurse, Clinic_Admin | Reschedule |
| DELETE | `/api/v1/appointments/{id}` | Nurse, Clinic_Admin | Cancel |
| POST | `/api/v1/appointments/waitlist` | Nurse, Clinic_Admin | Add to waitlist |
| GET | `/api/v1/patients/{id}/appointments` | Doctor, Nurse, Clinic_Admin | Patient history |

## Double-Booking Prevention
`AppointmentService._check_double_booking()` queries for overlapping scheduled/confirmed/checked-in/in-progress appointments for the same clinician before booking or rescheduling.

## Waitlist Promotion
When an appointment is cancelled, `WaitlistService.promote_from_waitlist()` is automatically called to find and offer the slot to the highest-priority (lowest `priority` integer) waiting patient for the same clinician.

## Recurring Appointments
`RecurrenceService.generate_recurring()` accepts a rule dict `{frequency, interval, count}` and generates N-1 child appointments linked via `parent_appointment_id`.

## HIPAA Compliance
- All responses include `Cache-Control: no-store` headers
- No PHI in log messages — UUIDs only
- All mutations audit-logged via `AuditService`
