from typing import Dict, Any, List, Tuple
import re


class ValidationService:
    """Service for validating invoices and documents"""

    @staticmethod
    def is_invoice(ocr_text: str) -> Tuple[bool, float]:
        """
        Check if document is an invoice by looking for keywords

        Args:
            ocr_text: Full OCR text

        Returns:
            Tuple of (is_invoice, confidence_score)
        """
        text_lower = ocr_text.lower()

        # Primary keywords - sufficient on their own to identify an invoice
        primary_keywords = [
            'facture',
            'invoice',
            'n° facture',
            'numéro facture',
            'invoice number',
            'invoice #'
        ]

        # Secondary keywords - support invoice detection
        secondary_keywords_french = [
            'total ttc',
            'total ht',
            'tva',
            'montant total',
            'sous-total',
            'ht',
            'ttc'
        ]

        secondary_keywords_english = [
            'total amount',
            'vat',
            'subtotal',
            'tax',
            'net amount'
        ]

        all_secondary = secondary_keywords_french + secondary_keywords_english

        # Check for primary keywords (strong indicators)
        primary_matches = sum(1 for keyword in primary_keywords if keyword in text_lower)

        # Check for secondary keywords (supporting evidence)
        secondary_matches = sum(1 for keyword in all_secondary if keyword in text_lower)

        # Determine if document is an invoice
        # Case 1: Has primary keyword (facture/invoice) -> definitely an invoice
        # Case 2: Has 2+ secondary keywords -> likely an invoice
        is_invoice = primary_matches >= 1 or secondary_matches >= 2

        # Calculate confidence score
        if primary_matches >= 1:
            # High confidence if we have primary keyword
            base_confidence = 0.7
            # Increase confidence with secondary keywords
            confidence = min(base_confidence + (secondary_matches * 0.1), 1.0)
        else:
            # Lower confidence if only secondary keywords
            confidence = min(secondary_matches / 5.0, 0.6)

        return is_invoice, confidence

    @staticmethod
    def validate_vat_calculation(
        total_ht: float,
        total_ttc: float,
        vat_rate: float = 20.0,
        tolerance: float = 0.5
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate VAT calculation

        Args:
            total_ht: Total without VAT
            total_ttc: Total with VAT
            vat_rate: Expected VAT rate (default 20% for France)
            tolerance: Tolerance in euros for validation

        Returns:
            Tuple of (is_valid, validation_details)
        """
        if total_ht <= 0 or total_ttc <= 0:
            return False, {
                'error': 'Invalid amounts',
                'total_ht': total_ht,
                'total_ttc': total_ttc
            }

        # Calculate expected VAT amount
        expected_vat = total_ht * (vat_rate / 100.0)
        expected_total_ttc = total_ht + expected_vat

        # Calculate actual VAT
        actual_vat = total_ttc - total_ht

        # Check if calculation is correct within tolerance
        difference = abs(expected_total_ttc - total_ttc)
        is_valid = difference <= tolerance

        # Calculate effective VAT rate
        effective_vat_rate = (actual_vat / total_ht) * 100 if total_ht > 0 else 0

        validation_details = {
            'is_valid': is_valid,
            'total_ht': total_ht,
            'total_ttc': total_ttc,
            'expected_vat': round(expected_vat, 2),
            'actual_vat': round(actual_vat, 2),
            'expected_total_ttc': round(expected_total_ttc, 2),
            'difference': round(difference, 2),
            'effective_vat_rate': round(effective_vat_rate, 2),
            'expected_vat_rate': vat_rate,
            'tolerance': tolerance
        }

        return is_valid, validation_details

    @staticmethod
    def validate_line_items_sum(
        line_items: List[Dict[str, Any]],
        declared_total_ht: float,
        tolerance: float = 0.5
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate that line items sum matches the declared total

        Args:
            line_items: List of invoice line items
            declared_total_ht: Declared total without VAT
            tolerance: Tolerance in euros

        Returns:
            Tuple of (is_valid, validation_details)
        """
        if not line_items:
            return False, {
                'error': 'No line items to validate',
                'declared_total': declared_total_ht
            }

        # Calculate sum of line items
        calculated_total = 0.0
        valid_items = 0

        for item in line_items:
            total_ht = item.get('total_ht')
            if total_ht is not None and total_ht > 0:
                calculated_total += total_ht
                valid_items += 1
            else:
                # Try to calculate from quantity and unit price
                qty = item.get('quantity')
                unit_price = item.get('unit_price')
                if qty and unit_price:
                    calculated_total += qty * unit_price
                    valid_items += 1

        # Check if sum matches
        difference = abs(calculated_total - declared_total_ht)
        is_valid = difference <= tolerance

        validation_details = {
            'is_valid': is_valid,
            'declared_total_ht': declared_total_ht,
            'calculated_total_ht': round(calculated_total, 2),
            'difference': round(difference, 2),
            'valid_items_count': valid_items,
            'total_items_count': len(line_items),
            'tolerance': tolerance
        }

        return is_valid, validation_details

    @staticmethod
    def validate_invoice_completeness(
        invoice_data: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        Validate that invoice has all required fields

        Args:
            invoice_data: Extracted invoice data

        Returns:
            Tuple of (is_complete, list_of_missing_fields)
        """
        required_fields = [
            'provider',
            'invoice_number',
            'date',
            'total_ht',
            'total_ttc'
        ]

        missing_fields = []

        for field in required_fields:
            value = invoice_data.get(field)
            if not value or (isinstance(value, (int, float)) and value <= 0):
                missing_fields.append(field)

        is_complete = len(missing_fields) == 0

        return is_complete, missing_fields

    @classmethod
    def validate_full_invoice(
        cls,
        ocr_text: str,
        invoice_data: Dict[str, Any],
        vat_rate: float = 20.0
    ) -> Dict[str, Any]:
        """
        Perform full validation of invoice

        Args:
            ocr_text: OCR text
            invoice_data: Extracted invoice data
            vat_rate: Expected VAT rate

        Returns:
            Complete validation report
        """
        validation_report = {
            'is_valid_invoice': False,
            'validations': {}
        }

        # 1. Check if document is an invoice
        is_invoice, invoice_confidence = cls.is_invoice(ocr_text)
        validation_report['validations']['document_type'] = {
            'is_invoice': is_invoice,
            'confidence': invoice_confidence
        }

        if not is_invoice:
            validation_report['overall_valid'] = False
            validation_report['reason'] = 'Document is not an invoice'
            return validation_report

        # 2. Check completeness
        is_complete, missing_fields = cls.validate_invoice_completeness(invoice_data)
        validation_report['validations']['completeness'] = {
            'is_complete': is_complete,
            'missing_fields': missing_fields
        }

        # 3. Validate VAT calculation
        total_ht = invoice_data.get('total_ht', 0)
        total_ttc = invoice_data.get('total_ttc', 0)

        if total_ht > 0 and total_ttc > 0:
            vat_valid, vat_details = cls.validate_vat_calculation(
                total_ht, total_ttc, vat_rate
            )
            validation_report['validations']['vat'] = vat_details
        else:
            validation_report['validations']['vat'] = {
                'is_valid': False,
                'error': 'Missing or invalid total amounts'
            }

        # 4. Validate line items sum
        line_items = invoice_data.get('line_items', [])
        if line_items and total_ht > 0:
            line_sum_valid, line_sum_details = cls.validate_line_items_sum(
                line_items, total_ht
            )
            validation_report['validations']['line_items_sum'] = line_sum_details
        else:
            validation_report['validations']['line_items_sum'] = {
                'is_valid': None,
                'note': 'No line items to validate or missing total'
            }

        # Overall validation
        vat_validation = validation_report['validations'].get('vat', {})
        validation_report['overall_valid'] = (
            is_invoice and
            is_complete and
            vat_validation.get('is_valid', False)
        )

        return validation_report
