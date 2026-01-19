from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.base import init_db, SessionLocal
from app.api import invoices, api_keys
from app.services.model_manager import initialize_models
from app.services.cleanup_service import CleanupService
from app.services.claude_vision_service import ClaudeVisionService, CLAUDE_API_CONSOLE_URL
import os
import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()

# Create upload directory
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

# Initialize database and models at startup
@app.on_event("startup")
async def startup_event():
    logger.info("Initializing database...")
    init_db(reset=True)  # Reset DB to apply schema changes

    logger.info("Creating temp directory...")
    os.makedirs(settings.TEMP_DIR, exist_ok=True)

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

    logger.info("Initializing models...")
    initialize_models()

    logger.info("Checking Anthropic API key...")
    claude_service = ClaudeVisionService()
    api_status = claude_service.check_api_key_status()
    if api_status['valid']:
        logger.info("Anthropic API key is valid and ready for use")
    elif api_status['configured']:
        logger.warning(
            "Anthropic API key is configured but invalid",
            error=api_status['error'],
            console_url=CLAUDE_API_CONSOLE_URL
        )
    else:
        logger.info(
            "Anthropic API key not configured - Claude pipeline will be unavailable",
            console_url=CLAUDE_API_CONSOLE_URL
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
app.include_router(invoices.router, prefix="/api/v1", tags=["invoices"])
app.include_router(api_keys.router, prefix="/api/v1", tags=["api-keys"])


@app.get("/")
async def root():
    return {"message": "Invoice Processor API", "version": settings.APP_VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
