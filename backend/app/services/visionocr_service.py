"""
VisionOCR Service for Handwritten Document Extraction

Optimized for handwritten invoices using GOT-OCR-2.0 model.
Model cached locally, loaded at startup.
"""

from typing import Dict, Any, List, Optional
from PIL import Image
import torch
import threading
import structlog
import os
import gc
import time
import re
import json
from transformers import AutoModelForImageTextToText, AutoProcessor
from app.core.config import settings

logger = structlog.get_logger(__name__)


class VisionOCRService:
    """Extract text and structured data from handwritten documents using VisionOCR"""
    _load_lock = threading.Lock()
    _inference_lock = threading.Lock()

    def __init__(self):
        self.model_name = settings.VISIONOCR_MODEL
        self.model = None
        self.processor = None
        self.cache_dir = settings.MODEL_CACHE_DIR

        os.makedirs(self.cache_dir, exist_ok=True)
        os.environ["HF_HOME"] = self.cache_dir
        os.environ["TRANSFORMERS_CACHE"] = self.cache_dir

    def load_model(self):
        """Load VisionOCR model (CPU-only)"""
        if self.model is not None:
            return

        with self._load_lock:
            if self.model is None:
                logger.info("Loading VisionOCR model", model=self.model_name, cache_dir=self.cache_dir)

                self.processor = AutoProcessor.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    cache_dir=self.cache_dir
                )

                self.model = AutoModelForImageTextToText.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    torch_dtype=torch.float32,
                    low_cpu_mem_usage=True,
                    cache_dir=self.cache_dir
                )

                self.model.eval()
                logger.info("VisionOCR model loaded on CPU")

    def extract_handwritten_text(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract text from handwritten document.

        Args:
            image: PIL Image of handwritten document

        Returns:
            Dictionary with extracted text and structured data
        """
        logger.info("Extracting handwritten text with VisionOCR")

        if image is None:
            raise ValueError("Image is None")

        if image.mode != 'RGB':
            image = image.convert('RGB')

        self.load_model()

        with self._inference_lock:
            try:
                result = self._run_inference(image)
                return result
            except Exception as e:
                logger.error("Error during VisionOCR inference", error=str(e))
                raise

    def _run_inference(self, image: Image.Image) -> Dict[str, Any]:
        """Run VisionOCR inference on image using HuggingFace generate() API"""
        inference_start = time.time()

        try:
            # Process image for the model
            inputs = self.processor(image, return_tensors="pt")

            # Generate OCR output
            with torch.no_grad():
                generate_ids = self.model.generate(
                    **inputs,
                    do_sample=False,
                    tokenizer=self.processor.tokenizer,
                    stop_strings="<|im_end|>",
                    max_new_tokens=4096,
                )

            # Decode the generated tokens (skip input tokens)
            ocr_result = self.processor.decode(
                generate_ids[0, inputs["input_ids"].shape[1]:],
                skip_special_tokens=True
            )

        except Exception as e:
            logger.error("VisionOCR generate failed", error=str(e))
            import traceback
            logger.error("Traceback", tb=traceback.format_exc())
            raise

        inference_time = time.time() - inference_start
        logger.info("VisionOCR completed", inference_time_sec=round(inference_time, 2))

        # Clean up
        del inputs
        gc.collect()

        # Parse the OCR result into structured invoice data
        structured_data = self._parse_handwritten_invoice(ocr_result)

        return {
            'raw_text': ocr_result,
            'structured_data': structured_data,
            'inference_time': inference_time
        }

    def _parse_handwritten_invoice(self, ocr_text: str) -> Dict[str, Any]:
        """Parse OCR text from handwritten invoice into structured data"""
        text_lower = ocr_text.lower()

        # Check if invoice
        invoice_keywords = ['facture', 'invoice', 'total', 'ttc', 'ht', 'tva', 'montant', 'prix']
        is_invoice = any(kw in text_lower for kw in invoice_keywords)

        if not is_invoice:
            return {'is_invoice': False, 'raw_text': ocr_text}

        result = {
            'is_invoice': True,
            'provider': self._extract_provider(ocr_text),
            'invoice_number': self._extract_invoice_number(ocr_text),
            'date': self._extract_date(ocr_text),
            'total_ht': self._extract_amount(ocr_text, ['total ht', 'sous-total', 'ht']),
            'total_ttc': self._extract_amount(ocr_text, ['total ttc', 'net à payer', 'total', 'ttc']),
            'currency': self._extract_currency(ocr_text),
            'line_items': self._extract_line_items(ocr_text),
            'raw_text': ocr_text
        }

        return result

    def _extract_provider(self, text: str) -> str:
        """Extract provider name from handwritten text"""
        lines = text.strip().split('\n')

        # Skip patterns
        skip_patterns = [
            r'^\d+', r'facture', r'invoice', r'date', r'total',
            r'tel', r'fax', r'email', r'@', r'www\.',
        ]

        for line in lines[:8]:
            line = line.strip()
            if len(line) < 3:
                continue

            line_lower = line.lower()
            should_skip = any(re.search(p, line_lower) for p in skip_patterns)

            if not should_skip and len(line) > 3:
                return line[:255]

        return ''

    def _extract_invoice_number(self, text: str) -> str:
        """Extract invoice number"""
        patterns = [
            r'(?:facture|invoice|fact|inv)[.\s]*[n°#:]*\s*([A-Z0-9\-/]+)',
            r'n[°#]\s*:?\s*([A-Z0-9\-/]+)',
            r'(?:ref|réf)[.\s]*:?\s*([A-Z0-9\-/]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)[:100]
        return ''

    def _extract_date(self, text: str) -> str:
        """Extract date from handwritten text"""
        patterns = [
            r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            r'(\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4})',
            r'(\d{4}[/\-\.]\d{2}[/\-\.]\d{2})'
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)[:50]
        return ''

    def _extract_amount(self, text: str, keywords: List[str]) -> Optional[float]:
        """Extract monetary amount near keywords"""
        text_lower = text.lower()
        lines = text.split('\n')

        for keyword in keywords:
            for line in reversed(lines):
                if keyword in line.lower():
                    amounts = self._find_amounts(line)
                    if amounts:
                        return max(a for a in amounts if a > 1.0) if any(a > 1.0 for a in amounts) else amounts[0]

        return None

    def _find_amounts(self, text: str) -> List[float]:
        """Find monetary amounts in text"""
        amounts = []
        patterns = [
            r'(\d{1,3}(?:\s\d{3})*[.,]\d{2})',
            r'(\d+[.,]\d{2})',
            r'(\d+)\s*(?:€|EUR|euros?)',
        ]

        for pattern in patterns:
            for match in re.findall(pattern, text, re.IGNORECASE):
                try:
                    clean = match.replace(' ', '').replace(',', '.')
                    amount = float(clean)
                    if amount > 0:
                        amounts.append(amount)
                except ValueError:
                    pass

        return amounts

    def _extract_currency(self, text: str) -> str:
        """Extract currency, default EUR"""
        if '€' in text or 'EUR' in text.upper() or 'euro' in text.lower():
            return 'EUR'
        if '$' in text or 'USD' in text.upper():
            return 'USD'
        if '£' in text or 'GBP' in text.upper():
            return 'GBP'
        return 'EUR'

    def _extract_line_items(self, text: str) -> List[Dict]:
        """Extract line items from handwritten invoice"""
        line_items = []
        lines = text.split('\n')

        # Skip header/footer patterns
        skip_patterns = [
            r'facture|invoice|total|tva|client|adresse|siret|date|tel|fax|email|page|iban|bic',
        ]

        for line in lines:
            line = line.strip()
            if len(line) < 5:
                continue

            line_lower = line.lower()
            if any(re.search(p, line_lower) for p in skip_patterns):
                continue

            # Look for lines with amounts
            amounts = self._find_amounts(line)
            if not amounts:
                continue

            # Extract designation (text before numbers)
            designation_match = re.match(r'^([A-Za-zÀ-ÿ\s\-\.]+)', line)
            if designation_match:
                designation = designation_match.group(1).strip()
                if len(designation) > 2:
                    item = {
                        'designation': designation[:500],
                        'quantity': None,
                        'unit_price': None,
                        'total_ht': amounts[-1] if amounts else None
                    }

                    # Try to extract quantity and price
                    numbers = re.findall(r'(\d+(?:[.,]\d+)?)', line)
                    if len(numbers) >= 3:
                        try:
                            item['quantity'] = float(numbers[0].replace(',', '.'))
                            item['unit_price'] = float(numbers[1].replace(',', '.'))
                            item['total_ht'] = float(numbers[-1].replace(',', '.'))
                        except ValueError:
                            pass
                    elif len(numbers) == 2:
                        try:
                            item['quantity'] = float(numbers[0].replace(',', '.'))
                            item['total_ht'] = float(numbers[-1].replace(',', '.'))
                        except ValueError:
                            pass

                    line_items.append(item)

        return line_items[:30]

    def extract_invoice_data(
        self,
        image: Image.Image,
        ocr_text: str = None,
        spatial_grid: str = None,
        words: List[Dict] = None
    ) -> Dict[str, Any]:
        """
        Extract invoice data - interface compatible with FlorenceService.

        For handwritten documents, we use VisionOCR directly on the image
        instead of relying on Tesseract OCR.

        Args:
            image: PIL Image of invoice
            ocr_text: Optional OCR text (may be ignored for handwritten)
            spatial_grid: Optional spatial grid (ignored)
            words: Optional word positions (ignored)

        Returns:
            Dictionary with structured invoice data
        """
        result = self.extract_handwritten_text(image)

        return {
            'structured_data': result['structured_data'],
            'raw_response': result['raw_text'],
            'ocr_text': result['raw_text'][:1000]
        }
