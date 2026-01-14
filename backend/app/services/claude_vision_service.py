from requests.models import LocationParseError
from urllib3 import Retry
from anthropic import Anthropic
from typing import Dict, Any
import base64
import requests
import os
import structlog

logger = structlog.get_logger(__name__)

class ClaudeVisionService:
    def __init__(self):
        self.client = Anthropic()
    
    def _image_to_base64(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def extract_invoice_data(self, image_path) -> Dict[str, Any]:
        """
        Extract structured invoice data using Claude Vision API.
        The method is aimed to process invoices that have significant parts in handwriting.
        Since Claude Vision does not support direct file uploads, the image is converted to a base64 string.
        Args:
            image_path: Path to the invoice image file.
        """
        
        logger.info("Extracting invoice data using Claude Vision", image_path=image_path)
        if image.mode != 'RGB':
            image = image.convert('RGB')
            
        image_base64 = self._image_to_base64(image_path)
        
        prompt = f"""
        You are an expert in extracting structured data from handwritten text and invoices. Analyze this text carefully. Read ALL text including handwritten content in any ink colour.
        Extract the following informations and return in the JSON format:
            {
                "is_invoice": true/false,
                "provider": "company at top of invoice",
                "invoice_number": "invoice/facture number",
                "invoice_date": "date in DD/MM/YYYY format",
                "client": "client name if present",
                "line_items": [
                    "quantity": number,
                    "designation": "item description",
                    "quantity": number,
                    "unit_price": number,
                    "total_ht": number
                ],
                "total_without_vat": number,
                "total_with_vat": number,
                "currency": "currency code in ISO 4217 format or XXX if not found"
            }
        """
        try:
            response = self.client.messages.create(
            model="claude-",
            max_tokens=1024,
            prompt=prompt,
            images=[{"type": "base64", "data": image_base64}]
            )
            return response.json()
        except: Exception as e:
            logger.error("Claude Vision API request failed", error=str(e))
            raise
        
        return {}