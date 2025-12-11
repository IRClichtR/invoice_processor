"""
Global model manager - loads models once at startup
"""

from app.services.qwen_service import QwenService

# Global singleton instances
_qwen_service = None


def get_qwen_service() -> QwenService:
    """Get or create the global Qwen service instance"""
    global _qwen_service
    if _qwen_service is None:
        _qwen_service = QwenService()
        _qwen_service.load_model()  # Load once at first access
    return _qwen_service


def initialize_models():
    """Initialize all models at startup"""
    print("Initializing models at startup...")
    get_qwen_service()
    print("Models initialized successfully!")
