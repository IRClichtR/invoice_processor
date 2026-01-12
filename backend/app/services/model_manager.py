"""
Global model manager - loads models once at startup

Models:
- Florence-2: For printed/digital documents
- VisionOCR: For handwritten documents
"""
import structlog

logger = structlog.get_logger(__name__)

from app.services.florence_service import FlorenceService
from app.services.visionocr_service import VisionOCRService

# Global singleton instances
_florence_service = None
_visionocr_service = None


def get_florence_service() -> FlorenceService:
    """Get or create the global Florence service instance (for printed documents)"""
    global _florence_service
    if _florence_service is None:
        _florence_service = FlorenceService()
        _florence_service.load_model()
    return _florence_service


def get_visionocr_service() -> VisionOCRService:
    """Get or create the global VisionOCR service instance (for handwritten documents)"""
    global _visionocr_service
    if _visionocr_service is None:
        _visionocr_service = VisionOCRService()
        _visionocr_service.load_model()
    return _visionocr_service


def initialize_models():
    """Initialize all models at startup"""
    logger.info("Initializing models at startup...")
    logger.info("Loading Florence-2 model for printed documents...")
    get_florence_service()
    logger.info("Loading VisionOCR model for handwritten documents...")
    get_visionocr_service()
    logger.info("All models initialized successfully!")
