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
Global model manager - loads models once at startup
"""
import structlog

logger = structlog.get_logger(__name__)

from app.services.florence_service import FlorenceService

# Global singleton instance
_florence_service = None


def get_florence_service() -> FlorenceService:
    """Get or create the global Florence service instance"""
    global _florence_service
    if _florence_service is None:
        _florence_service = FlorenceService()
        _florence_service.load_model()
    return _florence_service


def is_florence_available() -> bool:
    """Check if Florence service is loaded and ready"""
    global _florence_service
    return _florence_service is not None and _florence_service.model is not None


def get_model_status() -> dict:
    """Return the loading status of all models."""
    global _florence_service
    loaded = _florence_service is not None and _florence_service.model is not None
    return {
        "loaded": loaded,
        "florence": "loaded" if loaded else "not_loaded",
    }


def initialize_models():
    """Initialize all models at startup"""
    logger.info("Initializing models at startup...")
    try:
        get_florence_service()
        logger.info("Models initialized successfully!")
    except Exception as e:
        logger.error(
            "Failed to initialize models - Florence pipeline will be unavailable",
            error=str(e),
            error_type=type(e).__name__
        )
        # Don't re-raise - allow app to start without models
        # Users can still use Claude pipeline or export existing data
