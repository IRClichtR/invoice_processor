import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    # Database configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./invoice_db.sqlite")

    # Application settings
    APP_NAME: str = os.getenv("APP_NAME", "Invoice Processor API")
    APP_VERSION: str = os.getenv("APP_VERSION", "1.0.0")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    # File upload settings
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    MAX_UPLOAD_SIZE: int = int(os.getenv("MAX_UPLOAD_SIZE", "52428800"))

    # Florence-2 model settings (CPU-only)
    FLORENCE_MODEL: str = os.getenv("FLORENCE_MODEL", "microsoft/Florence-2-base")

    # Model cache directory (persistent on user machine)
    MODEL_CACHE_DIR: str = os.path.expanduser("~/.cache/invoice_processor/models")

    # Claude API settings (optional - for low-quality/handwritten document processing)
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")

    # Claude Vision settings
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
    CLAUDE_MAX_TOKENS: int = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))

    # OCR Quality thresholds
    OCR_LOW_CONFIDENCE_THRESHOLD: float = float(os.getenv("OCR_LOW_CONFIDENCE_THRESHOLD", "80.0"))

    def has_valid_claude_api_key(self) -> bool:
        """Check if a valid Claude API key is configured"""
        if not self.ANTHROPIC_API_KEY:
            return False
        key = self.ANTHROPIC_API_KEY.strip()
        # Reject placeholder values
        if key in ("your_anthropic_api_key_here", ""):
            return False
        return key.startswith("sk-ant-") and len(key) > 20


settings = Settings()
