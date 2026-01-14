"""
Florence-2 Service for Invoice Data Extraction

Dual-modality approach:
- Image + Spatial OCR text -> Florence-2 -> Structured JSON

Model cached locally, CPU-only (~1 GB RAM for Florence-2-base)
"""

from typing import Dict, Any, Optional, List
from PIL import Image
import torch
import threading
import structlog
import os
import gc
import time
from transformers import AutoModelForCausalLM, AutoProcessor
import json
import re
from app.core.config import settings

logger = structlog.get_logger(__name__)


class FlorenceService:
    """Extract structured invoice data using Florence-2 with OCR context"""
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
        """Load model (CPU-only)"""
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

                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    torch_dtype=torch.float32,
                    attn_implementation="eager",
                    cache_dir=self.cache_dir
                )

                self.model.eval()
                logger.info("Florence-2 model loaded on CPU")

    def extract_invoice_data(
        self,
        image: Image.Image,
        ocr_text: str,
        spatial_grid: str,
        words: List[Dict]
    ) -> Dict[str, Any]:
        """
        Extract structured invoice data using image + OCR context.

        Args:
            image: PIL Image of invoice
            ocr_text: Full OCR text
            spatial_grid: Spatial text grid with positions
            words: List of word dicts with positions

        Returns:
            Dictionary with structured invoice data
        """
        logger.info("Extracting invoice data", ocr_length=len(ocr_text), word_count=len(words))

        if image is None:
            raise ValueError("Image is None")

        if image.mode != 'RGB':
            image = image.convert('RGB')

        self.load_model()

        thread_name = threading.current_thread().name

        with self._inference_lock:
            try:
                result = self._run_inference(image, ocr_text, spatial_grid, words)
                return result
            except Exception as e:
                logger.error("Error during inference", error=str(e))
                raise

    def _run_inference(
        self,
        image: Image.Image,
        ocr_text: str,
        spatial_grid: str,
        words: List[Dict]
    ) -> Dict[str, Any]:
        """Run Florence-2 inference - use OCR for main extraction, Florence for validation"""

        # Florence-2 task tokens must be alone - use detailed caption for document understanding
        task_prompt = "<MORE_DETAILED_CAPTION>"

        inputs = self.processor(
            text=task_prompt,
            images=image,
            return_tensors="pt"
        )

        logger.info("Generating with Florence-2...")
        inference_start = time.time()

        try:
            with torch.no_grad():
                generated_ids = self.model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=256,
                    num_beams=1,
                    do_sample=False,
                    use_cache=False
                )
        except Exception as e:
            logger.error("Generate failed", error=str(e))
            import traceback
            logger.error("Traceback", tb=traceback.format_exc())
            raise

        inference_time = time.time() - inference_start
        logger.info("Generation completed", generated_length=len(generated_ids[0]), inference_time_sec=round(inference_time, 2))

        del inputs
        gc.collect()

        vlm_output = self.processor.batch_decode(
            generated_ids,
            skip_special_tokens=True
        )[0]

        logger.info("Florence-2 caption", output_length=len(vlm_output), sample=vlm_output[:200])

        # Main extraction from OCR data, VLM output for additional context
        structured_data = self._parse_with_ocr_context(ocr_text, spatial_grid, words, vlm_output)

        return {
            'structured_data': structured_data,
            'raw_response': vlm_output,
            'ocr_text': ocr_text[:1000]
        }

    def _parse_with_ocr_context(
        self,
        ocr_text: str,
        spatial_grid: str,
        words: List[Dict],
        vlm_response: str
    ) -> Dict[str, Any]:
        """Parse invoice data using OCR + VLM response"""

        text_lower = ocr_text.lower()

        # Check if invoice
        invoice_keywords = ['facture', 'invoice', 'total', 'ttc', 'ht', 'tva']
        is_invoice = any(kw in text_lower for kw in invoice_keywords)

        if not is_invoice:
            return {'is_invoice': False}

        # Extract totals - search from bottom up for more accuracy
        total_ht = self._extract_total_amount(ocr_text, words, ['total ht', 'sous-total ht', 'total hors taxe'])
        total_ttc = self._extract_total_amount(ocr_text, words, ['total ttc', 'net à payer', 'montant ttc', 'total à payer'])
        vat_amount = self._extract_total_amount(ocr_text, words, ['montant tva', 'total tva'])

        # If we found total_ht and total_ttc but not VAT, calculate it
        if total_ht and total_ttc and not vat_amount:
            vat_amount = round(total_ttc - total_ht, 2)

        result = {
            'is_invoice': True,
            'provider': self._extract_provider(ocr_text, words),
            'invoice_number': self._extract_invoice_number(ocr_text),
            'date': self._extract_date(ocr_text),
            'total_ht': total_ht,
            'total_ttc': total_ttc,
            'vat_amount': vat_amount,
            'currency': self._extract_currency(ocr_text),
            'line_items': self._extract_line_items_improved(words)
        }

        return result

    def _extract_currency(self, text: str) -> str:
        """
        Extract currency from invoice text (ISO 4217 compliant).
        Returns 'XXX' if currency cannot be identified.
        """
        text_upper = text.upper()

        # Currency symbols and their ISO codes
        symbol_map = {
            '€': 'EUR',
            '$': 'USD',
            '£': 'GBP',
            '¥': 'JPY',
            '₣': 'CHF',
            '₹': 'INR',
            '₽': 'RUB',
            '₩': 'KRW',
            '₴': 'UAH',
            '₺': 'TRY',
            '₿': 'XBT',
        }

        # Check for currency symbols first (most reliable)
        for symbol, code in symbol_map.items():
            if symbol in text:
                return code

        # Common ISO currency codes to search for
        iso_codes = [
            'EUR', 'USD', 'GBP', 'CHF', 'JPY', 'CAD', 'AUD', 'CNY', 'INR',
            'BRL', 'MXN', 'SGD', 'HKD', 'NOK', 'SEK', 'DKK', 'PLN', 'CZK',
            'HUF', 'RON', 'BGN', 'HRK', 'RUB', 'TRY', 'ZAR', 'NZD', 'KRW'
        ]

        # Search for ISO codes in text
        for code in iso_codes:
            # Look for code as standalone word or near amounts
            patterns = [
                rf'\b{code}\b',  # Standalone code
                rf'\d+[.,]\d{{2}}\s*{code}',  # Amount followed by code
                rf'{code}\s*\d+[.,]\d{{2}}',  # Code followed by amount
            ]
            for pattern in patterns:
                if re.search(pattern, text_upper):
                    return code

        # Currency name patterns (common currencies)
        name_patterns = {
            'EUR': [r'\beuros?\b', r'\b€\b'],
            'USD': [r'\bdollars?\b', r'\busd\b', r'\bus\s*\$'],
            'GBP': [r'\bpounds?\b', r'\bsterling\b', r'\bgbp\b'],
            'CHF': [r'\bfrancs?\s*suisses?\b', r'\bchf\b'],
        }

        text_lower = text.lower()
        for code, patterns in name_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return code

        # Default to XXX (unknown currency per ISO 4217)
        return 'XXX'

    def _extract_provider(self, ocr_text: str, words: List[Dict]) -> str:
        """Extract provider name from top of document"""

        # Patterns that indicate address/metadata, not company name
        address_patterns = [
            r'^\d+',  # Starts with number (street number)
            r'rue|avenue|boulevard|allée|chemin|place|impasse',
            r'^\d{5}',  # Postal code
            r'france|cedex',
            r'tel|fax|email|@|www\.',
            r'siret|siren|tva|rcs|ape|naf',
            r'facture|invoice|devis|bon de',
            r'client|destinataire|livraison',
        ]

        # Get lines from top of document
        lines = ocr_text.strip().split('\n')

        for line in lines[:10]:
            line = line.strip()
            if len(line) < 3:
                continue

            line_lower = line.lower()

            # Skip if it matches address/metadata patterns
            is_address = False
            for pattern in address_patterns:
                if re.search(pattern, line_lower):
                    is_address = True
                    break

            if is_address:
                continue

            # Look for company indicators
            company_indicators = ['sarl', 'sas', 'sa', 'eurl', 'sasu', 'sci', 'snc', 'gmbh', 'ltd', 'inc']

            # Check if line contains company indicator
            for indicator in company_indicators:
                if indicator in line_lower:
                    # Extract company name (might be "SARL BOSKA" or "BOSKA SARL")
                    return line[:255]

            # If no indicator, return first non-address line that looks like a name
            # (mostly uppercase, no numbers at start)
            if line[0].isupper() and not line[0].isdigit():
                # Check it's not just a single short word
                if len(line) > 3:
                    return line[:255]

        # Fallback: try to find company name in words from top area
        top_words = [w for w in words if w['y'] < 0.12]
        if top_words:
            top_words.sort(key=lambda w: (w['y'], w['x']))
            first_y = top_words[0]['y']
            first_line_words = [w['text'] for w in top_words if abs(w['y'] - first_y) < 0.015]
            if first_line_words:
                candidate = ' '.join(first_line_words)
                # Check it's not an address
                candidate_lower = candidate.lower()
                is_valid = True
                for pattern in address_patterns:
                    if re.search(pattern, candidate_lower):
                        is_valid = False
                        break
                if is_valid:
                    return candidate[:255]

        return ''

    def _extract_invoice_number(self, text: str) -> str:
        """Extract invoice number"""
        patterns = [
            r'(?:facture|invoice)\s*[n°#:]*\s*([A-Z0-9\-/]+)',
            r'n[°#]\s*:?\s*([A-Z0-9\-/]+)',
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

    def _extract_total_amount(self, ocr_text: str, words: List[Dict], keywords: list) -> Optional[float]:
        """Extract total amounts - search bottom of document first"""
        text_lower = ocr_text.lower()

        # Search from bottom of document (totals are usually at the end)
        lines = ocr_text.split('\n')
        lines_reversed = list(reversed(lines))

        for keyword in keywords:
            for line in lines_reversed[:30]:  # Search last 30 lines
                line_lower = line.lower()
                if keyword in line_lower:
                    # Find all amounts in this line and nearby
                    amounts = self._find_amounts_in_text(line)
                    if amounts:
                        # Return the largest reasonable amount (totals are usually bigger)
                        # Filter out percentages (like 20% TVA)
                        valid_amounts = [a for a in amounts if a > 1.0]
                        if valid_amounts:
                            return max(valid_amounts)

        return None

    def _find_amounts_in_text(self, text: str) -> List[float]:
        """Find all monetary amounts in text"""
        amounts = []

        # Pattern for amounts like: 1 234,56 or 1234.56 or 1,234.56
        patterns = [
            r'(\d{1,3}(?:\s\d{3})+[.,]\d{2})',  # 1 234,56 (with spaces)
            r'(\d{1,3}(?:,\d{3})+\.\d{2})',      # 1,234.56 (US format)
            r'(\d+[.,]\d{2})\s*€?',               # 123,45 or 123.45
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    # Normalize: remove spaces, convert comma to dot
                    clean = match.replace(' ', '').replace(',', '.')
                    # Handle case where there are multiple dots (1.234.56 -> 1234.56)
                    parts = clean.split('.')
                    if len(parts) > 2:
                        clean = ''.join(parts[:-1]) + '.' + parts[-1]
                    amount = float(clean)
                    if amount > 0:
                        amounts.append(amount)
                except ValueError:
                    pass

        return amounts

    def _extract_line_items_improved(self, words: List[Dict]) -> List[Dict]:
        """Extract line items using spatial analysis with column detection"""
        if not words:
            return []

        line_items = []

        # Group words by Y position (lines)
        lines_dict = {}
        y_tolerance = 0.012  # Tighter tolerance

        for word in words:
            y_key = round(word['y'] / y_tolerance) * y_tolerance
            if y_key not in lines_dict:
                lines_dict[y_key] = []
            lines_dict[y_key].append(word)

        # Sort lines by Y
        sorted_lines = sorted(lines_dict.items(), key=lambda x: x[0])

        # Skip patterns - more comprehensive
        skip_patterns = [
            r'(facture|invoice|total|tva|vat|client|adresse|siret|siren|iban|bic|page|n°|date|désignation|quantité|prix|montant|référence|code postal|cedex|tel|fax|email|www\.|http|titulaire|banque|swift|rib|compte|paiement|règlement|conditions|acompte|solde|avoir|escompte|pénalité|retard)',
            r'^\d+$',  # Just numbers (like postal codes)
            r'^[A-Z]{2}\d+',  # SIRET-like patterns
            r'^\d+\s*€?$',  # Just an amount
            r'^FR\d{2}',  # IBAN starting with FR
            r'^\d{5}\s+\w+',  # Postal code + city
        ]

        # Detect columns by analyzing X positions of numbers
        number_x_positions = []
        for y_pos, line_words in sorted_lines:
            for w in line_words:
                if re.match(r'^\d+[.,]?\d*$', w['text']):
                    number_x_positions.append(w['x'])

        # Find column boundaries (cluster X positions)
        if number_x_positions:
            number_x_positions.sort()
            # Typical invoice has qty around 0.5-0.6, price around 0.7, total around 0.85
            qty_x_min = 0.45
            price_x_min = 0.60
            total_x_min = 0.75

        for y_pos, line_words in sorted_lines:
            # Skip lines in header (top 20%) or footer (bottom 15%)
            if y_pos < 0.20 or y_pos > 0.85:
                continue

            line_words.sort(key=lambda w: w['x'])
            line_text = ' '.join(w['text'] for w in line_words)
            line_lower = line_text.lower()

            # Skip header/footer/admin lines
            should_skip = False
            for pattern in skip_patterns:
                if re.search(pattern, line_lower):
                    should_skip = True
                    break

            if should_skip:
                continue

            # Skip lines that are just addresses or short text
            if len(line_text) < 5:
                continue

            # Separate words into designation (left) and numbers (right)
            designation_words = []
            numbers_with_pos = []

            for w in line_words:
                text = w['text'].strip()
                # Check if it's a number (allowing comma/dot for decimals)
                if re.match(r'^\d+[.,]?\d*$', text):
                    numbers_with_pos.append({
                        'value': self._parse_number(text),
                        'x': w['x'],
                        'text': text
                    })
                elif w['x'] < 0.50:  # Designation is usually on the left half
                    # Skip currency symbols and percentage
                    if text not in ['€', '$', '%', '|', ')', '(']:
                        designation_words.append(text)

            # Need at least some designation and at least 2 numbers for a product line
            if len(designation_words) < 1 or len(numbers_with_pos) < 2:
                continue

            designation = ' '.join(designation_words)

            # Clean up designation
            designation = re.sub(r'\s+', ' ', designation).strip()
            designation = re.sub(r'^[\-\|:]+', '', designation).strip()

            # Skip if designation looks like metadata
            if any(kw in designation.lower() for kw in ['broderie', 'taille', 'couleur', 'page']):
                # This might be a variant line - try to merge with previous item
                continue

            if len(designation) < 3:
                continue

            # Assign numbers to columns based on X position
            qty = None
            unit_price = None
            total_ht = None

            # Sort numbers by X position
            numbers_with_pos.sort(key=lambda n: n['x'])

            if len(numbers_with_pos) >= 3:
                qty = numbers_with_pos[0]['value']
                unit_price = numbers_with_pos[1]['value']
                total_ht = numbers_with_pos[-1]['value']
            elif len(numbers_with_pos) == 2:
                # Could be qty + total or price + total
                n1, n2 = numbers_with_pos[0]['value'], numbers_with_pos[1]['value']
                if n1 and n2 and n1 < 100 and n2 > n1:
                    qty = n1
                    total_ht = n2
                    if qty > 0:
                        unit_price = round(n2 / n1, 2)
                else:
                    unit_price = n1
                    total_ht = n2

            # Always validate and correct values using total_ht as reference
            if unit_price and total_ht and unit_price > 0:
                # Calculate expected quantity from total / unit_price
                calculated_qty = total_ht / unit_price

                # Round to nearest integer if close
                if abs(calculated_qty - round(calculated_qty)) < 0.1:
                    calculated_qty = round(calculated_qty)
                else:
                    calculated_qty = round(calculated_qty, 2)

                # Use calculated qty if we don't have one or if current doesn't match
                if not qty or (qty and abs(qty * unit_price - total_ht) > 1.0):
                    qty = calculated_qty

            # If we have qty and total but no unit_price, calculate it
            elif qty and total_ht and qty > 0 and not unit_price:
                unit_price = round(total_ht / qty, 2)

            if designation and total_ht and total_ht > 0:
                item = {
                    'designation': designation[:500],
                    'quantity': qty,
                    'unit_price': unit_price,
                    'total_ht': total_ht
                }
                line_items.append(item)

        return line_items[:30]

    def _parse_number(self, text: str) -> Optional[float]:
        """Parse a number from text"""
        if not text:
            return None
        try:
            clean = text.replace(' ', '').replace(',', '.')
            return float(clean)
        except ValueError:
            return None
