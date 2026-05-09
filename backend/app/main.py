"""
PrescpHealth Backend - FastAPI Application Factory.

This module creates and configures the FastAPI application instance.
Uses the factory pattern for testability and clean resource management.
"""

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application lifecycle: startup and shutdown.

    Startup: Initialize DB pool, Redis connection, log environment info.
    Shutdown: Close connections gracefully, log clean stop.
    """
    settings = get_settings()
    logger.info(
        "application_starting",
        app_env=settings.app_env,
        app_name=settings.app_name,
        api_version=settings.api_version,
    )
    # DB and Redis init added in Tasks 1.3 and 1.4
    logger.info("application_ready")
    yield
    logger.info("application_shutting_down")
    logger.info("application_stopped")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns a fully configured app with CORS, request ID tracking,
    PHI cache-control headers, exception handlers, and health check.
    Module routers are registered in Task 33 (integration wiring).
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="AI-powered clinical decision support for disease risk prediction",
        version="0.1.0",
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        lifespan=lifespan,
    )

    # CORS - allows frontend SPA to communicate with API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next) -> Response:
        """Attach unique request_id for end-to-end correlation tracking."""
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def add_phi_cache_headers(request: Request, call_next) -> Response:
        """Prevent browser/CDN caching of PHI responses (HIPAA requirement)."""
        response = await call_next(request)
        if request.url.path.startswith(f"/api/{settings.api_version}"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all handler. Returns generic 500 with request_id.
        Never exposes stack traces or PHI to the client.
        """
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "unhandled_exception",
            request_id=request_id,
            error_type=type(exc).__name__,
            path=str(request.url.path),
            method=request.method,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred. Please try again.",
                    "details": [],
                    "request_id": request_id,
                },
            },
        )

    @app.get("/health", tags=["system"])
    async def health_check() -> dict:
        """Health check for load balancers. No auth required."""
        return {
            "status": "healthy",
            "service": settings.app_name,
            "version": "0.1.0",
            "environment": settings.app_env,
        }

    return app


# Application instance - uvicorn entry point
app = create_app()
