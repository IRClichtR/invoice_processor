from transformers import AutoProcessor, AutoModelForCausalLM
from PIL import Image
import torch
from typing import Dict, Any, List, Optional, Tuple
import json
import re
from collections import defaultdict
from app.core.config import settings


class FlorenceService:
    """Florence-2 VLM service for structured invoice data extraction"""

    def __init__(self):
        self.model_name = settings.FLORENCE_MODEL
        self.device = settings.DEVICE if torch.cuda.is_available() else "cpu"
        self.model = None
        self.processor = None

    def load_model(self):
        """Load Florence-2 model and processor"""
        if self.model is None:
            print(f"Loading Florence-2 model: {self.model_name}")
            self.processor = AutoProcessor.from_pretrained(
                self.model_name,
                trust_remote_code=True
            )
            # Load model without flash_attn (use eager attention for CPU compatibility)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                attn_implementation="eager"  # Use eager attention instead of flash_attn
            ).to(self.device)
            print(f"Model loaded on device: {self.device}")

    def extract_invoice_data(
        self,
        image: Image.Image,
        ocr_text: str,
        ocr_word_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Extract structured invoice data using Florence-2 VLM

        Args:
            image: PIL Image of invoice
            ocr_text: Full text from OCR
            ocr_word_data: Detailed word-level OCR data with positions

        Returns:
            Structured invoice data as dictionary
        """
        if image is None:
            raise ValueError("Image is None - cannot process")

        if not isinstance(image, Image.Image):
            raise ValueError(f"Image must be PIL Image, got {type(image)}")

        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')

        self.load_model()

        # Use OCR task to get text with bounding boxes
        task_prompt = "<OCR_WITH_REGION>"

        # Process image
        print(f"DEBUG: Processing image of size {image.size}, mode {image.mode}")
        inputs = self.processor(
            text=task_prompt,
            images=image,
            return_tensors="pt"
        )

        print(f"DEBUG: Inputs keys: {inputs.keys()}")
        if 'pixel_values' in inputs:
            pv = inputs['pixel_values']
            print(f"DEBUG: pixel_values type: {type(pv)}, is None: {pv is None}")
            if pv is not None:
                print(f"DEBUG: pixel_values shape: {pv.shape}")
        else:
            print("DEBUG: pixel_values not in inputs!")

        inputs = inputs.to(self.device)

        # Generate response
        # Note: Disabling cache to avoid past_key_values issues with Florence-2
        with torch.no_grad():
            generated_ids = self.model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=1024,
                num_beams=1,
                use_cache=False
            )

        # Decode response
        generated_text = self.processor.batch_decode(
            generated_ids,
            skip_special_tokens=False
        )[0]

        # Post-process the OCR results
        parsed_answer = self.processor.post_process_generation(
            generated_text,
            task=task_prompt,
            image_size=(image.width, image.height)
        )

        # Parse the Florence response and combine with our OCR data
        structured_data = self._parse_florence_ocr_response(
            parsed_answer,
            ocr_text,
            ocr_word_data
        )

        return {
            'structured_data': structured_data,
            'raw_response': str(parsed_answer),
            'model_used': self.model_name
        }

    def _parse_florence_ocr_response(
        self,
        florence_result: Dict[str, Any],
        ocr_text: str,
        ocr_word_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Parse Florence-2 OCR results and extract invoice data

        Args:
            florence_result: Parsed Florence-2 response
            ocr_text: Original OCR text
            ocr_word_data: OCR word-level data

        Returns:
            Structured invoice data
        """
        import re

        # Initialize structured data
        invoice_data = {
            'provider': '',
            'invoice_number': '',
            'date': '',
            'total_ht': 0.0,
            'total_ttc': 0.0,
            'vat_amount': 0.0,
            'line_items': []
        }

        # Use combined OCR text for extraction
        text = ocr_text

        # Extract provider (first non-empty line)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if lines:
            invoice_data['provider'] = lines[0][:100]

        # Extract invoice number with improved patterns
        invoice_patterns = [
            r'FACTURE\s*N[°#:]*\s*([A-Z0-9\-/]+)',
            r'N[°#]\s*([0-9\-/]+)',
            r'Invoice\s*[#:]*\s*([A-Z0-9\-/]+)'
        ]
        for pattern in invoice_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                invoice_data['invoice_number'] = match.group(1)
                break

        # Extract date
        date_patterns = [
            r'Date\s*:?\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                invoice_data['date'] = match.group(1)
                break

        # Extract totals - look at end of document
        lines_reversed = list(reversed(lines))

        for i, line in enumerate(lines_reversed):
            line_lower = line.lower()

            # Look for total HT/without VAT
            if any(keyword in line_lower for keyword in ['total ht', 'sous-total', 'subtotal', 'ht :']):
                # Find numbers in this line and nearby lines
                amount = self._extract_amount_from_line(line)
                if amount > 0:
                    invoice_data['total_ht'] = amount

            # Look for total TTC/with VAT
            if any(keyword in line_lower for keyword in ['total ttc', 'total général', 'net à payer', 'ttc :']):
                amount = self._extract_amount_from_line(line)
                if amount > 0:
                    invoice_data['total_ttc'] = amount

            # Look for TVA/VAT
            if any(keyword in line_lower for keyword in ['tva', 'vat', 'taxe']):
                amount = self._extract_amount_from_line(line)
                if amount > 0:
                    invoice_data['vat_amount'] = amount

        # Extract line items using Florence OCR results
        invoice_data['line_items'] = self._extract_line_items(text, ocr_word_data)

        return invoice_data

    def _extract_amount_from_line(self, line: str) -> float:
        """Extract monetary amount from a line of text"""
        import re

        # Remove currency symbols
        line = line.replace('€', '').replace('EUR', '')

        # Look for number patterns
        patterns = [
            r'(\d+\s*\d*\s*,\s*\d{2})',  # 1 234,56
            r'(\d+\s*\d*\.\s*\d{2})',    # 1 234.56
            r'(\d+,\d{2})',               # 123,56
            r'(\d+\.\d{2})',              # 123.56
        ]

        for pattern in patterns:
            matches = re.findall(pattern, line)
            if matches:
                # Take the last (rightmost) number as it's usually the total
                amount_str = matches[-1].replace(' ', '').replace(',', '.')
                try:
                    return float(amount_str)
                except ValueError:
                    continue

        return 0.0

    def _parse_florence_response(
        self,
        response: str,
        ocr_text: str,
        ocr_word_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Parse Florence-2 response and combine with OCR data to create structured output

        Args:
            response: Raw response from Florence-2
            ocr_text: Original OCR text
            ocr_word_data: OCR word-level data

        Returns:
            Structured invoice data
        """
        structured = {
            'provider': self._extract_field(ocr_text, ['fournisseur', 'supplier', 'provider', 'vendeur', 'emetteur']),
            'invoice_number': self._extract_invoice_number(ocr_text),
            'date': self._extract_date(ocr_text),
            'total_ht': self._extract_amount(ocr_text, ['total ht', 'total without vat', 'sous-total', 'subtotal']),
            'total_ttc': self._extract_amount(ocr_text, ['total ttc', 'total with vat', 'montant total', 'net à payer']),
            'vat_amount': self._extract_amount(ocr_text, ['tva', 'vat', 'taxe']),
            'line_items': self._extract_line_items(ocr_text, ocr_word_data),
            'florence_response': response
        }

        return structured

    def _extract_field(self, text: str, keywords: List[str]) -> str:
        """Extract a field value based on keywords"""
        text_lower = text.lower()
        for keyword in keywords:
            if keyword in text_lower:
                # Simple extraction: get the next few words after keyword
                idx = text_lower.index(keyword)
                remaining = text[idx + len(keyword):idx + len(keyword) + 100]
                # Extract until newline or special characters
                value = remaining.split('\n')[0].strip(' :-')
                if value:
                    return value[:50]  # Limit length
        return ""

    def _extract_invoice_number(self, text: str) -> str:
        """Extract invoice number with specific patterns"""
        patterns = [
            r'(?:facture|invoice)\s*[n°#:]*\s*([A-Z0-9\-/]+)',
            r'n°\s*([A-Z0-9\-/]+)',
            r'#\s*([A-Z0-9\-/]+)'
        ]

        text_lower = text.lower()
        for pattern in patterns:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            if matches:
                return matches[0].upper()
        return ""

    def _extract_date(self, text: str) -> str:
        """Extract date in various formats"""
        patterns = [
            r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b',  # DD/MM/YYYY or MM/DD/YYYY
            r'\b(\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4})\b',  # French format
            r'\b(\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4})\b',  # English format
            r'\b(\d{4}-\d{2}-\d{2})\b'  # ISO format
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0]
        return ""

    def _extract_amount(self, text: str, keywords: List[str]) -> float:
        """Extract monetary amount based on keywords"""
        text_lower = text.lower()

        for keyword in keywords:
            if keyword in text_lower:
                idx = text_lower.index(keyword)
                remaining = text[idx:idx + 150]

                # Look for patterns like 1234.56, 1 234,56, 1,234.56 €
                patterns = [
                    r'(\d{1,3}(?:[\s,]\d{3})*[.,]\d{2})',  # 1 234,56 or 1,234.56
                    r'(\d+[.,]\d{2})',  # 1234.56
                    r'(\d+)'  # Fallback to integer
                ]

                for pattern in patterns:
                    matches = re.findall(pattern, remaining)
                    if matches:
                        # Clean and convert to float
                        amount_str = matches[0].replace(' ', '').replace(',', '.')
                        try:
                            return float(amount_str)
                        except ValueError:
                            continue

        return 0.0

    def _extract_line_items(
        self,
        text: str,
        ocr_word_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Sophisticated line item extraction using table detection from OCR positions

        This method:
        1. Groups words into lines based on vertical position
        2. Detects table headers (Désignation, Quantité, Prix, etc.)
        3. Identifies columns based on horizontal alignment
        4. Extracts structured line items

        Args:
            text: Full OCR text
            ocr_word_data: List of word-level OCR data with positions

        Returns:
            List of structured line items
        """
        if not ocr_word_data:
            return []

        # Step 1: Group words into lines based on vertical position
        lines = self._group_words_into_lines(ocr_word_data)

        # Step 2: Detect table headers and column positions
        header_info = self._detect_table_headers(lines)

        if not header_info:
            # Fallback to simple text-based extraction
            return self._fallback_line_extraction(text)

        # Step 3: Extract table rows (line items)
        line_items = self._extract_table_rows(lines, header_info)

        return line_items

    def _group_words_into_lines(
        self,
        ocr_word_data: List[Dict[str, Any]],
        vertical_tolerance: int = 10
    ) -> List[List[Dict[str, Any]]]:
        """
        Group OCR words into lines based on vertical position

        Args:
            ocr_word_data: Word-level OCR data
            vertical_tolerance: Vertical pixel tolerance for grouping

        Returns:
            List of lines, where each line is a list of words
        """
        if not ocr_word_data:
            return []

        # Sort words by vertical position (top), then horizontal (left)
        sorted_words = sorted(ocr_word_data, key=lambda w: (w['top'], w['left']))

        lines = []
        current_line = [sorted_words[0]]
        current_y = sorted_words[0]['top']

        for word in sorted_words[1:]:
            # If word is on same line (within tolerance)
            if abs(word['top'] - current_y) <= vertical_tolerance:
                current_line.append(word)
            else:
                # New line
                lines.append(current_line)
                current_line = [word]
                current_y = word['top']

        # Add last line
        if current_line:
            lines.append(current_line)

        return lines

    def _detect_table_headers(
        self,
        lines: List[List[Dict[str, Any]]]
    ) -> Optional[Dict[str, Any]]:
        """
        Detect table headers and column positions

        Looks for keywords like: Désignation, Quantité, Prix, Total, etc.

        Args:
            lines: Grouped lines of words

        Returns:
            Dictionary with header information and column positions
        """
        header_keywords = {
            'designation': ['désignation', 'designation', 'description', 'libellé', 'libelle', 'article', 'produit'],
            'quantity': ['quantité', 'quantite', 'quantity', 'qté', 'qte', 'qty'],
            'unit': ['unité', 'unite', 'unit', 'u.'],
            'unit_price': ['prix unitaire', 'unit price', 'p.u.', 'pu', 'prix', 'price'],
            'total_ht': ['total ht', 'total', 'montant', 'amount']
        }

        for line_idx, line in enumerate(lines):
            line_text = ' '.join([w['text'].lower() for w in line])

            # Check if this line contains header keywords
            matches = {}
            for field, keywords in header_keywords.items():
                for word in line:
                    word_lower = word['text'].lower()
                    if any(keyword in word_lower for keyword in keywords):
                        matches[field] = {
                            'x_position': word['left'],
                            'width': word['width'],
                            'text': word['text']
                        }
                        break

            # If we found at least 3 header columns, consider this the header row
            if len(matches) >= 3:
                return {
                    'line_index': line_idx,
                    'columns': matches,
                    'header_line': line
                }

        return None

    def _extract_table_rows(
        self,
        lines: List[List[Dict[str, Any]]],
        header_info: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Extract table rows based on detected column positions

        Args:
            lines: All text lines
            header_info: Header information with column positions

        Returns:
            List of structured line items
        """
        line_items = []
        header_idx = header_info['line_index']
        columns = header_info['columns']

        # Define column x-ranges with tolerance
        tolerance = 50  # pixels

        # Process lines after header
        for line in lines[header_idx + 1:]:
            # Skip if line is too short or looks like a total/summary
            line_text = ' '.join([w['text'].lower() for w in line])
            if any(keyword in line_text for keyword in ['total', 'sous-total', 'subtotal', 'tva', 'vat']):
                continue

            if len(line) < 2:
                continue

            # Extract data for each column
            item = {
                'designation': '',
                'quantity': None,
                'unit': '',
                'unit_price': None,
                'total_ht': None
            }

            # Group words by column
            for word in line:
                word_center = word['left'] + word['width'] / 2

                # Determine which column this word belongs to
                for field, col_info in columns.items():
                    col_center = col_info['x_position'] + col_info['width'] / 2

                    if abs(word_center - col_center) <= tolerance:
                        # Assign word to column
                        if field == 'designation':
                            item['designation'] += ' ' + word['text']
                        elif field == 'quantity':
                            item['quantity'] = self._parse_number(word['text'])
                        elif field == 'unit':
                            item['unit'] = word['text']
                        elif field == 'unit_price':
                            item['unit_price'] = self._parse_number(word['text'])
                        elif field == 'total_ht':
                            item['total_ht'] = self._parse_number(word['text'])
                        break
                else:
                    # Word doesn't match any column - might be part of designation
                    if word['left'] < min(col['x_position'] for col in columns.values() if col['x_position'] > 0):
                        item['designation'] += ' ' + word['text']

            # Clean up designation
            item['designation'] = item['designation'].strip()

            # Only add if we have at least designation and one numeric value
            if item['designation'] and (item['quantity'] or item['unit_price'] or item['total_ht']):
                line_items.append(item)

        return line_items

    def _parse_number(self, text: str) -> Optional[float]:
        """
        Parse a number from text, handling various formats

        Args:
            text: Text containing a number

        Returns:
            Parsed float or None
        """
        # Remove currency symbols and extra spaces
        cleaned = re.sub(r'[€$£\s]', '', text)

        # Replace comma with period for decimal
        cleaned = cleaned.replace(',', '.')

        # Extract number
        match = re.search(r'\d+\.?\d*', cleaned)
        if match:
            try:
                return float(match.group())
            except ValueError:
                pass

        return None

    def _fallback_line_extraction(self, text: str) -> List[Dict[str, Any]]:
        """
        Fallback line item extraction when table structure cannot be detected

        Uses heuristics to identify line items from plain text

        Args:
            text: Full OCR text

        Returns:
            List of line items
        """
        line_items = []
        lines = text.split('\n')

        # Pattern for line items: typically contains text followed by numbers
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Skip headers and totals
            if any(keyword in line.lower() for keyword in [
                'désignation', 'designation', 'quantité', 'quantity',
                'total ttc', 'total ht', 'tva', 'vat'
            ]):
                continue

            # Look for lines with both text and numbers
            has_text = any(c.isalpha() for c in line)
            has_number = any(c.isdigit() for c in line)

            if has_text and has_number:
                # Extract numbers from line
                numbers = re.findall(r'\d+[.,]?\d*', line)

                # Remove numbers to get designation
                designation = line
                for num in numbers:
                    designation = designation.replace(num, '', 1)

                # Clean designation
                designation = re.sub(r'\s+', ' ', designation).strip()

                # Try to assign numbers to fields
                parsed_numbers = [self._parse_number(n) for n in numbers]
                parsed_numbers = [n for n in parsed_numbers if n is not None]

                if designation and parsed_numbers:
                    item = {
                        'designation': designation,
                        'quantity': parsed_numbers[0] if len(parsed_numbers) > 0 else None,
                        'unit': '',
                        'unit_price': parsed_numbers[1] if len(parsed_numbers) > 1 else None,
                        'total_ht': parsed_numbers[-1] if len(parsed_numbers) > 0 else None
                    }
                    line_items.append(item)

        return line_items[:20]  # Limit to 20 items
