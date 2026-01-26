"""
Qwen2-VL Service for Invoice Data Extraction

PDF -> Image -> Qwen2-VL -> Structured JSON
Model cached locally, CPU-only (~2-3 GB RAM)


/!\ Code is not in use. Kept for reference.
"""

from typing import Dict, Any, List, Optional
from PIL import Image
import torch
import threading
import structlog
import os
import gc
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
import json
import re
from app.core.config import settings

logger = structlog.get_logger(__name__)

class QwenService:
    """Extract structured invoice data using Qwen2-VL"""
    _load_lock = threading.Lock()      # To ensure thread-safe model loading
    _inference_lock = threading.Lock() # To ensure thread-safe inference

    def __init__(self):
        self.model_name = settings.QWEN_MODEL
        self.model = None
        self.processor = None
        self.cache_dir = settings.MODEL_CACHE_DIR

        os.makedirs(self.cache_dir, exist_ok=True)
        os.environ["HF_HOME"] = str(self.cache_dir)
        os.environ["TRANSFORMERS_CACHE"] = str(self.cache_dir)

    def load_model(self):
        """Load model (CPU-only, memory optimized)"""
        logger.info(f"Loading Qwen2-VL model: {self.model_name} in cache dir: {self.cache_dir}")
        
        if self.model is not None:
            logger.info("Model already loaded, skipping load")
            return
            
        with self._load_lock:    
            if self.model is None:
                logger.warning("Model not loaded yet, loading now...")
                logger.info(f"Loading Qwen2-VL model: {self.model_name}")
                logger.info(f"Cache directory: {self.cache_dir}")
    
                self.processor = AutoProcessor.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    cache_dir=self.cache_dir
                )
    
                self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    torch_dtype=torch.bfloat16,
                    low_cpu_mem_usage=True,
                    cache_dir=self.cache_dir
                )

                self.model.eval()
                logger.info("Model loaded on CPU")

    def extract_invoice_data(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract structured invoice data from image

        Args:
            image: PIL Image of invoice

        Returns:
            Dictionary with structured invoice data and raw response
        """
        logger.info("Extracting invoice data using Qwen2-VL")
        
        if image is None:
            logger.error("Image is None")
            raise ValueError("Image is None")

        if not isinstance(image, Image.Image):
            logger.error(f"Invalid image type: {type(image)}")
            raise ValueError(f"Image must be PIL Image, got {type(image)}")

        if image.mode != 'RGB':
            image = image.convert('RGB')

        self.load_model()
        
        # Thread safe inference
        thread_name = threading.current_thread().name
        logger.debug(f"Thread {thread_name} acquiring inference lock")
        
        with self._inference_lock:
            logger.debug(f"Thread {thread_name} acquired inference lock")
            
            try:
                result = self._run_inference(image)
                return result
            except Exception as e:
                logger.error(f"Error during inference: {e}")
                raise
            finally:
                logger.debug(f"Thread {thread_name} released inference lock")
                
                
    def _run_inference(self, image: Image.Image) -> Dict[str, Any]:
        """
            Run inference on the image and parse response
            must be called within inference lock
        """

        prompt = """Analyze this invoice image carefully and extract ALL information in JSON format.
        
        IMPORTANT: Extract EVERY line item from the invoice table/list. Each product or service is a separate line_item.
        
        Expected JSON structure:
        {
          "is_invoice": true,
          "provider": "company/supplier name (who issued the invoice)",
          "invoice_number": "invoice/facture number",
          "date": "invoice date (format: DD/MM/YYYY or YYYY-MM-DD)",
          "total_ht": 0.0,
          "total_ttc": 0.0,
          "vat_amount": 0.0,
          "line_items": [
            {
              "designation": "product or service description",
              "quantity": 1.0,
              "unit": "unit of measure (pièce, kg, h, m², etc.)",
              "unit_price": 0.0,
              "total_ht": 0.0
            }
          ]
        }
        
        EXTRACTION RULES FOR LINE ITEMS:
        1. Look for a table with columns like: Description/Désignation, Quantité/Qté, Prix unitaire/PU, Montant/Total
        2. Extract EACH row as a separate line_item
        3. For quantity: look for numbers in Qté/Quantité column (default to 1 if not specified)
        4. For unit_price: the price per single unit (Prix unitaire, PU, P.U.)
        5. For total_ht: the line total WITHOUT VAT (Montant HT, Total HT)
        6. For designation: the full product/service description
        
        FRENCH INVOICE TERMS:
        - "Fournisseur" / "Émetteur" = provider (NOT the client/customer)
        - "Facture N°" / "N° Facture" = invoice_number
        - "Date" / "Date de facture" = date
        - "Total HT" / "Sous-total HT" / "Montant HT" = total_ht (total without VAT)
        - "Total TTC" / "Net à payer" / "Montant TTC" = total_ttc (total with VAT)  
        - "TVA" / "Montant TVA" = vat_amount
        - "Qté" / "Quantité" = quantity
        - "P.U." / "Prix unitaire" / "PU HT" = unit_price
        
        If this is NOT an invoice (e.g. letter, quote/devis, contract, delivery note), return:
        {"is_invoice": false}
        
        Return ONLY valid JSON, no explanations or markdown."""
       
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

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
        )

        logger.info("Generating with Qwen2-VL...")
        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=False
            )

        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]

        del inputs
        gc.collect()

        output_text = self.processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False
        )[0]

        logger.info(f"Qwen2-VL output: {output_text[:300]}...")

        structured_data = self._parse_response(output_text)
        
        logger.info("Invoice data extraction completed")
        
        return {
            'structured_data': structured_data,
            'raw_response': output_text
        }

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON response from Qwen2-VL"""
        try:
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))

                # Check if it's an invoice
                if not data.get('is_invoice', True):
                    return {'is_invoice': False}

                return {
                    'is_invoice': True,
                    'provider': str(data.get('provider', ''))[:255],
                    'invoice_number': str(data.get('invoice_number', ''))[:100],
                    'date': str(data.get('date', ''))[:50],
                    'total_ht': self._to_float(data.get('total_ht')),
                    'total_ttc': self._to_float(data.get('total_ttc')),
                    'vat_amount': self._to_float(data.get('vat_amount')),
                    'line_items': [
                        {
                            'designation': str(item.get('designation', ''))[:500],
                            'quantity': self._to_float(item.get('quantity')),
                            'unit': str(item.get('unit', ''))[:50] if item.get('unit') else None,
                            'unit_price': self._to_float(item.get('unit_price')),
                            'total_ht': self._to_float(item.get('total_ht'))
                        }
                        for item in data.get('line_items', [])
                        if isinstance(item, dict)
                    ]
                }

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"Failed to parse response: {e}")
            print(f"Response: {response_text[:200]}")

        return {
            'is_invoice': True,
            'provider': '',
            'invoice_number': '',
            'date': '',
            'total_ht': 0.0,
            'total_ttc': 0.0,
            'vat_amount': 0.0,
            'line_items': [],
            'parse_error': response_text[:200]
        }

    def _to_float(self, value) -> Optional[float]:
        """Convert value to float, return None if invalid"""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
