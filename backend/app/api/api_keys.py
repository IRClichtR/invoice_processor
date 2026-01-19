"""
API Keys Router - Manage external API keys for services like Anthropic.

Endpoints:
- POST /api-keys: Store and validate a new API key
- GET /api-keys/status: Get status of all configured keys
- DELETE /api-keys/{provider}: Delete a stored key
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import structlog

from app.db.base import get_db
from app.services.api_key_service import ApiKeyService, ANTHROPIC_CONSOLE_URL

router = APIRouter()
logger = structlog.get_logger(__name__)


# Request/Response Models

class StoreApiKeyRequest(BaseModel):
    """Request to store an API key"""
    provider: str  # e.g., 'anthropic'
    key: str
    validate: bool = True  # Whether to validate the key with the provider


class StoreApiKeyResponse(BaseModel):
    """Response from storing an API key"""
    success: bool
    valid: bool
    provider: str
    error: Optional[str] = None


class ProviderStatus(BaseModel):
    """Status of a single provider's API key"""
    provider: str
    configured: bool
    valid: bool
    key_prefix: Optional[str] = None
    error: Optional[str] = None
    last_validated_at: Optional[str] = None


class ApiKeyStatusResponse(BaseModel):
    """Response with status of all API keys"""
    anthropic: ProviderStatus
    console_url: str = ANTHROPIC_CONSOLE_URL


class ValidateKeyResponse(BaseModel):
    """Response from key validation"""
    provider: str
    configured: bool
    valid: bool
    error: Optional[str] = None


class DeleteKeyResponse(BaseModel):
    """Response from deleting a key"""
    success: bool
    provider: str
    message: str


# Endpoints

@router.post("/api-keys", response_model=StoreApiKeyResponse)
async def store_api_key(
    request: StoreApiKeyRequest,
    db: Session = Depends(get_db)
):
    """
    Store and optionally validate an API key.

    Supported providers:
    - anthropic: Anthropic API key (starts with 'sk-ant-')

    The key is encrypted before storage. Never stored in plain text.
    """
    logger.info("Storing API key", provider=request.provider)

    # Validate provider
    supported_providers = ['anthropic']
    if request.provider not in supported_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider. Supported: {', '.join(supported_providers)}"
        )

    api_key_service = ApiKeyService()

    result = api_key_service.store_api_key(
        provider=request.provider,
        key=request.key,
        db=db,
        validate=request.validate
    )

    return StoreApiKeyResponse(
        success=result['success'],
        valid=result['valid'],
        provider=result['provider'],
        error=result.get('error')
    )


@router.get("/api-keys/status", response_model=ApiKeyStatusResponse)
async def get_api_key_status(db: Session = Depends(get_db)):
    """
    Get the status of all configured API keys.

    Returns configuration and validation status for each provider.
    """
    api_key_service = ApiKeyService()
    all_status = api_key_service.get_all_status(db)

    # Build response with status for each provider
    anthropic_status = all_status.get('anthropic', {
        'provider': 'anthropic',
        'configured': False,
        'valid': False,
        'key_prefix': None,
        'error': 'Not configured',
        'last_validated_at': None
    })

    return ApiKeyStatusResponse(
        anthropic=ProviderStatus(**anthropic_status),
        console_url=ANTHROPIC_CONSOLE_URL
    )


@router.post("/api-keys/{provider}/validate", response_model=ValidateKeyResponse)
async def validate_api_key(
    provider: str,
    db: Session = Depends(get_db)
):
    """
    Validate a stored API key with the provider's API.

    Makes a minimal API call to verify the key is working.
    """
    supported_providers = ['anthropic']
    if provider not in supported_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider. Supported: {', '.join(supported_providers)}"
        )

    api_key_service = ApiKeyService()
    result = api_key_service.validate_api_key(provider, db)

    return ValidateKeyResponse(
        provider=provider,
        configured=result['configured'],
        valid=result['valid'],
        error=result.get('error')
    )


@router.delete("/api-keys/{provider}", response_model=DeleteKeyResponse)
async def delete_api_key(
    provider: str,
    db: Session = Depends(get_db)
):
    """
    Delete a stored API key.

    After deletion, the provider will fall back to environment variable (if set).
    """
    supported_providers = ['anthropic']
    if provider not in supported_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider. Supported: {', '.join(supported_providers)}"
        )

    api_key_service = ApiKeyService()
    deleted = api_key_service.delete_api_key(provider, db)

    if deleted:
        return DeleteKeyResponse(
            success=True,
            provider=provider,
            message=f"API key for {provider} deleted successfully"
        )
    else:
        raise HTTPException(
            status_code=404,
            detail=f"No API key found for provider: {provider}"
        )


@router.get("/api-keys/console-url")
async def get_console_url():
    """
    Get the URL where users can obtain API keys.
    """
    return {
        "anthropic": ANTHROPIC_CONSOLE_URL
    }
