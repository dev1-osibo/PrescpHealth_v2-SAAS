"""
Tests for app.modules.task_status and app.core.tasks_tracker.
Covers exceptions, schemas, models, TaskStatusService, and BackgroundTaskTracker.

All tests use synthetic data only. No real PHI. DB is mocked.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

from app.modules.task_status.exceptions import TaskStatusError, TaskNotFoundError


def test_task_status_error_default():
    """TaskStatusError has a default message."""
    err = TaskStatusError()
    assert "task" in str(err).lower()
    assert isinstance(err, Exception)


def test_task_status_error_custom_message():
    """TaskStatusError stores custom message."""
    err = TaskStatusError("task polling failed")
    assert err.message == "task polling failed"


def test_task_not_found_error():
    """TaskNotFoundError includes task_id in message."""
    task_id = str(uuid.uuid4())
    err = TaskNotFoundError(task_id)
    assert task_id in str(err)
    assert isinstance(err, TaskStatusError)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

from app.modules.task_status.schemas import TaskStatusResponse, TaskStatusEnvelope


def test_task_status_response_valid():
    """TaskStatusResponse serializes all required fields."""
    now = datetime.now(timezone.utc)
    task_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    resp = TaskStatusResponse(
        id=task_id,
        tenant_id=tenant_id,
        task_type="clinical_pdf",
        status="running",
        retry_count=0,
        max_retries=3,
        celery_task_id=None,
        created_at=now,
        started_at=now,
        completed_at=None,
        result=None,
        error=None,
    )
    assert resp.task_type == "clinical_pdf"
    assert resp.status == "running"
    assert resp.retry_count == 0
    assert resp.max_retries == 3


def test_task_status_response_completed():
    """TaskStatusResponse stores result payload for completed task."""
    now = datetime.now(timezone.utc)
    resp = TaskStatusResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        task_type="report_generate",
        status="completed",
        retry_count=1,
        max_retries=3,
        celery_task_id="celery-abc-123",
        created_at=now,
        started_at=now,
        completed_at=now,
        result={"file_key": "reports/test-001.pdf"},
        error=None,
    )
    assert resp.status == "completed"
    assert resp.result["file_key"] == "reports/test-001.pdf"
    assert resp.celery_task_id == "celery-abc-123"


def test_task_status_response_failed():
    """TaskStatusResponse stores error message for failed task."""
    now = datetime.now(timezone.utc)
    resp = TaskStatusResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        task_type="risk_score_batch",
        status="failed",
        retry_count=3,
        max_retries=3,
        created_at=now,
        error="Synthetic test error message",
    )
    assert resp.status == "failed"
    assert resp.error == "Synthetic test error message"


def test_task_status_envelope():
    """TaskStatusEnvelope wraps TaskStatusResponse in success envelope."""
    now = datetime.now(timezone.utc)
    data = TaskStatusResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        task_type="clinical_pdf",
        status="pending",
        retry_count=0,
        max_retries=3,
        created_at=now,
    )
    env = TaskStatusEnvelope(data=data, meta={"request_id": "test", "timestamp": now.isoformat()})
    assert env.success is True
    assert env.data.status == "pending"


# ---------------------------------------------------------------------------
# BackgroundTask Model
# ---------------------------------------------------------------------------

from app.modules.task_status.models import BackgroundTask


def test_background_task_model_instantiation():
    """BackgroundTask can be instantiated with all required fields."""
    task = BackgroundTask(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        task_type="clinical_pdf",
        status="pending",
        params={"patient_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert task.task_type == "clinical_pdf"
    assert task.status == "pending"


def test_background_task_model_with_result():
    """BackgroundTask stores optional result and error fields."""
    task = BackgroundTask(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        task_type="risk_score_batch",
        status="completed",
        params={},
        result={"records_processed": 42},
        error=None,
    )
    assert task.result["records_processed"] == 42


def test_background_task_model_with_celery_id():
    """BackgroundTask stores optional celery_task_id."""
    task = BackgroundTask(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        task_type="report_generate",
        status="running",
        params={},
        celery_task_id="celery-task-xyz-001",
        retry_count=0,
    )
    assert task.celery_task_id == "celery-task-xyz-001"


# ---------------------------------------------------------------------------
# TaskStatusService
# ---------------------------------------------------------------------------

from app.modules.task_status.service import TaskStatusService


def _make_task_status_svc(mock_db=None, tenant_id=None):
    """Helper: create TaskStatusService with mocked deps."""
    return TaskStatusService(
        db=mock_db or AsyncMock(),
        audit_service=AsyncMock(),
        request_id="test-task-req",
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_get_task_status_found():
    """get_task_status returns BackgroundTask when found."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_task = MagicMock(spec=BackgroundTask)
    mock_task.id = task_id
    mock_task.task_type = "clinical_pdf"
    mock_task.status = "completed"
    mock_task.retry_count = 0
    mock_task.max_retries = 3

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_task
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_task_status_svc(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc.get_task_status(task_id=task_id)

    assert result is mock_task


@pytest.mark.asyncio
async def test_get_task_status_not_found():
    """get_task_status raises TaskNotFoundError when task not found."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_task_status_svc(mock_db=mock_db)

    with pytest.raises(TaskNotFoundError):
        await svc.get_task_status(task_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_list_tenant_tasks_returns_all():
    """list_tenant_tasks returns list of tasks for tenant."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_task1 = MagicMock()
    mock_task2 = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_task1, mock_task2]
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_task_status_svc(mock_db=mock_db, tenant_id=tenant_id)
    result = await svc.list_tenant_tasks(status_filter=None, limit=50)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_tenant_tasks_with_status_filter():
    """list_tenant_tasks applies status filter when provided."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_task_status_svc(mock_db=mock_db)
    result = await svc.list_tenant_tasks(status_filter="running", limit=20)

    assert result == []
    mock_db.scalars.assert_called_once()


@pytest.mark.asyncio
async def test_list_tenant_tasks_empty():
    """list_tenant_tasks returns empty list when no tasks exist."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    svc = _make_task_status_svc(mock_db=mock_db)
    result = await svc.list_tenant_tasks(status_filter=None)

    assert result == []


# ---------------------------------------------------------------------------
# BackgroundTaskTracker (app.core.tasks_tracker)
# ---------------------------------------------------------------------------

from app.core.tasks_tracker import BackgroundTaskTracker


def _make_tracker(mock_db=None, tenant_id=None):
    """Helper: create BackgroundTaskTracker with mocked DB."""
    return BackgroundTaskTracker(
        db=mock_db or AsyncMock(),
        tenant_id=tenant_id or uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_tracker_create_task_returns_uuid_string():
    """create_task returns a UUID string for the new task."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.id = task_id

    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=mock_task)

    # Simulate flush setting the id
    def fake_add(obj):
        obj.id = task_id

    mock_db.add.side_effect = fake_add

    tracker = _make_tracker(mock_db=mock_db, tenant_id=tenant_id)
    result = await tracker.create_task(
        task_type="clinical_pdf",
        params={"patient_id": "00000000-0000-0000-0000-000000000001"},
    )

    # Should be a UUID string
    assert isinstance(result, str)
    uuid.UUID(result)  # Validates it's a proper UUID


@pytest.mark.asyncio
async def test_tracker_update_status_to_running():
    """update_status sets started_at when transitioning to running."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.status = "pending"
    mock_task.started_at = None

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_task
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()

    tracker = _make_tracker(mock_db=mock_db, tenant_id=tenant_id)
    await tracker.update_status(task_id=str(task_id), status="running")

    assert mock_task.status == "running"
    assert mock_task.started_at is not None


@pytest.mark.asyncio
async def test_tracker_update_status_to_completed():
    """update_status sets completed_at when transitioning to completed."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.status = "running"
    mock_task.started_at = datetime.now(timezone.utc)
    mock_task.completed_at = None

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_task
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()

    tracker = _make_tracker(mock_db=mock_db, tenant_id=tenant_id)
    await tracker.update_status(
        task_id=str(task_id),
        status="completed",
        result={"file_key": "reports/synth-001.pdf"},
    )

    assert mock_task.status == "completed"
    assert mock_task.completed_at is not None
    assert mock_task.result == {"file_key": "reports/synth-001.pdf"}


@pytest.mark.asyncio
async def test_tracker_update_status_to_failed():
    """update_status sets completed_at and error when transitioning to failed."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.status = "running"
    mock_task.started_at = datetime.now(timezone.utc)
    mock_task.completed_at = None

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_task
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()

    tracker = _make_tracker(mock_db=mock_db, tenant_id=tenant_id)
    await tracker.update_status(
        task_id=str(task_id),
        status="failed",
        error="Synthetic task failure",
    )

    assert mock_task.status == "failed"
    assert mock_task.completed_at is not None
    assert mock_task.error == "Synthetic task failure"


@pytest.mark.asyncio
async def test_tracker_update_status_task_not_found():
    """update_status silently logs warning when task not found — no exception raised."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    tracker = _make_tracker(mock_db=mock_db)

    # Should not raise
    await tracker.update_status(task_id=str(uuid.uuid4()), status="running")


@pytest.mark.asyncio
async def test_tracker_update_status_running_does_not_reset_started_at():
    """update_status does not overwrite started_at if already set."""
    mock_db = AsyncMock()
    task_id = uuid.uuid4()
    original_started = datetime(2026, 1, 1, tzinfo=timezone.utc)

    mock_task = MagicMock()
    mock_task.status = "retrying"
    mock_task.started_at = original_started  # Already set

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_task
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()

    tracker = _make_tracker(mock_db=mock_db)
    await tracker.update_status(task_id=str(task_id), status="running")

    # started_at should not be overwritten since it was already set
    assert mock_task.started_at == original_started


@pytest.mark.asyncio
async def test_tracker_get_status_returns_dict():
    """get_status returns a dict with task fields when task exists."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_task = MagicMock()
    mock_task.id = task_id
    mock_task.task_type = "risk_score_batch"
    mock_task.status = "completed"
    mock_task.retry_count = 0
    mock_task.max_retries = 3
    mock_task.celery_task_id = None
    mock_task.error = None
    mock_task.started_at = now
    mock_task.completed_at = now
    mock_task.created_at = now

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_task
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    tracker = _make_tracker(mock_db=mock_db, tenant_id=tenant_id)
    result = await tracker.get_status(task_id=str(task_id))

    assert result is not None
    assert result["task_type"] == "risk_score_batch"
    assert result["status"] == "completed"
    assert "task_id" in result


@pytest.mark.asyncio
async def test_tracker_get_status_not_found_returns_none():
    """get_status returns None when task does not exist in this tenant."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    tracker = _make_tracker(mock_db=mock_db)
    result = await tracker.get_status(task_id=str(uuid.uuid4()))

    assert result is None


@pytest.mark.asyncio
async def test_tracker_mark_retry_increments_count():
    """mark_retry increments retry_count and sets status to retrying."""
    mock_db = AsyncMock()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.status = "failed"
    mock_task.retry_count = 1

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_task
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()

    tracker = _make_tracker(mock_db=mock_db)
    await tracker.mark_retry(task_id=str(task_id))

    assert mock_task.retry_count == 2
    assert mock_task.status == "retrying"


@pytest.mark.asyncio
async def test_tracker_mark_retry_task_not_found():
    """mark_retry silently logs warning when task not found — no exception raised."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    tracker = _make_tracker(mock_db=mock_db)

    # Should not raise
    await tracker.mark_retry(task_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_tracker_get_task_invalid_uuid_returns_none():
    """_get_task returns None for malformed UUID string."""
    mock_db = AsyncMock()
    tracker = _make_tracker(mock_db=mock_db)

    result = await tracker._get_task("not-a-uuid-string")

    assert result is None
    mock_db.scalars.assert_not_called()


@pytest.mark.asyncio
async def test_tracker_status_transitions_pending_to_running_to_completed():
    """BackgroundTaskTracker supports full status lifecycle: pending→running→completed."""
    mock_db = AsyncMock()
    task_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_task = MagicMock()
    mock_task.status = "pending"
    mock_task.started_at = None
    mock_task.completed_at = None

    call_count = 0

    def scalars_side_effect(*args, **kwargs):
        result = MagicMock()
        result.first.return_value = mock_task
        return result

    mock_db.scalars = AsyncMock(side_effect=scalars_side_effect)
    mock_db.commit = AsyncMock()

    tracker = _make_tracker(mock_db=mock_db)

    # Step 1: transition to running
    await tracker.update_status(str(task_id), "running")
    assert mock_task.status == "running"
    assert mock_task.started_at is not None

    # Step 2: transition to completed
    mock_task.started_at = now  # Simulate already set
    await tracker.update_status(str(task_id), "completed", result={"rows": 10})
    assert mock_task.status == "completed"
    assert mock_task.completed_at is not None


@pytest.mark.asyncio
async def test_tracker_status_transitions_pending_to_running_to_failed():
    """BackgroundTaskTracker supports failure lifecycle: pending→running→failed."""
    mock_db = AsyncMock()
    task_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_task = MagicMock()
    mock_task.status = "pending"
    mock_task.started_at = None
    mock_task.completed_at = None

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_task
    mock_db.scalars = AsyncMock(return_value=mock_scalars)
    mock_db.commit = AsyncMock()

    tracker = _make_tracker(mock_db=mock_db)

    # Transition to running
    await tracker.update_status(str(task_id), "running")
    mock_task.started_at = now  # Simulate already set

    # Transition to failed
    await tracker.update_status(str(task_id), "failed", error="Worker crashed")
    assert mock_task.status == "failed"
    assert mock_task.error == "Worker crashed"
