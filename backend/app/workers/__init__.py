"""
PrescpHealth Backend — Workers Package.

Contains Celery worker configuration and background task definitions.
Celery handles all async processing that shouldn't block API responses:
- Risk score computation (ML inference, ~5s)
- Forecast generation (time-series models, ~10s)
- Notification dispatch (email/SMS/WhatsApp via external APIs)
- Report generation (PDF/CSV, ~15s)
- Population metrics refresh (aggregation queries, ~60s)
"""
