"""
Additional exception handler coverage: 5xx logging path and Pydantic RequestValidationError.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from app.core.exception_handlers import register_exception_handlers
from app.core.exceptions import PrescpHealthError


# A custom 5xx error to exercise the server_error logging branch
class _ServerExplodedError(PrescpHealthError):
    def __init__(self):
        super().__init__(
            message="A downstream service exploded",
            code="DOWNSTREAM_FAILURE",
            status_code=503,
        )


class _BodyModel(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    age: int = Field(..., ge=0, le=150)


def _create_error_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise-5xx")
    async def raise_5xx():
        raise _ServerExplodedError()

    @app.post("/validate-body")
    async def validate_body(body: _BodyModel):
        return JSONResponse({"ok": True})

    return app


@pytest.mark.asyncio
async def test_5xx_app_error_logs_as_server_error():
    """PrescpHealthError with status >=500 should still produce a JSON envelope."""
    app = _create_error_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-5xx")

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "DOWNSTREAM_FAILURE"
    assert body["error"]["message"] == "A downstream service exploded"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_pydantic_validation_error_returns_400_envelope():
    """RequestValidationError handler converts Pydantic errors to envelope."""
    app = _create_error_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/validate-body", json={"name": "", "age": -1})

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert isinstance(body["error"]["details"], list)
    assert len(body["error"]["details"]) >= 1
    # Each detail must NOT include the actual input value (PHI safety)
    for detail in body["error"]["details"]:
        assert "input" not in detail
        assert "field" in detail
        assert "type" in detail
        assert "message" in detail


@pytest.mark.asyncio
async def test_pydantic_validation_error_missing_field():
    """Missing required field produces a validation envelope error."""
    app = _create_error_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/validate-body", json={"name": "Alice"})

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    # At least one detail about the missing field
    fields = [d["field"] for d in body["error"]["details"]]
    assert any("age" in f for f in fields)
