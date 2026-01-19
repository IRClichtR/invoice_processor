"""
API Key Service - Manage encrypted API key storage and validation.

Provides secure storage and retrieval of API keys for external services.
Keys are encrypted using Fernet symmetric encryption.
"""

from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
import structlog

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.models.api_key import ApiKey

logger = structlog.get_logger(__name__)

# Console URL for getting Anthropic API keys
ANTHROPIC_CONSOLE_URL = "https://platform.claude.com"


class ApiKeyService:
    """
    Manage encrypted API key storage and validation.

    Keys are encrypted at rest using Fernet encryption.
    The encryption key is auto-generated on first run.
    """

    def __init__(self):
        try:
            self.fernet = Fernet(settings.API_KEY_ENCRYPTION_KEY.encode())
        except Exception as e:
            logger.error("Failed to initialize Fernet encryption", error=str(e))
            raise RuntimeError("Encryption key is invalid. Check API_KEY_ENCRYPTION_KEY setting.")

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a string"""
        return self.fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt a string"""
        try:
            return self.fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            logger.error("Failed to decrypt API key - invalid token")
            raise ValueError("Failed to decrypt API key. Encryption key may have changed.")

    def _get_key_prefix(self, key: str) -> str:
        """Get prefix of key for identification (e.g., 'sk-ant-...')"""
        if len(key) > 10:
            return key[:10] + "..."
        return key[:4] + "..."

    def store_api_key(
        self,
        provider: str,
        key: str,
        db: Session,
        validate: bool = True
    ) -> Dict[str, Any]:
        """
        Store an API key (encrypted) for a provider.

        Args:
            provider: Provider name (e.g., 'anthropic')
            key: The API key to store
            db: Database session
            validate: Whether to validate the key with the provider

        Returns:
            {
                'success': bool,
                'valid': bool,
                'error': str or None,
                'provider': str
            }
        """
        logger.info("Storing API key", provider=provider)

        # Validate key format
        if not key or len(key) < 10:
            return {
                'success': False,
                'valid': False,
                'error': 'API key is too short',
                'provider': provider
            }

        # Provider-specific validation
        if provider == 'anthropic':
            if not key.startswith('sk-ant-'):
                return {
                    'success': False,
                    'valid': False,
                    'error': 'Invalid Anthropic API key format. Key should start with "sk-ant-"',
                    'provider': provider
                }

        # Encrypt the key
        encrypted_key = self._encrypt(key)
        key_prefix = self._get_key_prefix(key)

        # Check if key already exists for provider
        existing = db.query(ApiKey).filter(ApiKey.provider == provider).first()

        if existing:
            # Update existing key
            existing.encrypted_key = encrypted_key
            existing.key_prefix = key_prefix
            existing.is_valid = True
            existing.validation_error = None
            api_key_record = existing
        else:
            # Create new key
            api_key_record = ApiKey(
                provider=provider,
                encrypted_key=encrypted_key,
                key_prefix=key_prefix,
                is_valid=True
            )
            db.add(api_key_record)

        db.commit()

        # Validate with provider API if requested
        if validate:
            validation_result = self.validate_api_key(provider, db)
            return {
                'success': True,
                'valid': validation_result['valid'],
                'error': validation_result.get('error'),
                'provider': provider
            }

        return {
            'success': True,
            'valid': True,  # Assumed valid if not validated
            'error': None,
            'provider': provider
        }

    def get_api_key(self, provider: str, db: Session) -> Optional[str]:
        """
        Retrieve and decrypt an API key for a provider.

        Args:
            provider: Provider name (e.g., 'anthropic')
            db: Database session

        Returns:
            Decrypted API key or None if not found
        """
        api_key_record = db.query(ApiKey).filter(ApiKey.provider == provider).first()

        if not api_key_record:
            return None

        try:
            return self._decrypt(api_key_record.encrypted_key)
        except ValueError as e:
            logger.error("Failed to decrypt API key", provider=provider, error=str(e))
            return None

    def validate_api_key(self, provider: str, db: Session) -> Dict[str, Any]:
        """
        Validate an API key with the provider's API.

        Args:
            provider: Provider name
            db: Database session

        Returns:
            {
                'configured': bool,
                'valid': bool,
                'error': str or None
            }
        """
        api_key = self.get_api_key(provider, db)

        if not api_key:
            return {
                'configured': False,
                'valid': False,
                'error': 'API key not configured'
            }

        result = {
            'configured': True,
            'valid': False,
            'error': None
        }

        if provider == 'anthropic':
            result = self._validate_anthropic_key(api_key)
        else:
            # Unknown provider - assume valid if key exists
            result['valid'] = True

        # Update validation status in database
        api_key_record = db.query(ApiKey).filter(ApiKey.provider == provider).first()
        if api_key_record:
            api_key_record.update_validation(
                is_valid=result['valid'],
                error=result.get('error')
            )
            db.commit()

        return result

    def _validate_anthropic_key(self, api_key: str) -> Dict[str, Any]:
        """Validate an Anthropic API key by making a minimal API call"""
        try:
            from anthropic import Anthropic, AuthenticationError, APIError

            client = Anthropic(api_key=api_key)

            # Make a minimal API call to validate
            client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": "test"}]
            )

            logger.info("Anthropic API key validated successfully")
            return {
                'configured': True,
                'valid': True,
                'error': None
            }

        except AuthenticationError:
            logger.warning("Anthropic API key authentication failed")
            return {
                'configured': True,
                'valid': False,
                'error': 'API key is invalid or expired'
            }
        except APIError as e:
            # API error but key might still be valid
            error_msg = str(e)
            if "invalid_api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                return {
                    'configured': True,
                    'valid': False,
                    'error': 'API key is invalid'
                }
            # Other API errors (rate limit, etc.) - key is likely valid
            logger.warning("Anthropic API error during validation", error=error_msg)
            return {
                'configured': True,
                'valid': True,
                'error': None
            }
        except ImportError:
            logger.error("anthropic package not installed")
            return {
                'configured': True,
                'valid': False,
                'error': 'anthropic package not installed'
            }
        except Exception as e:
            logger.error("Unexpected error validating Anthropic key", error=str(e))
            return {
                'configured': True,
                'valid': False,
                'error': f'Validation error: {str(e)}'
            }

    def delete_api_key(self, provider: str, db: Session) -> bool:
        """
        Delete a stored API key.

        Args:
            provider: Provider name
            db: Database session

        Returns:
            True if key was deleted, False if not found
        """
        api_key_record = db.query(ApiKey).filter(ApiKey.provider == provider).first()

        if not api_key_record:
            return False

        db.delete(api_key_record)
        db.commit()

        logger.info("API key deleted", provider=provider)
        return True

    def get_all_status(self, db: Session) -> Dict[str, Dict[str, Any]]:
        """
        Get status of all configured API keys.

        Returns:
            {
                'anthropic': {
                    'configured': bool,
                    'valid': bool,
                    'key_prefix': str,
                    'error': str or None,
                    'last_validated_at': str or None
                },
                ...
            }
        """
        result = {}

        # Get all stored keys
        api_keys = db.query(ApiKey).all()
        for api_key in api_keys:
            result[api_key.provider] = api_key.to_status_response()

        # Add providers that aren't configured
        known_providers = ['anthropic']
        for provider in known_providers:
            if provider not in result:
                result[provider] = {
                    'provider': provider,
                    'configured': False,
                    'valid': False,
                    'key_prefix': None,
                    'error': 'Not configured',
                    'last_validated_at': None
                }

        return result

    def get_anthropic_key_for_processing(self, db: Session) -> Optional[str]:
        """
        Get Anthropic API key for processing, with fallback to env var.

        Priority:
        1. Database-stored key (if valid)
        2. Environment variable

        Returns:
            API key or None if not available
        """
        # Try database first
        db_key = self.get_api_key('anthropic', db)
        if db_key:
            # Check if it's marked as valid
            api_key_record = db.query(ApiKey).filter(ApiKey.provider == 'anthropic').first()
            if api_key_record and api_key_record.is_valid:
                return db_key

        # Fallback to environment variable
        if settings.has_valid_claude_api_key():
            return settings.ANTHROPIC_API_KEY

        return None
