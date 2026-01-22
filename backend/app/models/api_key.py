"""
API Key Model - Stores encrypted API keys for external services.

API keys are encrypted using Fernet symmetric encryption before storage.
The encryption key is auto-generated on first run and stored locally.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from datetime import datetime
from app.db.base import Base


class ApiKey(Base):
    """
    Stores encrypted API keys for external services (Anthropic, etc.)

    Keys are encrypted at rest using Fernet encryption.
    The encryption key is stored in a local file or environment variable.
    """
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    provider = Column(String(50), unique=True, index=True)
    # Provider values: anthropic, openai, etc.

    encrypted_key = Column(Text, nullable=False)
    # Fernet-encrypted API key

    key_prefix = Column(String(20), nullable=True)
    # First few chars of key for identification (e.g., "sk-ant-...")

    is_valid = Column(Boolean, default=True)
    # Whether the key passed validation

    validation_error = Column(String(255), nullable=True)
    # Error message if validation failed

    source = Column(String(50), nullable=True)
    # Source of the key: 'manual', 'env_migrated'

    key_expires_at = Column(DateTime, nullable=True)
    # Optional expiration date for the key

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    last_validated_at = Column(DateTime, nullable=True)

    def update_validation(self, is_valid: bool, error: str = None):
        """Update validation status"""
        self.is_valid = is_valid
        self.validation_error = error
        self.last_validated_at = datetime.utcnow()

    def is_expired(self) -> bool:
        """Check if the key has expired"""
        if not self.key_expires_at:
            return False
        return datetime.utcnow() > self.key_expires_at

    def get_status(self) -> str:
        """Get the current status of the key"""
        if self.is_expired():
            return 'expired'
        if not self.is_valid:
            return 'invalid'
        return 'valid'

    def to_status_response(self) -> dict:
        """Convert to API status response format"""
        expired = self.is_expired()
        return {
            'provider': self.provider,
            'status': self.get_status(),
            'configured': True,
            'valid': self.is_valid and not expired,
            'expired': expired,
            'key_prefix': self.key_prefix,
            'error': self.validation_error,
            'source': self.source,
            'last_validated_at': self.last_validated_at.isoformat() if self.last_validated_at else None
        }
