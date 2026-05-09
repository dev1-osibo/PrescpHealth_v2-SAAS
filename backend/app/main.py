"""
PrescpHealth Backend — FastAPI Application Factory.

This module creates and configures the FastAPI application instance.
Uses the factory pattern so the app can be configured differently
for testing vs production without import side effects.

The lifespan context manager handles startup/shutdown of async resources
(database connections, Redis pools) ensuring clean resource management.

Architecture:
    create_app() -> FastAPI instance with:
        - CORS middleware (origins from config, not hardcoded)
        - Request ID middleware (correlation tracking across async flows)
        - PHI cache-control headers (HIPAA: no browser caching of patient data)
        - Exception handlers (consistent error format, no stack traces exposed)
        - Health check endpoint (for load balancers, no auth required)
        - Router registration (added in Task 33 — integration wiring)
"""

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings

# ---------------------------------------------------------------------------
# Structured logger — never logs PHI, only request metadata
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — manages startup and shutdown of async resources
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application lifecycle: startup and shutdown.

    Startup:
        - Initialize database connection pool (Task 1.3)
        - Initialize Redis connection (Task 1.4)
        - Log application start with environment info

    Shutdown:
        - Close database connections gracefully
        - Close Redis connections
        - Log clean shutdown

    Why lifespan instead of on_event("startup"):
        FastAPI's lifespan is the modern pattern — it guarantees cleanup
        runs even on unclean shutdown, and makes testing easier since
        resources are scoped to the app instance, not the module.
    """
    settings = get_settings()

    # --- Startup ---
    logger.info(
        "application_starting",
        app_env=settings.app_env,
        app_name=settings.app_name,
        api_version=settings.api_version,
    )

    # Database and Redis initialization will be wired here in lifespan
    # once init_db() and init_redis() are integrated (Tasks 1.3, 1.4)
    logger.info("application_ready")

    yield

    # --- Shutdown ---
    # Close connections gracefully so no requests are dropped mid-flight
    logger.info("application_shutting_down")
    logger.info("application_stopped")


# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    This factory function builds the complete application with all middleware,
    exception handlers, and configuration applied. It does NOT register module
    routers — those are added in the integration wiring task (Task 33).

    Returns:
        FastAPI: Fully configured application instance ready to serve requests.

    Usage:
        # In production (uvicorn entry point)
        app = create_app()

        # In tests (override settings, no side effects)
        app = create_app()
        client = AsyncClient(app=app)
    """
    settings = get_settings()

    # Create FastAPI instance with metadata for OpenAPI docs
    app = FastAPI(
        title=settings.app_name,
        description="AI-powered clinical decision support for disease risk prediction",
        version="0.1.0",
        # Disable docs in production — exposing the API schema publicly
        # is a security risk (attackers can map all endpoints)
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        lifespan=lifespan,
    )

    # --- CORS Middleware ---
    # Allows the frontend SPA (running on a different port/domain) to
    # communicate with the API. In production, restrict to the exact
    # frontend domain only — never use "*" for a HIPAA platform.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    # --- Request ID Middleware ---
    # Generates a unique correlation ID for every request. This ID flows
    # through the entire chain: API -> Service -> Celery -> Event Handler
    # enabling end-to-end tracing without exposing PHI in logs.
    @app.middleware("http")
    async def add_request_id(request: Request, call_next) -> Response:
        """Attach unique request_id for end-to-end correlation tracking."""
        request_id = str(uuid.uuid4())
        # Store on request.state so downstream code (services, handlers) can access it
        request.state.request_id = request_id

        response = await call_next(request)

        # Return request_id in response header so frontend can reference it
        # in support tickets ("my request ID was X, what happened?")
        response.headers["X-Request-ID"] = request_id
        return response

    # --- PHI Cache-Control Middleware ---
    # HIPAA requirement: patient data must NEVER be stored in browser cache
    # or intermediate CDN/proxy caches. This header ensures browsers don't
    # retain API responses containing PHI after the page is closed.
    @app.middleware("http")
    async def add_phi_cache_headers(request: Request, call_next) -> Response:
        """Prevent browser/CDN caching of PHI responses (HIPAA requirement)."""
        response = await call_next(request)

        # Only apply to API routes — static frontend assets CAN be cached
        if request.url.path.startswith(f"/api/{settings.api_version}"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        return response

    # --- Global Exception Handler ---
    # Consistent error response format across all unhandled errors.
    # CRITICAL: Never expose stack traces or internal details to the client.
    # Attackers use error details to map internal architecture.
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all handler for unhandled errors.

        Returns a generic 500 error with request_id for support correlation.
        Logs the full error context server-side (without PHI) for debugging.
        Never exposes stack traces, internal paths, or error details to client.
        """
        # Use getattr with fallback because this handler might fire before
        # the request_id middleware runs (e.g., during middleware itself)
        request_id = getattr(request.state, "request_id", "unknown")

        # Log full error context server-side — includes error type and path
        # but NEVER patient data, measurement values, or other PHI
        logger.error(
            "unhandled_exception",
            request_id=request_id,
            error_type=type(exc).__name__,
            path=str(request.url.path),
            method=request.method,
        )

        # Return generic message — don't tell the client WHAT went wrong internally
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

    # --- Health Check ---
    # Simple endpoint for load balancers and monitoring systems.
    # Does NOT require authentication (load balancer needs to check without a token).
    # Does NOT check downstream dependencies — those have separate readiness probes.
    @app.get("/health", tags=["system"])
    async def health_check() -> dict:
        """Health check for load balancers and monitoring. No auth required."""
        return {
            "status": "healthy",
            "service": settings.app_name,
            "version": "0.1.0",
            "environment": settings.app_env,
        }

    return app


# ---------------------------------------------------------------------------
# Application instance — used by uvicorn as entry point
# Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000
# ---------------------------------------------------------------------------
app = create_app()
