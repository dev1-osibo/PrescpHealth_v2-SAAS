"""
PrescpHealth Backend — Modules Package.

Contains all domain modules organized by business capability:
- auth: Authentication, sessions, RBAC
- patients: Patient profile management
- measurements: Clinical measurement entry and validation
- risk_engine: Disease risk score computation
- forecast_engine: Health trajectory forecasting
- ai_assistant: LLM-powered clinical assistant
- drug_interactions: Medication safety engine
- alerts: Alert generation and notification dispatch
- reports: PDF/CSV report generation
- population: Population-level analytics
- admin: Tenant and model management

Each module is self-contained with its own:
- models.py: SQLAlchemy database models
- service.py: Business logic
- schemas.py: Pydantic request/response schemas
- router.py: FastAPI route definitions
- tasks.py: Celery background tasks (if applicable)
- README.md: Module documentation
"""
