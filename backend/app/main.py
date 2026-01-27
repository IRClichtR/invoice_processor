# Copyright 2026 Floriane TUERNAL SABOTINOV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Invoice Processor FastAPI Application

Main application module that configures and runs the FastAPI server.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.core.config import settings
from app.db.base import init_db, SessionLocal
from app.api import invoices, api_keys, health
from app.services.model_manager import initialize_models
from app.services.cleanup_service import CleanupService
from app.services.api_key_service import ApiKeyService

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # === STARTUP ===
    logger.info(
        "Starting application",
        mode="production" if settings.is_production_mode() else "development",
        data_dir=str(settings.DATA_DIR)
    )

    # Initialize database
    logger.info("Initializing database...", path=str(settings.DATA_SUBDIR / "invoices.db"))
    init_db(reset=False)

    # Run cleanup of expired jobs
    logger.info("Running cleanup of expired jobs...")
    cleanup_service = CleanupService()
    db = SessionLocal()
    try:
        result = cleanup_service.full_cleanup(db)
        if result['total_files_deleted'] > 0 or result['expired_jobs']['jobs_cleaned'] > 0:
            logger.info(
                "Startup cleanup completed",
                jobs_cleaned=result['expired_jobs']['jobs_cleaned'],
                files_deleted=result['total_files_deleted']
            )
    except Exception as e:
        logger.warning("Cleanup failed on startup", error=str(e))
    finally:
        db.close()

    # Initialize models
    logger.info("Initializing models...", cache_dir=str(settings.MODEL_CACHE_DIR))
    initialize_models()

    # Handle API key service tasks
    logger.info("Checking encryption key rotation...")
    api_key_service = ApiKeyService()
    db = SessionLocal()
    try:
        # Check and perform encryption key rotation if needed
        if api_key_service.check_and_perform_key_rotation(db):
            logger.info("Encryption key rotation completed successfully")

        # Log API key status
        status = api_key_service.get_all_status(db)
        anthropic_status = status.get('anthropic', {})
        if anthropic_status.get('valid'):
            logger.info("Anthropic API key is configured and valid")
        elif anthropic_status.get('configured'):
            logger.warning(
                "Anthropic API key is configured but invalid",
                error=anthropic_status.get('error')
            )
        else:
            logger.info("Anthropic API key not configured - Claude pipeline unavailable")
    except Exception as e:
        logger.warning("API key service startup tasks failed", error=str(e))
    finally:
        db.close()

    logger.info("Application startup complete")

    yield  # Application runs here

    # === SHUTDOWN ===
    logger.info("Application shutting down...")

    # Cleanup temp files
    try:
        cleanup_service = CleanupService()
        db = SessionLocal()
        try:
            cleanup_service.cleanup_temp_files(str(settings.TEMP_DIR))
            logger.info("Temp files cleaned up")
        finally:
            db.close()
    except Exception as e:
        logger.warning("Cleanup failed on shutdown", error=str(e))

    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(invoices.router, prefix="/api/v1", tags=["invoices"])
app.include_router(api_keys.router, prefix="/api/v1", tags=["api-keys"])


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Invoice Processor API",
        "version": settings.APP_VERSION,
        "mode": "production" if settings.is_production_mode() else "development"
    }


# Keep /health at root level for simple health checks
@app.get("/health")
async def health_check():
    """Simple health check endpoint at root level."""
    return {"status": "healthy"}
