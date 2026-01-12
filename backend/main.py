import argparse
import os

import structlog
import uvicorn
from app.api import invoices
from app.core.config import settings
from app.db.base import init_db
from app.services.model_manager import initialize_models
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()

app = FastAPI(
    title=settings.APP_NAME, version=settings.APP_VERSION, debug=settings.DEBUG
)


# Initialize database and models at startup
@app.on_event("startup")
async def startup_event():
    logger.info("Initializing database...")
    init_db()
    logger.info("Initializing models...")
    initialize_models()


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


@app.get("/")
async def root():
    return {"message": "Invoice Processor API", "version": settings.APP_VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/api/shutdown")
def shutdown():
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description="Invoicator Backend")
    parser.add_argument(
        "--port", type=int, default=8745, help="Server should run on this port"
    )
    parser.add_argument(
        "--data_dir", type=str, default=None, help="Directory to store uploaded files"
    )
    args = parser.parse_args()

    # Create upload directory
    logger.info("Setting up upload directory...")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    if args.data_dir:
        settings.UPLOAD_DIR = args.data_dir

    logger.info(
        f"Starting server on port {args.port} with data directory {settings.UPLOAD_DIR}"
    )
    uvicorn.run(
        app, host="127.0.0.1", port=args.port, log_level="info", access_log=False
    )


if __name__ == "__main__":
    main()
