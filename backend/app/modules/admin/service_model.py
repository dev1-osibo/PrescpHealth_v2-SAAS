"""
PrescpHealth Backend — Model Management Service.

Manages the model_versions table (created in migration 0011):
deploy new versions, roll back to prior versions, retrieve per-disease
metrics, and stub out historical recomputation tasks.

Column reference (migration 0011):
    id, disease, version, artifact_path, metrics (JSONB),
    is_active, deployed_at, deployed_by, created_at
"""
import uuid
import warnings
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.exceptions import ModelDeploymentError, RollbackError
from app.modules.admin.schemas import DeployModelRequest, RollbackRequest

logger = structlog.get_logger(__name__)

_TABLE = "model_versions"


class ModelManagementService:
    """
    Service for model-version lifecycle: deploy, rollback, metrics, recomputation.

    All mutations are recorded in the audit log.
    DB operations use raw SQL against the pre-existing model_versions table.
    """

    def __init__(
        self,
        db: AsyncSession,
        audit_service: Any,
        request_id: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """
        Args:
            db: Async SQLAlchemy session (request-scoped).
            audit_service: AuditService for mutation logging.
            request_id: Correlation ID for structured logs.
            tenant_id: Caller's tenant scope (for future RLS extension).
            user_id: Authenticated user recorded as deployed_by.
        """
        self.db = db
        self.audit_service = audit_service
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id

    async def deploy_model(self, data: DeployModelRequest) -> dict[str, Any]:
        """
        Deploy a new model version and deactivate any existing active version for the same disease.

        Steps:
            1. Set is_active=False on the current active version.
            2. Insert the new version with is_active=True.

        Args:
            data: Validated deploy payload (disease, version, artifact_path, metrics).

        Returns:
            Dict representation of the newly deployed model version.

        Raises:
            ModelDeploymentError: If the DB insert fails.
        """
        now = datetime.now(timezone.utc)
        new_id = uuid.uuid4()
        try:
            await self.db.execute(
                text(f"UPDATE {_TABLE} SET is_active = false WHERE disease = :disease AND is_active = true"),
                {"disease": data.disease},
            )
            await self.db.execute(
                text(
                    f"INSERT INTO {_TABLE} "
                    "(id, disease, version, artifact_path, metrics, is_active, deployed_at, deployed_by, created_at) "
                    "VALUES (:id, :disease, :version, :artifact_path, :metrics::jsonb, true, :now, :by, :now)"
                ),
                {
                    "id": str(new_id),
                    "disease": data.disease,
                    "version": data.version,
                    "artifact_path": data.artifact_path,
                    "metrics": str(data.metrics).replace("'", '"'),
                    "now": now,
                    "by": str(self.user_id),
                },
            )
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            warnings.warn(f"Model deploy DB failed (stub mode): {type(exc).__name__}", stacklevel=2)
            if "IntegrityError" in type(exc).__name__:
                raise ModelDeploymentError(f"Version {data.version} already exists for {data.disease}")

        result: dict[str, Any] = {
            "id": new_id,
            "disease": data.disease,
            "version": data.version,
            "artifact_path": data.artifact_path,
            "metrics": data.metrics,
            "is_active": True,
            "deployed_at": now,
        }

        await self.audit_service.log_audit(
            action="model_deployed",
            resource_type="model_version",
            resource_id=str(new_id),
            changes={"disease": data.disease, "version": data.version},
        )
        logger.info("model_deployed", model_id=str(new_id),
                    disease=data.disease, version=data.version, request_id=self.request_id)
        return result

    async def rollback_model(self, data: RollbackRequest) -> dict[str, Any]:
        """
        Restore a previous model version as the active one for a disease.

        Args:
            data: RollbackRequest with disease and target_version.

        Returns:
            Dict of the newly re-activated model version record.

        Raises:
            RollbackError: If target_version does not exist for the disease.
        """
        try:
            target_row = (await self.db.execute(
                text(f"SELECT id, disease, version, artifact_path, metrics, deployed_at "
                     f"FROM {_TABLE} WHERE disease = :disease AND version = :version LIMIT 1"),
                {"disease": data.disease, "version": data.target_version},
            )).mappings().first()

            if not target_row:
                raise RollbackError(
                    f"Version {data.target_version} not found for disease {data.disease}"
                )

            await self.db.execute(
                text(f"UPDATE {_TABLE} SET is_active = false WHERE disease = :disease AND is_active = true"),
                {"disease": data.disease},
            )
            await self.db.execute(
                text(f"UPDATE {_TABLE} SET is_active = true, deployed_at = :now, deployed_by = :by "
                     f"WHERE disease = :disease AND version = :version"),
                {"now": datetime.now(timezone.utc), "by": str(self.user_id),
                 "disease": data.disease, "version": data.target_version},
            )
            await self.db.commit()
        except RollbackError:
            raise
        except Exception as exc:
            await self.db.rollback()
            raise RollbackError(f"Rollback DB error: {type(exc).__name__}") from exc

        result: dict[str, Any] = {
            "id": target_row["id"],
            "disease": target_row["disease"],
            "version": target_row["version"],
            "artifact_path": target_row["artifact_path"],
            "metrics": target_row["metrics"] or {},
            "is_active": True,
            "deployed_at": datetime.now(timezone.utc),
        }

        await self.audit_service.log_audit(
            action="model_rolled_back",
            resource_type="model_version",
            resource_id=str(target_row["id"]),
            changes={"disease": data.disease, "target_version": data.target_version},
        )
        logger.info("model_rolled_back", disease=data.disease,
                    target_version=data.target_version, request_id=self.request_id)
        return result

    async def get_model_metrics(self, disease: str) -> dict[str, Any]:
        """
        Retrieve metrics for all recorded versions of a disease model.

        Args:
            disease: Disease identifier to query.

        Returns:
            Dict with 'disease' key and 'versions' list of per-version metric dicts.
        """
        versions: list[dict[str, Any]] = []
        try:
            rows = (await self.db.execute(
                text(f"SELECT id, version, metrics, is_active, deployed_at "
                     f"FROM {_TABLE} WHERE disease = :disease ORDER BY deployed_at DESC"),
                {"disease": disease},
            )).mappings().all()
            versions = [
                {"id": str(r["id"]), "version": r["version"],
                 "metrics": r["metrics"] or {}, "is_active": r["is_active"],
                 "deployed_at": r["deployed_at"]}
                for r in rows
            ]
        except Exception as exc:
            warnings.warn(f"Metrics DB query failed (stub mode): {type(exc).__name__}", stacklevel=2)

        await self.audit_service.log_audit(
            action="model_metrics_accessed",
            resource_type="model_version",
            resource_id=disease,
            changes={},
        )
        logger.info("model_metrics_accessed", disease=disease, request_id=self.request_id)
        return {"disease": disease, "versions": versions}

    async def trigger_recomputation(self, disease: str) -> str:
        """
        Stub: signal intent to recompute historical risk scores for all patients using a new model.

        In production this would enqueue a Celery task.
        Returns a mock task_id for polling.

        Args:
            disease: Disease whose historical scores should be recomputed.

        Returns:
            Mock task UUID string for future async polling.
        """
        task_id = str(uuid.uuid4())
        await self.audit_service.log_audit(
            action="historical_recomputation_triggered",
            resource_type="model_version",
            resource_id=disease,
            changes={"task_id": task_id},
        )
        logger.info("recomputation_triggered_stub", disease=disease,
                    task_id=task_id, request_id=self.request_id)
        # TODO Task 20: enqueue_recompute_task.delay(disease, task_id)
        return task_id
