#!/usr/bin/env python3

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
Entry point for the Invoice Processor backend server.

This script is the main entry point for PyInstaller packaging.
It can be run directly in development or bundled as an executable.

Environment variables:
    DATA_DIR: Base directory for all application data (required in production)
    PORT: Server port (default: 8000)
    MODEL_CACHE_DIR: Override model cache location
    DEBUG: Enable debug mode (default: false)

Usage:
    # Development (uses OS-specific default DATA_DIR)
    python run_server.py

    # Production (Tauri sets DATA_DIR)
    DATA_DIR=/path/to/data python run_server.py
"""

import sys
import shutil
import signal
import structlog

# Configure logging before anything else
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

logger = structlog.get_logger("run_server")


def check_system_dependencies():
    """Check that required system tools are available, bundled or on PATH."""
    from app.core.bundled_deps import get_tesseract_cmd, get_poppler_path

    bundled_tesseract = get_tesseract_cmd()
    bundled_poppler = get_poppler_path()

    deps = {
        "tesseract": {
            "description": "Tesseract OCR (needed for local text extraction)",
            "bundled": bundled_tesseract,
        },
        "pdftoppm": {
            "description": "poppler-utils (needed for PDF to image conversion)",
            "bundled": bundled_poppler,
        },
        "pdfinfo": {
            "description": "poppler-utils (needed for PDF page info)",
            "bundled": bundled_poppler,
        },
    }
    for binary, info in deps.items():
        if info["bundled"]:
            logger.info("Using bundled dependency", binary=binary, path=info["bundled"])
        elif shutil.which(binary) is not None:
            logger.debug("System dependency found on PATH", binary=binary)
        else:
            logger.warning(
                "System dependency not found",
                binary=binary,
                description=info["description"],
            )


def main():
    """Main entry point for the server."""
    from app.core.bundled_deps import configure_library_paths
    configure_library_paths()

    check_system_dependencies()

    # Import settings first to ensure directories are created
    from app.core.config import settings

    logger.info(
        "Starting Invoice Processor Backend",
        mode="production" if settings.is_production_mode() else "development",
        data_dir=str(settings.DATA_DIR),
        port=settings.PORT,
        debug=settings.DEBUG
    )

    # Log path information
    paths_info = settings.get_paths_info()
    logger.debug("Configured paths", **paths_info)

    # Validate paths
    validation = settings.validate_paths()
    if not validation['valid']:
        logger.error("Path validation failed", errors=validation['errors'])
        sys.exit(1)

    # Import uvicorn after settings are loaded
    import uvicorn

    # Import the FastAPI app
    from app.main import app

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal", signal=signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the server
    logger.info("Starting uvicorn server", host=settings.HOST, port=settings.PORT)

    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level="debug" if settings.DEBUG else "info",
        access_log=settings.DEBUG
    )


if __name__ == "__main__":
    main()
