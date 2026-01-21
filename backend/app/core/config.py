import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _get_or_create_encryption_key() -> str:
    """
    Get encryption key from env var or generate and store one.

    The key is stored in ~/.config/parsefacture/encryption.key
    """
    # Check env var first
    env_key = os.getenv("API_KEY_ENCRYPTION_KEY")
    if env_key and len(env_key) >= 32:
        return env_key

    # Use local file for auto-generated key
    config_dir = Path.home() / ".config" / "parsefacture"
    key_file = config_dir / "encryption.key"

    if key_file.exists():
        return key_file.read_text().strip()

    # Generate new key
    try:
        from cryptography.fernet import Fernet
        new_key = Fernet.generate_key().decode('utf-8')
    except ImportError:
        # Fallback if cryptography not installed yet
        import secrets
        import base64
        new_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')

    # Store key
    config_dir.mkdir(parents=True, exist_ok=True)
    key_file.write_text(new_key)
    key_file.chmod(0o600)  # Restrict permissions

    return new_key


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

    # Temp directory for analysis job files
    TEMP_DIR: str = os.getenv("TEMP_DIR", "/tmp/parsefacture")

    # Job expiration time in seconds (default: 1 hour)
    JOB_EXPIRATION_SECONDS: int = int(os.getenv("JOB_EXPIRATION_SECONDS", "3600"))

    # Permanent document storage directory
    DOCUMENTS_DIR: str = os.getenv("DOCUMENTS_DIR", "documents")

    # Encryption key for API keys (auto-generated if not set)
    API_KEY_ENCRYPTION_KEY: str = _get_or_create_encryption_key()

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
