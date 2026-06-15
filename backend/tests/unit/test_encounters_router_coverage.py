"""
Coverage tests: Encounters router_detail.py — endpoint function paths.

Tests call endpoint functions directly (bypassing HTTP/auth machinery) to cover
the ~40 uncovered statements in router_detail.py (currently 61%):
  - get_encounter
  - update_encounter
  - add_soap_note
  - record_diagnosis
  - record_procedure
  - discharge_encounter
  - _serialize_detail helper

All services and DB session are mocked — no real DB required.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_TEST_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
_TEST_ENCOUNTER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

_AUTH_CONTEXT = {
    "tenant_id": _TEST_TENANT_ID,
    "user_id": _TEST_USER_ID,
    "role": "Doctor",
}


def _make_encounter(**kw):
    """Return a mock Encounter ORM object."""
    enc = MagicMock()
    enc.id = kw.get("id", _TEST_ENCOUNTER_ID)
    enc.tenant_id = kw.get("tenant_id", _TEST_TENANT_ID)
    enc.patient_id = kw.get("patient_id", uuid.uuid4())
    enc.clinician_id = kw.get("clinician_id", _TEST_USER_ID)
    enc.encounter_class = kw.get("encounter_class", "outpatient")
    enc.status = kw.get("status", "in-progress")
    enc.chief_complaint = kw.get("chief_complaint", "Routine visit")
    enc.start_time = kw.get("start_time", datetime.now(timezone.utc))
    enc.end_time = kw.get("end_time", None)
    enc.fhir_json = kw.get("fhir_json", {})
    enc.soap_notes = kw.get("soap_notes", [])
    enc.diagnoses = kw.get("diagnoses", [])
    enc.procedures = kw.get("procedures", [])
    enc.created_at = kw.get("created_at", datetime.now(timezone.utc))
    return enc


def _make_soap_note(**kw):
    """Return a mock SOAPNote ORM object."""
    note = MagicMock()
    note.id = kw.get("id", uuid.uuid4())
    note.subjective = kw.get("subjective", "Patient reports fatigue")
    note.objective = kw.get("objective", "BP 120/80")
    note.assessment = kw.get("assessment", "Stable")
    note.plan = kw.get("plan", "Continue current plan")
    note.recorded_by = kw.get("recorded_by", _TEST_USER_ID)
    note.created_at = kw.get("created_at", datetime.now(timezone.utc))
    return note


def _make_diagnosis(**kw):
    """Return a mock Diagnosis ORM object."""
    dx = MagicMock()
    dx.id = kw.get("id", uuid.uuid4())
    dx.icd10_code = kw.get("icd10_code", "I10")
    dx.display_name = kw.get("display_name", "Hypertension")
    dx.is_chronic = kw.get("is_chronic", True)
    dx.is_primary = kw.get("is_primary", True)
    dx.fhir_json = kw.get("fhir_json", {})
    return dx


def _make_procedure(**kw):
    """Return a mock Procedure ORM object."""
    proc = MagicMock()
    proc.id = kw.get("id", uuid.uuid4())
    proc.code = kw.get("code", "A1234")
    proc.description = kw.get("description", "BP monitoring")
    proc.performed_at = kw.get("performed_at", datetime.now(timezone.utc))
    return proc


def _make_mock_request(**kw):
    """Return a mock FastAPI Request with state attributes."""
    req = MagicMock()
    req.state.request_id = kw.get("request_id", "test-req-001")
    return req


@asynccontextmanager
async def _async_db_ctx():
    """Async context manager yielding a reusable mock session."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    yield db


# ===========================================================================
# _serialize_detail helper — tested directly
# ===========================================================================
class TestSerializeDetail:
    """Verify _serialize_detail correctly builds nested encounter dict."""

    def test_serialize_detail_empty_collections(self):
        """_serialize_detail returns empty lists when encounter has no sub-records."""
        from app.modules.encounters.router_detail import _serialize_detail

        enc = _make_encounter(soap_notes=[], diagnoses=[], procedures=[])

        # _serialize_detail calls _serialize_encounter from router.py via local import
        with patch(
            "app.modules.encounters.router._serialize_encounter",
            return_value={"id": str(enc.id), "status": enc.status},
        ):
            result = _serialize_detail(enc)

        assert result["soap_notes"] == []
        assert result["diagnoses"] == []
        assert result["procedures"] == []

    def test_serialize_detail_with_soap_note(self):
        """_serialize_detail includes SOAP note data."""
        from app.modules.encounters.router_detail import _serialize_detail

        note = _make_soap_note()
        enc = _make_encounter(soap_notes=[note], diagnoses=[], procedures=[])

        with patch(
            "app.modules.encounters.router._serialize_encounter",
            return_value={"id": str(enc.id)},
        ):
            result = _serialize_detail(enc)

        assert len(result["soap_notes"]) == 1
        assert result["soap_notes"][0]["subjective"] == "Patient reports fatigue"
        assert result["soap_notes"][0]["objective"] == "BP 120/80"

    def test_serialize_detail_with_diagnosis(self):
        """_serialize_detail includes diagnosis data."""
        from app.modules.encounters.router_detail import _serialize_detail

        dx = _make_diagnosis()
        enc = _make_encounter(soap_notes=[], diagnoses=[dx], procedures=[])

        with patch(
            "app.modules.encounters.router._serialize_encounter",
            return_value={"id": str(enc.id)},
        ):
            result = _serialize_detail(enc)

        assert len(result["diagnoses"]) == 1
        assert result["diagnoses"][0]["icd10_code"] == "I10"
        assert result["diagnoses"][0]["is_chronic"] is True

    def test_serialize_detail_with_procedure(self):
        """_serialize_detail includes procedure data."""
        from app.modules.encounters.router_detail import _serialize_detail

        proc = _make_procedure()
        enc = _make_encounter(soap_notes=[], diagnoses=[], procedures=[proc])

        with patch(
            "app.modules.encounters.router._serialize_encounter",
            return_value={"id": str(enc.id)},
        ):
            result = _serialize_detail(enc)

        assert len(result["procedures"]) == 1
        assert result["procedures"][0]["code"] == "A1234"

    def test_serialize_detail_procedure_performed_at_iso(self):
        """_serialize_detail formats performed_at as ISO string."""
        from app.modules.encounters.router_detail import _serialize_detail

        ts = datetime(2025, 8, 1, 10, 0, tzinfo=timezone.utc)
        proc = _make_procedure(performed_at=ts)
        enc = _make_encounter(soap_notes=[], diagnoses=[], procedures=[proc])

        with patch(
            "app.modules.encounters.router._serialize_encounter",
            return_value={"id": str(enc.id)},
        ):
            result = _serialize_detail(enc)

        assert result["procedures"][0]["performed_at"] == ts.isoformat()

    def test_serialize_detail_soap_note_created_at_iso(self):
        """_serialize_detail formats created_at as ISO string for SOAP note."""
        from app.modules.encounters.router_detail import _serialize_detail

        ts = datetime(2025, 8, 1, 9, 30, tzinfo=timezone.utc)
        note = _make_soap_note(created_at=ts)
        enc = _make_encounter(soap_notes=[note], diagnoses=[], procedures=[])

        with patch(
            "app.modules.encounters.router._serialize_encounter",
            return_value={"id": str(enc.id)},
        ):
            result = _serialize_detail(enc)

        assert result["soap_notes"][0]["created_at"] == ts.isoformat()


# ===========================================================================
# Endpoint function tests — called directly to bypass HTTP/auth
# ===========================================================================

class TestGetEncounterEndpoint:
    """Verify get_encounter endpoint logic."""

    @pytest.mark.asyncio
    async def test_get_encounter_returns_200_json(self):
        """get_encounter endpoint returns JSONResponse with 200 when encounter found."""
        from app.modules.encounters.router_detail import get_encounter

        enc = _make_encounter()
        request = _make_mock_request()
        session_factory = MagicMock(return_value=_async_db_ctx())

        with patch(
            "app.modules.encounters.router_detail.get_session_factory",
            return_value=session_factory,
        ), patch(
            "app.modules.encounters.router_detail.set_tenant_context",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.router_detail._encounter_service.get_encounter",
            new_callable=AsyncMock,
            return_value=enc,
        ), patch(
            "app.modules.encounters.router_detail._serialize_detail",
            return_value={"id": str(enc.id), "status": "in-progress"},
        ):
            response = await get_encounter(
                request=request,
                encounter_id=enc.id,
                auth_context=_AUTH_CONTEXT,
            )

        assert response.status_code == 200
        import json
        body = json.loads(response.body)
        assert body["success"] is True
        assert body["data"]["id"] == str(enc.id)

    @pytest.mark.asyncio
    async def test_get_encounter_hipaa_headers(self):
        """get_encounter endpoint includes HIPAA security headers."""
        from app.modules.encounters.router_detail import get_encounter

        enc = _make_encounter()
        request = _make_mock_request()
        session_factory = MagicMock(return_value=_async_db_ctx())

        with patch(
            "app.modules.encounters.router_detail.get_session_factory",
            return_value=session_factory,
        ), patch(
            "app.modules.encounters.router_detail.set_tenant_context",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.router_detail._encounter_service.get_encounter",
            new_callable=AsyncMock,
            return_value=enc,
        ), patch(
            "app.modules.encounters.router_detail._serialize_detail",
            return_value={"id": str(enc.id)},
        ):
            response = await get_encounter(
                request=request,
                encounter_id=enc.id,
                auth_context=_AUTH_CONTEXT,
            )

        # HIPAA headers include cache-control and pragma no-cache
        assert "cache-control" in response.headers or "pragma" in response.headers


class TestUpdateEncounterEndpoint:
    """Verify update_encounter endpoint logic."""

    @pytest.mark.asyncio
    async def test_update_encounter_returns_200(self):
        """update_encounter returns 200 with encounter id."""
        from app.modules.encounters.router_detail import update_encounter
        from app.modules.encounters.schemas import EncounterUpdate

        enc = _make_encounter()
        request = _make_mock_request()
        session_factory = MagicMock(return_value=_async_db_ctx())
        body = EncounterUpdate(encounter_class="inpatient")

        with patch(
            "app.modules.encounters.router_detail.get_session_factory",
            return_value=session_factory,
        ), patch(
            "app.modules.encounters.router_detail.set_tenant_context",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.router_detail._encounter_service.update_encounter",
            new_callable=AsyncMock,
            return_value=enc,
        ), patch(
            "app.modules.encounters.router_detail.encounter_to_fhir",
            return_value={},
        ):
            response = await update_encounter(
                request=request,
                encounter_id=enc.id,
                body=body,
                auth_context=_AUTH_CONTEXT,
            )

        assert response.status_code == 200


class TestAddSoapNoteEndpoint:
    """Verify add_soap_note endpoint logic."""

    @pytest.mark.asyncio
    async def test_add_soap_note_returns_201(self):
        """add_soap_note returns 201 with note id."""
        from app.modules.encounters.router_detail import add_soap_note
        from app.modules.encounters.schemas import SOAPNoteCreate

        enc = _make_encounter()
        note = _make_soap_note()
        request = _make_mock_request()
        session_factory = MagicMock(return_value=_async_db_ctx())
        body = SOAPNoteCreate(
            subjective="Patient reports fatigue",
            objective="BP 120/80",
            assessment="Stable",
            plan="Continue current plan",
        )

        with patch(
            "app.modules.encounters.router_detail.get_session_factory",
            return_value=session_factory,
        ), patch(
            "app.modules.encounters.router_detail.set_tenant_context",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.router_detail._soap_service.add_soap_note",
            new_callable=AsyncMock,
            return_value=note,
        ):
            response = await add_soap_note(
                request=request,
                encounter_id=enc.id,
                body=body,
                auth_context=_AUTH_CONTEXT,
            )

        assert response.status_code == 201
        import json
        body_data = json.loads(response.body)
        assert body_data["success"] is True
        assert "id" in body_data["data"]


class TestRecordDiagnosisEndpoint:
    """Verify record_diagnosis endpoint logic."""

    @pytest.mark.asyncio
    async def test_record_diagnosis_returns_201(self):
        """record_diagnosis returns 201 with diagnosis id."""
        from app.modules.encounters.router_detail import record_diagnosis
        from app.modules.encounters.schemas import DiagnosisCreate

        enc = _make_encounter()
        dx = _make_diagnosis()
        request = _make_mock_request()
        session_factory = MagicMock(return_value=_async_db_ctx())
        body = DiagnosisCreate(icd10_code="I10", is_chronic=True, is_primary=True)

        with patch(
            "app.modules.encounters.router_detail.get_session_factory",
            return_value=session_factory,
        ), patch(
            "app.modules.encounters.router_detail.set_tenant_context",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.router_detail._encounter_service.get_encounter",
            new_callable=AsyncMock,
            return_value=enc,
        ), patch(
            "app.modules.encounters.router_detail._diagnosis_service.record_diagnosis",
            new_callable=AsyncMock,
            return_value=dx,
        ), patch(
            "app.modules.encounters.router_detail.diagnosis_to_fhir",
            return_value={},
        ):
            response = await record_diagnosis(
                request=request,
                encounter_id=enc.id,
                body=body,
                auth_context=_AUTH_CONTEXT,
            )

        assert response.status_code == 201


class TestRecordProcedureEndpoint:
    """Verify record_procedure endpoint logic."""

    @pytest.mark.asyncio
    async def test_record_procedure_returns_201(self):
        """record_procedure returns 201 with procedure id."""
        from app.modules.encounters.router_detail import record_procedure
        from app.modules.encounters.schemas import ProcedureCreate

        enc = _make_encounter()
        request = _make_mock_request()
        session_factory = MagicMock(return_value=_async_db_ctx())
        body = ProcedureCreate(
            code="A1234",
            description="BP monitoring",
            performed_at=datetime.now(timezone.utc),
        )

        mock_procedure = _make_procedure()

        with patch(
            "app.modules.encounters.router_detail.get_session_factory",
            return_value=session_factory,
        ), patch(
            "app.modules.encounters.router_detail.set_tenant_context",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.router_detail._encounter_service.get_encounter",
            new_callable=AsyncMock,
            return_value=enc,
        ), patch(
            "app.modules.encounters.router_detail.Procedure",
            return_value=mock_procedure,
        ) if False else patch(
            "app.modules.encounters.procedure_model.Procedure",
            return_value=mock_procedure,
        ):
            response = await record_procedure(
                request=request,
                encounter_id=enc.id,
                body=body,
                auth_context=_AUTH_CONTEXT,
            )

        assert response.status_code == 201


class TestDischargeEncounterEndpoint:
    """Verify discharge_encounter endpoint logic."""

    @pytest.mark.asyncio
    async def test_discharge_encounter_returns_200(self):
        """discharge_encounter returns 200 with completed status."""
        from app.modules.encounters.router_detail import discharge_encounter
        from app.modules.encounters.schemas import DischargeRequest

        enc = _make_encounter()
        completed_enc = _make_encounter(status="completed")
        request = _make_mock_request()
        session_factory = MagicMock(return_value=_async_db_ctx())
        body = DischargeRequest(discharge_notes="Discharged in stable condition")

        with patch(
            "app.modules.encounters.router_detail.get_session_factory",
            return_value=session_factory,
        ), patch(
            "app.modules.encounters.router_detail.set_tenant_context",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.encounters.router_detail._encounter_service.complete_encounter",
            new_callable=AsyncMock,
            return_value=completed_enc,
        ), patch(
            "app.modules.encounters.router_detail.encounter_to_fhir",
            return_value={},
        ):
            response = await discharge_encounter(
                request=request,
                encounter_id=enc.id,
                body=body,
                auth_context=_AUTH_CONTEXT,
            )

        assert response.status_code == 200
        import json
        body_data = json.loads(response.body)
        assert body_data["data"]["status"] == "completed"
