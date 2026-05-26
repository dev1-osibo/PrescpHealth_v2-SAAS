"""
PrescpHealth Backend — Lab Orders Module.

Manages the full laboratory order lifecycle: ordering tests, tracking
specimen collection, recording results, and integrating with the
risk computation pipeline via Measurement records.

Module Responsibilities:
- Lab test ordering with LOINC code validation
- Status tracking (ordered → specimen_collected → in_progress → resulted)
- Result recording with abnormal flag computation
- Measurement creation for risk engine integration
- Alert generation for abnormal results
- FHIR R4 ServiceRequest/Observation mapping

Integration Points:
- CodeCatalog: LOINC code validation
- Measurements: Creates Measurement records from lab results
- Alerts: Triggers alerts on abnormal results
- Encounters: Links orders to patient visits (optional)
- FHIR API: Exposes orders/results as ServiceRequest/Observation

HIPAA Compliance:
- All tables use RLS for tenant isolation
- Lab values are PHI — encrypted at rest, never logged
- Soft delete only with 7-year retention

Usage:
    from app.modules.lab_orders.models import LabOrder, LabResult
    from app.modules.lab_orders.enums import LabOrderStatus, LabPriority
"""

from app.modules.lab_orders.enums import LabOrderStatus, LabPriority
from app.modules.lab_orders.exceptions import (
    InvalidLabOrderStatusTransitionError,
    LabOrderAlreadyResultedError,
    LabOrderNotFoundError,
)
from app.modules.lab_orders.models import LabOrder, LabResult

__all__ = [
    "LabOrder",
    "LabResult",
    "LabOrderStatus",
    "LabPriority",
    "LabOrderNotFoundError",
    "InvalidLabOrderStatusTransitionError",
    "LabOrderAlreadyResultedError",
]
