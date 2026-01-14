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


def initialize_models():
    """Initialize all models at startup"""
    logger.info("Initializing models at startup...")
    get_florence_service()
    logger.info("Models initialized successfully!")
