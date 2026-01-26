"""
Application configuration with DATA_DIR-based path management.

Supports two modes:
- Development: DATA_DIR not set, uses OS-specific default
- Production (Tauri sidecar): DATA_DIR set by Tauri

All paths are derived from DATA_DIR to ensure proper isolation.
"""

import os
import sys
import json
from typing import Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta

# Constants (not configurable)
KEY_ROTATION_DAYS = 30
MAX_UPLOAD_SIZE = 52428800  # 50MB
DEFAULT_HOST = "127.0.0.1"  # Default: localhost for security (override with HOST env var for Docker)


def _get_os_default_data_dir() -> Path:
    """
    Get OS-specific default data directory.

    - Linux: ~/.local/share/Invoicator
    - macOS: ~/Library/Application Support/Invoicator
    - Windows: %APPDATA%/Invoicator
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Invoicator"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "Invoicator"
    else:  # Linux and other Unix-like
        return Path.home() / ".local" / "share" / "Invoicator"


def _get_data_dir() -> Path:
    """
    Get DATA_DIR from environment or use OS-specific default.

    In production (Tauri sidecar), DATA_DIR is set by Tauri.
    In development, uses OS-specific default.
    """
    env_data_dir = os.environ.get("DATA_DIR")
    if env_data_dir:
        return Path(env_data_dir)
    return _get_os_default_data_dir()


class Settings:
    """
    Application settings with all paths derived from DATA_DIR.

    Environment variables:
        DATA_DIR: Base directory for all application data (optional, has OS default)
        PORT: Server port (optional, default 8000)
        MODEL_CACHE_DIR: Override model cache location (optional)
        DEBUG: Enable debug mode (optional, default false)
    """

    def __init__(self):
        # Determine if running in production mode (DATA_DIR explicitly set)
        self._data_dir_from_env = os.environ.get("DATA_DIR") is not None

        # Base data directory
        self.DATA_DIR: Path = _get_data_dir()

        # Derived directories
        self.CONFIG_DIR: Path = self.DATA_DIR / "config"
        self.DATA_SUBDIR: Path = self.DATA_DIR / "data"
        self.UPLOAD_DIR: Path = self.DATA_DIR / "uploads"
        self.TEMP_DIR: Path = self.DATA_DIR / "temp"
        self.DOCUMENTS_DIR: Path = self.DATA_DIR / "documents"
        self.LOG_DIR: Path = self.DATA_DIR / "logs"

        # Encryption key paths (in CONFIG_DIR)
        self.ENCRYPTION_KEY_FILE: Path = self.CONFIG_DIR / "encryption.key"
        self.ENCRYPTION_META_FILE: Path = self.CONFIG_DIR / "encryption.meta.json"

        # Database URL (derived from DATA_DIR)
        self.DATABASE_URL: str = f"sqlite:///{self.DATA_SUBDIR / 'invoices.db'}"

        # Server settings
        self.HOST: str = os.environ.get("HOST", DEFAULT_HOST)
        self.PORT: int = int(os.environ.get("PORT", "8000"))

        # Application settings
        self.APP_NAME: str = "Invoice Processor API"
        self.APP_VERSION: str = "1.0.0"
        self.DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"

        # Model settings (fixed values)
        self.FLORENCE_MODEL: str = "microsoft/Florence-2-base"
        self.CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
        self.CLAUDE_MAX_TOKENS: int = 4096

        # Model cache directory (can be overridden)
        model_cache_env = os.environ.get("MODEL_CACHE_DIR")
        if model_cache_env:
            self.MODEL_CACHE_DIR: Path = Path(model_cache_env)
        else:
            self.MODEL_CACHE_DIR: Path = self.DATA_DIR / "models"

        # File upload settings (fixed)
        self.MAX_UPLOAD_SIZE: int = MAX_UPLOAD_SIZE

        # OCR settings
        self.OCR_LOW_CONFIDENCE_THRESHOLD: float = 80.0

        # Job settings
        self.JOB_EXPIRATION_SECONDS: int = 3600  # 1 hour

        # Encryption key (auto-generated if not exists)
        self.API_KEY_ENCRYPTION_KEY: str = self._get_or_create_encryption_key()

        # Create necessary directories
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create all necessary directories if they don't exist."""
        directories = [
            self.DATA_DIR,
            self.CONFIG_DIR,
            self.DATA_SUBDIR,
            self.UPLOAD_DIR,
            self.TEMP_DIR,
            self.DOCUMENTS_DIR,
            self.LOG_DIR,
            self.MODEL_CACHE_DIR,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def _get_encryption_metadata(self) -> dict:
        """Get encryption key metadata (creation date, etc.)"""
        if self.ENCRYPTION_META_FILE.exists():
            try:
                return json.loads(self.ENCRYPTION_META_FILE.read_text())
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_encryption_metadata(self, metadata: dict) -> None:
        """Save encryption key metadata"""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.ENCRYPTION_META_FILE.write_text(json.dumps(metadata, indent=2))
        try:
            self.ENCRYPTION_META_FILE.chmod(0o600)
        except OSError:
            pass  # Windows may not support chmod

    def _generate_new_key(self) -> str:
        """Generate a new Fernet encryption key"""
        try:
            from cryptography.fernet import Fernet
            return Fernet.generate_key().decode('utf-8')
        except ImportError:
            import secrets
            import base64
            return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')

    def _get_or_create_encryption_key(self) -> str:
        """
        Get encryption key from file or generate a new one.

        The key is stored in {DATA_DIR}/config/encryption.key
        Metadata is stored in {DATA_DIR}/config/encryption.meta.json
        """
        # Ensure config directory exists
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Use existing key if available
        if self.ENCRYPTION_KEY_FILE.exists():
            return self.ENCRYPTION_KEY_FILE.read_text().strip()

        # Generate new key
        new_key = self._generate_new_key()

        # Store key
        self.ENCRYPTION_KEY_FILE.write_text(new_key)
        try:
            self.ENCRYPTION_KEY_FILE.chmod(0o600)
        except OSError:
            pass  # Windows may not support chmod

        # Store metadata
        self._save_encryption_metadata({
            'created_at': datetime.utcnow().isoformat(),
            'version': 1
        })

        return new_key

    def _key_needs_rotation(self) -> bool:
        """Check if the encryption key is older than KEY_ROTATION_DAYS"""
        metadata = self._get_encryption_metadata()
        created_at_str = metadata.get('created_at')
        if not created_at_str:
            return False  # No metadata = new key, don't rotate yet

        try:
            created_at = datetime.fromisoformat(created_at_str)
            return datetime.utcnow() - created_at > timedelta(days=KEY_ROTATION_DAYS)
        except (ValueError, TypeError):
            return False

    def has_valid_claude_api_key(self) -> bool:
        """Check if a valid Anthropic API key is set in the environment."""
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        return key.startswith("sk-ant-") and len(key) > 20

    def is_production_mode(self) -> bool:
        """Check if running in production mode (DATA_DIR explicitly set by Tauri)."""
        return self._data_dir_from_env

    def is_development_mode(self) -> bool:
        """Check if running in development mode (using default DATA_DIR)."""
        return not self._data_dir_from_env

    def validate_paths(self) -> dict:
        """
        Validate that all required paths are accessible.

        Returns:
            dict with 'valid' (bool) and 'errors' (list of str)
        """
        errors = []

        # Check that DATA_DIR is writable
        try:
            test_file = self.DATA_DIR / ".write_test"
            test_file.touch()
            test_file.unlink()
        except (OSError, IOError) as e:
            errors.append(f"DATA_DIR not writable: {e}")

        # Check that encryption key is readable
        if self.ENCRYPTION_KEY_FILE.exists():
            try:
                self.ENCRYPTION_KEY_FILE.read_text()
            except (OSError, IOError) as e:
                errors.append(f"Cannot read encryption key: {e}")

        return {
            'valid': len(errors) == 0,
            'errors': errors
        }

    def get_paths_info(self) -> dict:
        """Get information about all configured paths (for debugging/health checks)."""
        return {
            'data_dir': str(self.DATA_DIR),
            'config_dir': str(self.CONFIG_DIR),
            'database_path': str(self.DATA_SUBDIR / 'invoices.db'),
            'upload_dir': str(self.UPLOAD_DIR),
            'temp_dir': str(self.TEMP_DIR),
            'documents_dir': str(self.DOCUMENTS_DIR),
            'log_dir': str(self.LOG_DIR),
            'model_cache_dir': str(self.MODEL_CACHE_DIR),
            'mode': 'production' if self.is_production_mode() else 'development'
        }


def check_and_rotate_encryption_key() -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if encryption key needs rotation and perform rotation if needed.

    This function is called from api_key_service to handle the re-encryption
    of stored API keys.

    Returns:
        Tuple of (rotation_needed, old_key, new_key)
        If rotation is not needed, returns (False, None, None)
    """
    if not settings._key_needs_rotation():
        return (False, None, None)

    if not settings.ENCRYPTION_KEY_FILE.exists():
        return (False, None, None)

    # Get old key
    old_key = settings.ENCRYPTION_KEY_FILE.read_text().strip()

    # Generate new key
    new_key = settings._generate_new_key()

    # Store new key
    settings.ENCRYPTION_KEY_FILE.write_text(new_key)
    try:
        settings.ENCRYPTION_KEY_FILE.chmod(0o600)
    except OSError:
        pass

    # Update metadata
    metadata = settings._get_encryption_metadata()
    metadata['created_at'] = datetime.utcnow().isoformat()
    metadata['version'] = metadata.get('version', 1) + 1
    metadata['last_rotation'] = datetime.utcnow().isoformat()
    settings._save_encryption_metadata(metadata)

    # Update the settings instance
    settings.API_KEY_ENCRYPTION_KEY = new_key

    return (True, old_key, new_key)


# Create global settings instance
settings = Settings()
