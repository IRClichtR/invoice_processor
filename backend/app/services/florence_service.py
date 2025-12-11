"""
Florence-2 Service for Invoice Data Extraction

PDF -> Image -> Florence-2 -> Structured JSON
Model cached locally, CPU-only (~2-3 GB RAM)
"""

from typing import Dict, Any, Optional
from PIL import Image
import torch
import threading
import structlog
import os
import gc
from transformers import AutoModelForCausalLM, AutoProcessor
import json
import re
from app.core.config import settings

logger = structlog.get_logger(__name__)


class FlorenceService:
    """Extract structured invoice data using Florence-2"""
    _load_lock = threading.Lock()
    _inference_lock = threading.Lock()

    def __init__(self):
        self.model_name = settings.FLORENCE_MODEL
        self.model = None
        self.processor = None
        self.cache_dir = settings.MODEL_CACHE_DIR

        os.makedirs(self.cache_dir, exist_ok=True)
        os.environ["HF_HOME"] = self.cache_dir
        os.environ["TRANSFORMERS_CACHE"] = self.cache_dir

    def load_model(self):
        """Load model (CPU-only, memory optimized)"""
        if self.model is not None:
            return

        with self._load_lock:
            if self.model is None:
                logger.info("Loading Florence-2 model", model=self.model_name, cache_dir=self.cache_dir)

                self.processor = AutoProcessor.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    cache_dir=self.cache_dir
                )

                # Use sdpa attention to avoid flash-attention error
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    torch_dtype=torch.float32,
                    attn_implementation="eager",
                    cache_dir=self.cache_dir
                )

                self.model.eval()
                logger.info("Florence-2 model loaded on CPU")

    def extract_invoice_data(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract structured invoice data from image

        Args:
            image: PIL Image of invoice

        Returns:
            Dictionary with structured invoice data and raw response
        """
        logger.info("Extracting invoice data using Florence-2")

        if image is None:
            logger.error("Image is None")
            raise ValueError("Image is None")

        if not isinstance(image, Image.Image):
            logger.error("Invalid image type", type=type(image))
            raise ValueError(f"Image must be PIL Image, got {type(image)}")

        if image.mode != 'RGB':
            image = image.convert('RGB')

        self.load_model()

        thread_name = threading.current_thread().name
        logger.debug("Acquiring inference lock", thread=thread_name)

        with self._inference_lock:
            logger.debug("Acquired inference lock", thread=thread_name)
            try:
                result = self._run_inference(image)
                return result
            except Exception as e:
                logger.error("Error during inference", error=str(e))
                raise
            finally:
                logger.debug("Released inference lock", thread=thread_name)

    def _run_inference(self, image: Image.Image) -> Dict[str, Any]:
        """Run inference on the image"""

        # Use OCR task to extract all text
        task_prompt = "<OCR>"

        inputs = self.processor(
            text=task_prompt,
            images=image,
            return_tensors="pt"
        )

        logger.debug("Processor input keys", keys=list(inputs.keys()))
        logger.debug("input_ids shape", shape=inputs["input_ids"].shape)
        logger.debug("pixel_values shape", shape=inputs["pixel_values"].shape)

        logger.info("Generating with Florence-2...")
        try:
            with torch.no_grad():
                generated_ids = self.model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=1024,
                    num_beams=1,
                    do_sample=False,
                    use_cache=False  # Disable KV cache to avoid past_key_values bug
                )
        except Exception as e:
            logger.error("Generate failed", error=str(e), error_type=type(e).__name__)
            import traceback
            logger.error("Traceback", tb=traceback.format_exc())
            raise

        if generated_ids is None:
            logger.error("Generation returned None")
            raise RuntimeError("Florence-2 generation failed")

        logger.info("Generation completed", generated_length=len(generated_ids[0]))

        del inputs
        gc.collect()

        output_text = self.processor.batch_decode(
            generated_ids,
            skip_special_tokens=False
        )[0]

        # Post-process to extract text after task prompt
        # Florence returns: <s>task_prompt</s>result</s>
        if "</s>" in output_text:
            parts = output_text.split("</s>")
            if len(parts) > 1:
                output_text = parts[1].strip()

        logger.info("Florence-2 OCR output", output_length=len(output_text), sample=output_text[:300] if output_text else "EMPTY")

        # Parse the OCR text to extract invoice data
        structured_data = self._parse_ocr_to_invoice(output_text)

        logger.info("Invoice data extraction completed")

        return {
            'structured_data': structured_data,
            'raw_response': output_text
        }

    def _parse_ocr_to_invoice(self, ocr_text: str) -> Dict[str, Any]:
        """Parse OCR text to extract invoice data"""

        # Check if it looks like an invoice
        invoice_keywords = ['facture', 'invoice', 'total', 'ttc', 'ht', 'tva', 'vat']
        text_lower = ocr_text.lower()
        is_invoice = any(kw in text_lower for kw in invoice_keywords)

        if not is_invoice:
            return {'is_invoice': False}

        lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]

        result = {
            'is_invoice': True,
            'provider': self._extract_provider(lines),
            'invoice_number': self._extract_invoice_number(ocr_text),
            'date': self._extract_date(ocr_text),
            'total_ht': self._extract_amount(ocr_text, ['total ht', 'sous-total', 'montant ht', 'ht :']),
            'total_ttc': self._extract_amount(ocr_text, ['total ttc', 'net à payer', 'montant ttc', 'ttc :']),
            'vat_amount': self._extract_amount(ocr_text, ['tva', 'vat', 'taxe']),
            'line_items': self._extract_line_items(ocr_text)
        }

        return result

    def _extract_provider(self, lines: list) -> str:
        """Extract provider from first lines"""
        for line in lines[:5]:
            # Skip short lines and lines that look like addresses/numbers
            if len(line) > 3 and not line.replace(' ', '').isdigit():
                return line[:255]
        return ''

    def _extract_invoice_number(self, text: str) -> str:
        """Extract invoice number"""
        patterns = [
            r'(?:facture|invoice)\s*[n°#:]*\s*([A-Z0-9\-/]+)',
            r'n[°#]\s*([A-Z0-9\-/]+)',
            r'(?:ref|référence)\s*[.:]*\s*([A-Z0-9\-/]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)[:100]
        return ''

    def _extract_date(self, text: str) -> str:
        """Extract date"""
        patterns = [
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4})',
            r'(\d{4}-\d{2}-\d{2})'
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)[:50]
        return ''

    def _extract_amount(self, text: str, keywords: list) -> Optional[float]:
        """Extract monetary amount based on keywords"""
        text_lower = text.lower()

        for keyword in keywords:
            if keyword in text_lower:
                idx = text_lower.index(keyword)
                # Look in the area around the keyword
                search_area = text[max(0, idx-20):idx+100]

                # Find amounts
                patterns = [
                    r'(\d{1,3}(?:[\s,]\d{3})*[.,]\d{2})',
                    r'(\d+[.,]\d{2})',
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, search_area)
                    if matches:
                        amount_str = matches[-1].replace(' ', '').replace(',', '.')
                        try:
                            return float(amount_str)
                        except ValueError:
                            continue
        return None

    def _extract_line_items(self, text: str) -> list:
        """Extract line items from text"""
        line_items = []
        lines = text.split('\n')

        # Skip header/footer lines
        skip_keywords = ['facture', 'invoice', 'total', 'tva', 'vat', 'client',
                        'adresse', 'siret', 'siren', 'iban', 'bic']

        for line in lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue

            line_lower = line.lower()
            if any(kw in line_lower for kw in skip_keywords):
                continue

            # Look for lines with product + numbers pattern
            numbers = re.findall(r'\d+[.,]?\d*', line)
            if len(numbers) >= 2:
                # Remove numbers to get designation
                designation = line
                for num in numbers:
                    designation = designation.replace(num, '', 1)
                designation = re.sub(r'[€$£]', '', designation)
                designation = re.sub(r'\s+', ' ', designation).strip()

                if len(designation) > 3:
                    parsed = [self._to_float(n) for n in numbers]
                    parsed = [p for p in parsed if p is not None]

                    if parsed:
                        item = {
                            'designation': designation[:500],
                            'quantity': parsed[0] if len(parsed) > 0 else None,
                            'unit': None,
                            'unit_price': parsed[1] if len(parsed) > 1 else None,
                            'total_ht': parsed[-1] if len(parsed) > 0 else None
                        }
                        line_items.append(item)

        return line_items[:20]

    def _to_float(self, value: str) -> Optional[float]:
        """Convert string to float"""
        if not value:
            return None
        try:
            cleaned = value.replace(' ', '').replace(',', '.')
            return float(cleaned)
        except (ValueError, TypeError):
            return None
