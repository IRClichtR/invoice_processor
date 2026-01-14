"""
Claude Vision Service for Invoice Data Extraction

Uses Claude's vision capabilities to extract structured data from
low-quality or handwritten invoice documents.
"""

from typing import Dict, Any, Optional
from PIL import Image
import base64
import io
import json
import re
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Claude API console URL for getting API keys
CLAUDE_API_CONSOLE_URL = "https://console.anthropic.com/settings/keys"


class ClaudeVisionError(Exception):
    """Base exception for Claude Vision service errors"""
    pass


class APIKeyNotConfiguredError(ClaudeVisionError):
    """Raised when Claude API key is not configured"""
    def __init__(self):
        self.console_url = CLAUDE_API_CONSOLE_URL
        super().__init__(
            f"Claude API key not configured. "
            f"Please obtain an API key from: {self.console_url}"
        )


class APIKeyInvalidError(ClaudeVisionError):
    """Raised when Claude API key is invalid"""
    def __init__(self, message: str = "Invalid API key"):
        self.console_url = CLAUDE_API_CONSOLE_URL
        super().__init__(
            f"{message}. "
            f"Please verify your API key at: {self.console_url}"
        )


class ClaudeVisionService:
    """
    Extract structured invoice data using Claude's vision capabilities.

    Used for:
    - Low-quality scanned documents
    - Handwritten invoices
    - Documents where OCR confidence is below threshold
    """

    INVOICE_EXTRACTION_PROMPT = """You are an expert in extracting structured data from invoices, including handwritten content.
Analyze this invoice image carefully. Read ALL text including handwritten content in any ink color.

Extract the following information and return ONLY a valid JSON object:
{
    "is_invoice": true or false,
    "provider": "Company name at top of invoice (issuer)",
    "invoice_number": "Invoice/facture number",
    "date": "Invoice date (preserve original format)",
    "currency": "ISO 4217 currency code (EUR, USD, GBP, etc.) - use XXX if unknown",
    "total_ht": numeric value of total before tax (null if not found),
    "total_ttc": numeric value of total including tax (null if not found),
    "vat_amount": numeric value of VAT/tax amount (null if not found),
    "line_items": [
        {
            "designation": "Product/service description",
            "quantity": numeric quantity,
            "unit_price": numeric unit price,
            "total_ht": numeric line total
        }
    ]
}

Important:
- Extract ALL visible line items
- For handwritten text, interpret the writing as best as possible
- Use null for fields that are not clearly visible
- For currency, look for symbols (€, $, £) or codes (EUR, USD)
- Return ONLY the JSON object, no markdown, no explanation"""

    def __init__(self):
        self._client = None

    def _get_client(self):
        """Get or create Anthropic client, validating API key"""
        if not settings.has_valid_claude_api_key():
            raise APIKeyNotConfiguredError()

        if self._client is None:
            try:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            except ImportError:
                raise ClaudeVisionError(
                    "anthropic package not installed. "
                    "Run: pip install anthropic"
                )

        return self._client

    def check_api_key_status(self) -> Dict[str, Any]:
        """
        Check if Claude API key is configured and valid.

        Returns:
            {
                'configured': bool,
                'valid': bool,
                'error': str or None,
                'console_url': str
            }
        """
        result = {
            'configured': False,
            'valid': False,
            'error': None,
            'console_url': CLAUDE_API_CONSOLE_URL
        }

        if not settings.ANTHROPIC_API_KEY:
            result['error'] = "API key not configured"
            return result

        result['configured'] = True

        if not settings.has_valid_claude_api_key():
            result['error'] = "API key format appears invalid"
            return result

        # Try a minimal API call to validate the key
        try:
            client = self._get_client()
            client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=10,
                messages=[{"role": "user", "content": "test"}]
            )
            result['valid'] = True
        except Exception as e:
            error_msg = str(e)
            if "invalid_api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                result['error'] = "API key is invalid or expired"
            else:
                result['error'] = f"API error: {error_msg}"

        return result

    def _image_to_base64(self, image: Image.Image) -> str:
        """Convert PIL Image to base64 string"""
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Resize if too large (Claude has limits)
        max_dimension = 2048
        if image.width > max_dimension or image.height > max_dimension:
            ratio = min(max_dimension / image.width, max_dimension / image.height)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return base64.standard_b64encode(buffer.getvalue()).decode('utf-8')

    def extract_invoice_data(
        self,
        image: Image.Image,
        ocr_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract structured invoice data from image using Claude Vision.

        Args:
            image: PIL Image of the invoice
            ocr_context: Optional OCR text for additional context

        Returns:
            {
                'structured_data': dict with invoice fields,
                'raw_response': str,
                'model_used': str
            }

        Raises:
            APIKeyNotConfiguredError: If API key is not set
            APIKeyInvalidError: If API key is invalid
            ClaudeVisionError: For other errors
        """
        client = self._get_client()

        # Convert image to base64
        image_base64 = self._image_to_base64(image)

        # Build the prompt
        prompt = self.INVOICE_EXTRACTION_PROMPT
        if ocr_context:
            prompt += f"\n\nPartial OCR text (may be incomplete):\n{ocr_context[:1500]}"

        logger.info(
            "Calling Claude Vision API",
            model=settings.CLAUDE_MODEL,
            image_size=f"{image.width}x{image.height}"
        )

        try:
            response = client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=settings.CLAUDE_MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )

            raw_response = response.content[0].text
            logger.info("Claude Vision response received", response_length=len(raw_response))

            # Parse the JSON response
            structured_data = self._parse_response(raw_response)

            return {
                'structured_data': structured_data,
                'raw_response': raw_response,
                'model_used': settings.CLAUDE_MODEL
            }

        except APIKeyNotConfiguredError:
            raise
        except APIKeyInvalidError:
            raise
        except Exception as e:
            error_msg = str(e)
            logger.error("Claude Vision API error", error=error_msg)

            if "invalid_api_key" in error_msg.lower():
                raise APIKeyInvalidError("API key is invalid")
            elif "authentication" in error_msg.lower():
                raise APIKeyInvalidError("Authentication failed")
            else:
                raise ClaudeVisionError(f"Claude API error: {error_msg}")

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse Claude's response into structured data"""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response

            data = json.loads(json_str)

            # Ensure required fields
            if 'is_invoice' not in data:
                data['is_invoice'] = True

            # Normalize currency
            currency = data.get('currency', 'XXX')
            if currency and len(str(currency)) == 3:
                data['currency'] = str(currency).upper()
            else:
                data['currency'] = 'XXX'

            return data

        except json.JSONDecodeError as e:
            logger.error("Failed to parse Claude response as JSON", error=str(e))
            return {
                'is_invoice': True,
                'provider': '',
                'currency': 'XXX',
                'parse_error': str(e),
                'raw_text': response[:1000]
            }