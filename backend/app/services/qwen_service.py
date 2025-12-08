"""
Qwen2-VL Service for Invoice Data Extraction

Uses Qwen2-VL-2B-Instruct for structured invoice data extraction
"""

from typing import Dict, Any, List
from PIL import Image
import torch
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
import json
import re
from app.core.config import settings


class QwenService:
    """Service for extracting structured data from invoices using Qwen2-VL"""

    def __init__(self, model_name: str = None, device: str = None):
        """
        Initialize Qwen2-VL service

        Args:
            model_name: Hugging Face model name (default: from settings)
            device: Device to run model on (default: from settings)
        """
        self.model_name = model_name or settings.QWEN_MODEL
        self.device = device or settings.DEVICE
        self.model = None
        self.processor = None

    def load_model(self):
        """Load Qwen2-VL model and processor"""
        if self.model is None:
            print(f"Loading Qwen2-VL model: {self.model_name}")

            # Load processor
            self.processor = AutoProcessor.from_pretrained(
                self.model_name,
                trust_remote_code=True
            )

            # Load model
            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
            ).to(self.device)

            print(f"Model loaded on device: {self.device}")

    def extract_invoice_data(
        self,
        image: Image.Image,
        ocr_text: str,
        ocr_word_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Extract structured invoice data using Qwen2-VL

        Args:
            image: PIL Image of invoice
            ocr_text: Pre-extracted OCR text (for fallback)
            ocr_word_data: Word-level OCR data with positions (for fallback)

        Returns:
            Dictionary with structured invoice data
        """
        # Validate image
        if image is None:
            raise ValueError("Image is None")

        if not isinstance(image, Image.Image):
            raise ValueError(f"Image must be PIL Image, got {type(image)}")

        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')

        self.load_model()

        # Create prompt for invoice extraction
        prompt = """Analyze this invoice image and extract the following information in JSON format:

{
  "provider": "company name",
  "invoice_number": "invoice number",
  "date": "invoice date",
  "total_ht": 0.0,
  "total_ttc": 0.0,
  "vat_amount": 0.0,
  "line_items": [
    {
      "designation": "item description",
      "quantity": 0.0,
      "unit": "unit",
      "unit_price": 0.0,
      "total_ht": 0.0
    }
  ]
}

Extract all line items from the invoice. For French invoices:
- "Total HT" or "Sous-total" = total_ht (total without VAT)
- "Total TTC" or "Net à payer" = total_ttc (total with VAT)
- "TVA" = vat_amount

Return ONLY the JSON, no other text."""

        # Prepare messages for Qwen2-VL
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "image": image,
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        # Process the inputs
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        image_inputs, video_inputs = process_vision_info(messages)

        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.device)

        # Generate response
        print("DEBUG: Generating with Qwen2-VL...")
        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=2048,
                do_sample=False
            )

        # Trim input tokens from output
        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]

        # Decode response
        output_text = self.processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False
        )[0]

        print(f"DEBUG: Qwen2-VL output: {output_text[:500]}...")

        # Parse JSON response
        structured_data = self._parse_qwen_response(output_text, ocr_text)

        return {
            'structured_data': structured_data,
            'raw_response': output_text,
            'model_used': self.model_name
        }

    def _parse_qwen_response(self, response_text: str, ocr_fallback: str) -> Dict[str, Any]:
        """
        Parse Qwen2-VL JSON response

        Args:
            response_text: Raw response from Qwen2-VL
            ocr_fallback: OCR text for fallback extraction

        Returns:
            Structured invoice data
        """
        # Try to extract JSON from response
        try:
            # Look for JSON block in response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)

                # Validate and convert types
                structured_data = {
                    'provider': str(data.get('provider', ''))[:255],
                    'invoice_number': str(data.get('invoice_number', ''))[:100],
                    'date': str(data.get('date', ''))[:50],
                    'total_ht': float(data.get('total_ht', 0.0)) if data.get('total_ht') else 0.0,
                    'total_ttc': float(data.get('total_ttc', 0.0)) if data.get('total_ttc') else 0.0,
                    'vat_amount': float(data.get('vat_amount', 0.0)) if data.get('vat_amount') else 0.0,
                    'line_items': []
                }

                # Parse line items
                for item in data.get('line_items', []):
                    if isinstance(item, dict):
                        line_item = {
                            'designation': str(item.get('designation', ''))[:500],
                            'quantity': float(item.get('quantity', 0.0)) if item.get('quantity') else None,
                            'unit': str(item.get('unit', ''))[:50] if item.get('unit') else None,
                            'unit_price': float(item.get('unit_price', 0.0)) if item.get('unit_price') else None,
                            'total_ht': float(item.get('total_ht', 0.0)) if item.get('total_ht') else None
                        }
                        structured_data['line_items'].append(line_item)

                return structured_data

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"WARNING: Failed to parse Qwen2-VL JSON response: {e}")
            print(f"Response was: {response_text[:200]}")

        # Fallback: Return empty structure
        return {
            'provider': '',
            'invoice_number': '',
            'date': '',
            'total_ht': 0.0,
            'total_ttc': 0.0,
            'vat_amount': 0.0,
            'line_items': [],
            'florence_response': f'Qwen2-VL parsing failed, response: {response_text[:200]}'
        }
