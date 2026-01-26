"""
Health check endpoints for the Invoice Processor API.

Provides endpoints for:
- Basic health check (for Tauri process monitoring)
- Detailed health check (for debugging)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.base import get_db
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """
    Basic health check endpoint.

    Returns a simple status for quick liveness checks.
    Used by Tauri to verify the backend is running.
    """
    return {"status": "healthy"}


@router.get("/health/detailed")
async def detailed_health_check(db: Session = Depends(get_db)):
    """
    Detailed health check with component status.

    Checks:
    - Database connectivity
    - Path accessibility
    - Model loading status
    """
    health_status = {
        "status": "healthy",
        "mode": "production" if settings.is_production_mode() else "development",
        "version": settings.APP_VERSION,
        "components": {}
    }

    # Check database
    try:
        db.execute(text("SELECT 1"))
        health_status["components"]["database"] = {
            "status": "healthy",
            "path": str(settings.DATA_SUBDIR / "invoices.db")
        }
    except Exception as e:
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"

    # Check paths
    path_validation = settings.validate_paths()
    health_status["components"]["paths"] = {
        "status": "healthy" if path_validation["valid"] else "unhealthy",
        "data_dir": str(settings.DATA_DIR),
        "errors": path_validation.get("errors", [])
    }
    if not path_validation["valid"]:
        health_status["status"] = "degraded"

    # Check model status (if model manager is available)
    try:
        from app.services.model_manager import get_model_status
        model_status = get_model_status()
        health_status["components"]["models"] = {
            "status": "healthy" if model_status.get("loaded") else "not_loaded",
            "details": model_status
        }
    except Exception as e:
        health_status["components"]["models"] = {
            "status": "unknown",
            "error": str(e)
        }

    return health_status


@router.get("/health/paths")
async def paths_info():
    """
    Get information about configured paths.

    Useful for debugging path-related issues.
    """
    return settings.get_paths_info()
