# Copyright 2026 Floriane TUERNAL SABOTINOV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
        os.environ["HF_HOME"] = str(self.cache_dir)
        os.environ["TRANSFORMERS_CACHE"] = str(self.cache_dir)

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
        """
        Extract invoice date from text.

        Prioritizes:
        1. Labeled invoice dates (Date de facture:, Date:, Invoice date:, etc.)
        2. Dates near the top of the document
        3. Any date found in the text
        """
        # French month names
        french_months = r'(?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)'
        # English month names
        english_months = r'(?:january|february|march|april|may|june|july|august|september|october|november|december)'
        # Short month names (both languages)
        short_months = r'(?:jan|fév|fev|feb|mar|avr|apr|mai|may|jun|jui|jul|aoû|aou|aug|sep|sept|oct|nov|déc|dec)'

        all_months = f'(?:{french_months}|{english_months}|{short_months})'

        # Date patterns (more comprehensive)
        date_patterns = [
            # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
            r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            # YYYY-MM-DD (ISO format)
            r'(\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})',
            # DD Month YYYY (e.g., "15 janvier 2024" or "15 January 2024")
            rf'(\d{{1,2}}\s+{all_months}\.?\s+\d{{4}})',
            # Month DD, YYYY (e.g., "January 15, 2024")
            rf'({all_months}\.?\s+\d{{1,2}},?\s+\d{{4}})',
            # DD Month YY (e.g., "15 jan 24")
            rf'(\d{{1,2}}\s+{all_months}\.?\s+\d{{2}})',
        ]

        # Labels that indicate an invoice date (prioritized search)
        date_labels = [
            # French labels
            r'date\s*(?:de\s*)?(?:la\s*)?facture\s*[:\s]*',
            r"date\s*d.?émission\s*[:\s]*",
            r'date\s*[:\s]+',
            r'émise?\s*le\s*[:\s]*',
            r'le\s*[:\s]*(?=\d)',
            r'en\s*date\s*du\s*[:\s]*',
            # English labels
            r'invoice\s*date\s*[:\s]*',
            r'date\s*of\s*invoice\s*[:\s]*',
            r'issue\s*date\s*[:\s]*',
            r'dated?\s*[:\s]+',
            r'bill\s*date\s*[:\s]*',
        ]

        text_lower = text.lower()

        # First, try to find dates near labeled fields
        for label in date_labels:
            # Search for label followed by a date pattern
            for date_pattern in date_patterns:
                combined_pattern = label + r'\s*' + date_pattern
                match = re.search(combined_pattern, text_lower, re.IGNORECASE)
                if match:
                    # Return the captured date group
                    date_value = match.group(1) if match.lastindex else match.group(0)
                    return self._normalize_date(date_value)

        # Second, look in the first 20 lines (header area) for any date
        lines = text.split('\n')[:20]
        header_text = '\n'.join(lines)

        for date_pattern in date_patterns:
            match = re.search(date_pattern, header_text, re.IGNORECASE)
            if match:
                return self._normalize_date(match.group(1))

        # Finally, search the entire document for any date
        for date_pattern in date_patterns:
            match = re.search(date_pattern, text, re.IGNORECASE)
            if match:
                return self._normalize_date(match.group(1))

        return ''

    def _normalize_date(self, date_str: str) -> str:
        """
        Normalize a date string to a consistent format.
        Returns the cleaned date string (max 50 chars).
        """
        if not date_str:
            return ''

        # Clean up the date string
        date_str = date_str.strip()
        date_str = re.sub(r'\s+', ' ', date_str)  # Normalize whitespace

        return date_str[:50]

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

    def _detect_column_headers(self, words: List[Dict], sorted_lines: List) -> Dict[str, float]:
        """
        Detect column headers and their X positions.
        Returns a dict mapping column type to X position.
        """
        # Column header patterns (French and English)
        column_patterns = {
            'designation': [
                r'\bdésignation\b', r'\bdescription\b', r'\blibellé\b', r'\blibelle\b',
                r'\barticle\b', r'\bproduit\b', r'\bservice\b', r'\bprestation\b',
                r'\bitem\b', r'\bdetail\b', r'\bdétail\b'
            ],
            'quantity': [
                r'\bquantité\b', r'\bquantite\b', r'\bqté\b', r'\bqte\b', r'\bqty\b',
                r'\bnombre\b', r'\bnb\b', r'\bquantity\b', r'\bunits?\b'
            ],
            'unit_price': [
                r'\bprix\s*unitaire\b', r'\bp\.?\s*u\.?\b', r'\bpu\b', r'\bprix\s*unit\.?\b',
                r'\bunit\s*price\b', r'\btarif\b', r'\bprix\b', r'\brate\b',
                r'\bunitaire\b', r'\bunit\b'
            ],
            'total': [
                r'\btotal\s*h\.?t\.?\b', r'\bmontant\s*h\.?t\.?\b', r'\btotal\b',
                r'\bmontant\b', r'\bamount\b', r'\bsomme\b', r'\bnet\b'
            ],
            'vat': [
                r'\btva\b', r'\bvat\b', r'\btaxe\b', r'\btax\b'
            ]
        }

        column_positions = {}

        # Search in the top portion of the document for header row
        for y_pos, line_words in sorted_lines:
            if y_pos > 0.35:  # Headers should be in top 35%
                break

            line_words_sorted = sorted(line_words, key=lambda w: w['x'])
            line_text = ' '.join(w['text'] for w in line_words_sorted).lower()

            # Check if this line looks like a header row (multiple column keywords)
            matches_found = 0
            for col_type, patterns in column_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, line_text, re.IGNORECASE):
                        matches_found += 1
                        break

            # If we found at least 2 column keywords, this is likely the header row
            if matches_found >= 2:
                for w in line_words_sorted:
                    word_lower = w['text'].lower()
                    for col_type, patterns in column_patterns.items():
                        if col_type not in column_positions:
                            for pattern in patterns:
                                if re.search(pattern, word_lower, re.IGNORECASE):
                                    column_positions[col_type] = w['x']
                                    break

                # If we found headers, stop searching
                if len(column_positions) >= 2:
                    logger.debug("Detected column headers", positions=column_positions)
                    break

        return column_positions

    def _assign_values_by_columns(
        self,
        numbers_with_pos: List[Dict],
        column_positions: Dict[str, float]
    ) -> Dict[str, Optional[float]]:
        """
        Assign numeric values to columns based on detected header positions.
        """
        result = {'quantity': None, 'unit_price': None, 'total_ht': None}

        if not numbers_with_pos:
            return result

        # If we have column positions, use them
        if column_positions:
            tolerance = 0.08  # X position tolerance for matching

            for num in numbers_with_pos:
                x_pos = num['x']
                value = num['value']

                # Find the closest column header
                best_match = None
                best_distance = float('inf')

                for col_type in ['quantity', 'unit_price', 'total']:
                    if col_type in column_positions:
                        distance = abs(x_pos - column_positions[col_type])
                        if distance < best_distance and distance < tolerance:
                            best_distance = distance
                            best_match = col_type

                if best_match:
                    key = 'total_ht' if best_match == 'total' else best_match
                    if result[key] is None:  # Don't overwrite
                        result[key] = value

        # Fallback: if columns weren't detected or didn't match all values
        if result['total_ht'] is None and numbers_with_pos:
            # Total is usually the rightmost and largest value
            numbers_with_pos_sorted = sorted(numbers_with_pos, key=lambda n: n['x'])
            result['total_ht'] = numbers_with_pos_sorted[-1]['value']

        return result

    def _extract_line_items_improved(self, words: List[Dict]) -> List[Dict]:
        """Extract line items using spatial analysis with column header detection"""
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

        # Detect column headers first
        column_positions = self._detect_column_headers(words, sorted_lines)

        # Skip patterns - more comprehensive
        skip_patterns = [
            r'(facture|invoice|total\s+h\.?t|total\s+t\.?t\.?c|tva|vat|client|adresse|siret|siren|iban|bic|page|n°|date|désignation|quantité|prix|montant|référence|code postal|cedex|tel|fax|email|www\.|http|titulaire|banque|swift|rib|compte|paiement|règlement|conditions|acompte|solde|avoir|escompte|pénalité|retard)',
            r'^\d+$',  # Just numbers (like postal codes)
            r'^[A-Z]{2}\d+',  # SIRET-like patterns
            r'^\d+\s*€?$',  # Just an amount
            r'^FR\d{2}',  # IBAN starting with FR
            r'^\d{5}\s+\w+',  # Postal code + city
        ]

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

            # Determine designation boundary (use column position if available)
            designation_x_max = column_positions.get('designation', 0.0) + 0.25
            if designation_x_max < 0.30:
                designation_x_max = 0.50  # Default fallback

            for w in line_words:
                text = w['text'].strip()
                # Check if it's a number (allowing comma/dot for decimals)
                if re.match(r'^\d+[.,]?\d*$', text):
                    numbers_with_pos.append({
                        'value': self._parse_number(text),
                        'x': w['x'],
                        'text': text
                    })
                elif w['x'] < designation_x_max:
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
                continue

            if len(designation) < 3:
                continue

            # Assign numbers to columns using detected header positions
            values = self._assign_values_by_columns(numbers_with_pos, column_positions)
            qty = values['quantity']
            unit_price = values['unit_price']
            total_ht = values['total_ht']

            # If column detection didn't work well, fall back to heuristics
            if not column_positions or (total_ht and not qty and not unit_price):
                numbers_with_pos.sort(key=lambda n: n['x'])

                if len(numbers_with_pos) >= 3:
                    # Use mathematical validation to determine correct order
                    n1, n2, n3 = [n['value'] for n in numbers_with_pos[:3]]

                    # Try qty, price, total order
                    if n1 and n2 and n3 and abs(n1 * n2 - n3) < 1.0:
                        qty, unit_price, total_ht = n1, n2, n3
                    # Try price, qty, total order
                    elif n1 and n2 and n3 and abs(n2 * n1 - n3) < 1.0:
                        unit_price, qty, total_ht = n1, n2, n3
                    else:
                        # Default: assume rightmost is total, then work backwards
                        total_ht = numbers_with_pos[-1]['value']
                        # The smaller non-total value is likely quantity
                        remaining = [n['value'] for n in numbers_with_pos[:-1] if n['value']]
                        if len(remaining) >= 2:
                            if remaining[0] < remaining[1]:
                                qty, unit_price = remaining[0], remaining[1]
                            else:
                                unit_price, qty = remaining[0], remaining[1]
                        elif len(remaining) == 1:
                            # Only one other number - determine if it's qty or price
                            if remaining[0] < 100 and total_ht and remaining[0] < total_ht:
                                qty = remaining[0]
                            else:
                                unit_price = remaining[0]

                elif len(numbers_with_pos) == 2:
                    n1, n2 = numbers_with_pos[0]['value'], numbers_with_pos[1]['value']
                    if n1 and n2:
                        # Larger value is likely total
                        if n2 > n1:
                            total_ht = n2
                            if n1 < 100:  # Small number likely quantity
                                qty = n1
                            else:
                                unit_price = n1
                        else:
                            total_ht = n1
                            if n2 < 100:
                                qty = n2
                            else:
                                unit_price = n2

            # Validate and correct using mathematical relationship: qty * unit_price = total
            if total_ht and total_ht > 0:
                if qty and unit_price:
                    # Check if the math works out
                    expected_total = qty * unit_price
                    if abs(expected_total - total_ht) > 1.0:
                        # Values might be swapped, try the other way
                        if abs(unit_price * qty - total_ht) < 1.0:
                            pass  # Already correct
                        elif qty > 0 and abs(total_ht / qty - unit_price) > 1.0:
                            # Recalculate unit_price from total/qty
                            unit_price = round(total_ht / qty, 2)

                elif qty and qty > 0 and not unit_price:
                    unit_price = round(total_ht / qty, 2)

                elif unit_price and unit_price > 0 and not qty:
                    calculated_qty = total_ht / unit_price
                    if abs(calculated_qty - round(calculated_qty)) < 0.1:
                        qty = round(calculated_qty)
                    else:
                        qty = round(calculated_qty, 2)

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
