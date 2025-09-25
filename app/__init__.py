import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Lazy imports within create_app to avoid ImportError during initial scaffolding
# and to keep module import side-effects minimal.

def create_app() -> FastAPI:
    """
    FastAPI application factory.
    Wires routers, initializes database, and registers lifecycle events.
    """
    app = FastAPI(
        title="Notification Service",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Health endpoints
    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        # In future: verify DB connectivity, worker liveness, Redis availability, etc.
        return {"status": "ready"}

    # Startup / Shutdown events
    @app.on_event("startup")
    async def on_startup():
        # Initialize DB
        try:
            from .database import init_db
            init_db()
        except Exception as e:
            # Ensure startup errors are visible in logs
            print(f"[startup] Database initialization failed: {e}")

        # Start background services (queue workers, scheduler) when implemented
        # These will be no-ops until services are created.
        try:
            from .services.queue_service import start_queue_workers
            await start_queue_workers()
        except Exception as e:
            print(f"[startup] Queue workers not started (likely not implemented yet): {e}")

        try:
            from .services.scheduler_service import start_scheduler
            await start_scheduler()
        except Exception as e:
            print(f"[startup] Scheduler not started (likely not implemented yet): {e}")

    @app.on_event("shutdown")
    async def on_shutdown():
        try:
            from .services.queue_service import stop_queue_workers
            await stop_queue_workers()
        except Exception as e:
            print(f"[shutdown] Queue workers stop encountered an issue: {e}")

        try:
            from .services.scheduler_service import stop_scheduler
            await stop_scheduler()
        except Exception as e:
            print(f"[shutdown] Scheduler stop encountered an issue: {e}")

    # Routers
    try:
        from .api.notifications import router as notifications_router
        app.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
    except Exception as e:
        print(f"[routers] Notifications router not included yet: {e}")

    try:
        from .api.templates import router as templates_router
        app.include_router(templates_router, prefix="/templates", tags=["templates"])
    except Exception as e:
        print(f"[routers] Templates router not included yet: {e}")

    try:
        from .api.analytics import router as analytics_router
        app.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
    except Exception as e:
        print(f"[routers] Analytics router not included yet: {e}")

    # Default exception handler for generic errors (optional; can be replaced with structured logging)
    @app.exception_handler(Exception)
    async def default_exception_handler(request, exc):
        # Avoid leaking internals in production; keep simple for now
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app
