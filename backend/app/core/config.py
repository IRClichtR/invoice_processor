import os
import json
from typing import Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Constants
CONFIG_DIR = Path.home() / ".config" / "parsefacture"
ENCRYPTION_KEY_FILE = CONFIG_DIR / "encryption.key"
ENCRYPTION_META_FILE = CONFIG_DIR / "encryption.meta.json"
KEY_ROTATION_DAYS = 30


def _get_encryption_metadata() -> dict:
    """Get encryption key metadata (creation date, etc.)"""
    if ENCRYPTION_META_FILE.exists():
        try:
            return json.loads(ENCRYPTION_META_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_encryption_metadata(metadata: dict) -> None:
    """Save encryption key metadata"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ENCRYPTION_META_FILE.write_text(json.dumps(metadata, indent=2))
    ENCRYPTION_META_FILE.chmod(0o600)


def _generate_new_key() -> str:
    """Generate a new Fernet encryption key"""
    try:
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode('utf-8')
    except ImportError:
        import secrets
        import base64
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')


def _key_needs_rotation() -> bool:
    """Check if the encryption key is older than KEY_ROTATION_DAYS"""
    metadata = _get_encryption_metadata()
    created_at_str = metadata.get('created_at')
    if not created_at_str:
        return False  # No metadata = new key, don't rotate yet

    try:
        created_at = datetime.fromisoformat(created_at_str)
        return datetime.utcnow() - created_at > timedelta(days=KEY_ROTATION_DAYS)
    except (ValueError, TypeError):
        return False


def _get_or_create_encryption_key() -> str:
    """
    Get encryption key from env var or generate and store one.

    The key is stored in ~/.config/parsefacture/encryption.key
    Metadata is stored in ~/.config/parsefacture/encryption.meta.json
    """
    # Check env var first
    env_key = os.getenv("API_KEY_ENCRYPTION_KEY")
    if env_key and len(env_key) >= 32:
        return env_key

    # Use local file for auto-generated key
    if ENCRYPTION_KEY_FILE.exists():
        return ENCRYPTION_KEY_FILE.read_text().strip()

    # Generate new key
    new_key = _generate_new_key()

    # Store key and metadata
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ENCRYPTION_KEY_FILE.write_text(new_key)
    ENCRYPTION_KEY_FILE.chmod(0o600)

    _save_encryption_metadata({
        'created_at': datetime.utcnow().isoformat(),
        'version': 1
    })

    return new_key


def check_and_rotate_encryption_key() -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if encryption key needs rotation and perform rotation if needed.

    Returns:
        Tuple of (rotation_needed, old_key, new_key)
        If rotation is not needed, returns (False, None, None)
    """
    # Don't rotate if using env var
    if os.getenv("API_KEY_ENCRYPTION_KEY"):
        return (False, None, None)

    if not _key_needs_rotation():
        return (False, None, None)

    if not ENCRYPTION_KEY_FILE.exists():
        return (False, None, None)

    # Get old key
    old_key = ENCRYPTION_KEY_FILE.read_text().strip()

    # Generate new key
    new_key = _generate_new_key()

    # Store new key
    ENCRYPTION_KEY_FILE.write_text(new_key)
    ENCRYPTION_KEY_FILE.chmod(0o600)

    # Update metadata
    metadata = _get_encryption_metadata()
    metadata['created_at'] = datetime.utcnow().isoformat()
    metadata['version'] = metadata.get('version', 1) + 1
    metadata['last_rotation'] = datetime.utcnow().isoformat()
    _save_encryption_metadata(metadata)

    return (True, old_key, new_key)


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
