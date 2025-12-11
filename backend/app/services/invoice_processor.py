from typing import Dict, Any, List
from PIL import Image
import os
from sqlalchemy.orm import Session

from app.utils.pdf_converter import PDFConverter
from app.utils.image_preprocessor import ImagePreprocessor
from app.utils.adaptive_preprocessor import AdaptivePreprocessor
from app.services.ocr_service import OCRService
from app.services.model_manager import get_qwen_service
from app.services.validation_service import ValidationService
from app.models.invoice import Invoice, InvoiceLine, OtherDocument


class InvoiceProcessor:
    """Main service for processing invoice PDFs"""

    def __init__(self):
        self.pdf_converter = PDFConverter()
        self.preprocessor = ImagePreprocessor()
        self.adaptive_preprocessor = AdaptivePreprocessor()
        self.ocr_service = OCRService()
        self.qwen_service = get_qwen_service()  # Use global singleton
        self.validation_service = ValidationService()

    def process_pdf(
        self,
        pdf_path: str,
        db: Session,
        preprocessing_mode: str = 'adaptive',
        original_filename: str = None
    ) -> Dict[str, Any]:
        """
        Process a PDF file through the complete pipeline

        Args:
            pdf_path: Path to PDF file
            db: Database session
            preprocessing_mode: Preprocessing mode to use
            original_filename: Original filename of the uploaded file

        Returns:
            Processing result with database IDs and validation status
        """
        result = {
            'success': False,
            'pdf_path': pdf_path,
            'processing_steps': {}
        }

        try:
            # Step 1: Convert PDF to images
            images = self.pdf_converter.pdf_to_images(pdf_path)
            result['processing_steps']['pdf_conversion'] = {
                'success': True,
                'page_count': len(images)
            }

            # Step 2: Preprocess images using adaptive method
            preprocessed_images = []
            preprocessing_reports = []

            for img in images:
                if preprocessing_mode == 'none':
                    # No preprocessing
                    preprocessed_images.append(img)
                elif preprocessing_mode == 'adaptive':
                    # Smart preprocessing based on image quality
                    preprocessed, report = self.adaptive_preprocessor.smart_preprocess(img)
                    preprocessed_images.append(preprocessed)
                    preprocessing_reports.append(report)
                else:
                    # Use specified mode: 'gentle', 'aggressive', etc.
                    preprocessed = self.adaptive_preprocessor.preprocess_for_ocr(img, mode=preprocessing_mode)
                    preprocessed_images.append(preprocessed)

            result['processing_steps']['preprocessing'] = {
                'success': True,
                'mode': preprocessing_mode,
                'images_processed': len(preprocessed_images),
                'quality_reports': preprocessing_reports if preprocessing_mode == 'adaptive' else None
            }

            # Step 3: OCR extraction
            ocr_results = self.ocr_service.extract_from_multiple_images(preprocessed_images)

            # Combine OCR text from all pages
            full_text = '\n\n--- Page Break ---\n\n'.join([
                page['full_text'] for page in ocr_results
            ])

            # Get word data from first page (main invoice page)
            main_page_words = ocr_results[0]['word_data'] if ocr_results else []
            avg_confidence = sum(page['average_confidence'] for page in ocr_results) / len(ocr_results)

            result['processing_steps']['ocr'] = {
                'success': True,
                'pages_processed': len(ocr_results),
                'average_confidence': round(avg_confidence, 2)
            }

            # Step 4: Validate if document is an invoice
            is_invoice, invoice_confidence = self.validation_service.is_invoice(full_text)

            result['processing_steps']['validation'] = {
                'is_invoice': is_invoice,
                'confidence': round(invoice_confidence, 2),
                'ocr_text_sample': full_text[:500] if full_text else "NO TEXT EXTRACTED",
                'ocr_text_length': len(full_text)
            }

            if not is_invoice:
                # Store as other document
                other_doc = self._save_other_document(db, full_text, original_filename)
                result['success'] = True
                result['document_type'] = 'other'
                result['document_id'] = other_doc.id
                return result

            # Step 5: VLM extraction (Qwen2-VL) - Optional, use OCR fallback if it fails
            try:
                vlm_result = self.qwen_service.extract_invoice_data(
                    preprocessed_images[0],  # Use first page
                    full_text,
                    main_page_words
                )

                invoice_data = vlm_result['structured_data']

                result['processing_steps']['vlm_extraction'] = {
                    'success': True,
                    'model': vlm_result['model_used']
                }
            except Exception as e:
                # Qwen2-VL failed, use OCR-only extraction
                import traceback
                error_traceback = traceback.format_exc()
                print(f"ERROR in Qwen2-VL extraction: {str(e)}")
                print(f"Full traceback:\n{error_traceback}")

                result['processing_steps']['vlm_extraction'] = {
                    'success': False,
                    'error': str(e),
                    'fallback': 'Using OCR-only extraction'
                }

                # Use OCR-based extraction as fallback
                invoice_data = self._extract_from_ocr_only(full_text, main_page_words)

            # Step 6: Full validation
            validation_report = self.validation_service.validate_full_invoice(
                full_text,
                invoice_data
            )

            result['processing_steps']['full_validation'] = validation_report

            # Step 7: Save to database
            # Create vlm_result for database storage
            if 'vlm_extraction' not in result['processing_steps'] or not result['processing_steps']['vlm_extraction'].get('success'):
                # Qwen2-VL failed, create minimal vlm_result
                vlm_result = {
                    'structured_data': invoice_data,
                    'raw_response': 'OCR-only extraction used (Qwen2-VL unavailable)'
                }

            invoice = self._save_invoice(
                db,
                invoice_data,
                vlm_result,
                avg_confidence,
                validation_report,
                original_filename
            )

            result['success'] = True
            result['document_type'] = 'invoice'
            result['invoice_id'] = invoice.id
            result['validation'] = validation_report

        except Exception as e:
            result['success'] = False
            result['error'] = str(e)

        return result

    def _save_invoice(
        self,
        db: Session,
        invoice_data: Dict[str, Any],
        vlm_result: Dict[str, Any],
        confidence_score: float,
        validation_report: Dict[str, Any],
        original_filename: str = None
    ) -> Invoice:
        """Save invoice and line items to database"""

        # Create invoice record
        invoice = Invoice(
            provider=invoice_data.get('provider', '')[:255],
            date=invoice_data.get('date', '')[:50],
            invoice_number=invoice_data.get('invoice_number', '')[:100],
            total_without_vat=invoice_data.get('total_ht'),
            total_with_vat=invoice_data.get('total_ttc'),
            confidence_score=confidence_score,
            original_filename=original_filename[:255] if original_filename else None,
            raw_vlm_json=vlm_result.get('structured_data'),
            raw_vlm_response=vlm_result.get('raw_response')
        )

        db.add(invoice)
        db.flush()  # Get invoice ID

        # Create line items
        line_items = invoice_data.get('line_items', [])
        for item_data in line_items:
            line_item = InvoiceLine(
                invoice_id=invoice.id,
                designation=item_data.get('designation', '')[:500],
                quantity=item_data.get('quantity'),
                unit=item_data.get('unit', '')[:50],
                unit_price=item_data.get('unit_price'),
                total_ht=item_data.get('total_ht')
            )
            db.add(line_item)

        db.commit()
        db.refresh(invoice)

        return invoice

    def _save_other_document(
        self,
        db: Session,
        raw_text: str,
        original_filename: str = None
    ) -> OtherDocument:
        """Save non-invoice document to database"""

        # Try to extract provider name from text
        provider = self._extract_provider_from_text(raw_text)

        other_doc = OtherDocument(
            provider=provider[:255] if provider else None,
            original_filename=original_filename[:255] if original_filename else None,
            raw_text=raw_text
        )

        db.add(other_doc)
        db.commit()
        db.refresh(other_doc)

        return other_doc

    def _extract_provider_from_text(self, text: str) -> str:
        """Simple heuristic to extract provider name from text"""
        # Take first few lines as potential provider info
        lines = text.split('\n')[:5]
        for line in lines:
            line = line.strip()
            if len(line) > 3 and len(line) < 100:
                return line
        return ""

    def _extract_from_ocr_only(self, ocr_text: str, ocr_word_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract invoice data using only OCR (fallback when Qwen2-VL fails)

        Args:
            ocr_text: Full OCR text
            ocr_word_data: OCR word-level data

        Returns:
            Structured invoice data
        """
        import re

        # Extract basic fields using regex and text patterns
        invoice_data = {
            'provider': '',
            'invoice_number': '',
            'date': '',
            'total_ht': 0.0,
            'total_ttc': 0.0,
            'vat_amount': 0.0,
            'line_items': [],
            'qwen_response': 'OCR-only extraction (Qwen2-VL unavailable)'
        }

        # Extract provider (usually first line)
        lines = ocr_text.split('\n')
        if lines:
            invoice_data['provider'] = lines[0].strip()[:100]

        # Extract invoice number
        invoice_patterns = [
            r'FACTURE\s*N[°#:]*\s*([A-Z0-9\-/]+)',
            r'INVOICE\s*[#:]*\s*([A-Z0-9\-/]+)',
            r'N[°#]\s*([A-Z0-9\-/]+)'
        ]
        for pattern in invoice_patterns:
            match = re.search(pattern, ocr_text, re.IGNORECASE)
            if match:
                invoice_data['invoice_number'] = match.group(1)
                break

        # Extract date
        date_patterns = [
            r'Date\s*:?\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
        ]
        for pattern in date_patterns:
            match = re.search(pattern, ocr_text, re.IGNORECASE)
            if match:
                invoice_data['date'] = match.group(1)
                break

        # Extract amounts - improved patterns for various formats
        amount_patterns = {
            'total_ht': [
                r'Total\s*HT\s*:?\s*([\d\s,\.]+)\s*€?',
                r'Sous[-\s]total\s*:?\s*([\d\s,\.]+)',
                r'HT\s*:?\s*([\d\s,\.]+)\s*€',
                r'(\d+\s*\d+\s*,\s*\d{2})\s*€?\s*(?:HT|ht)'
            ],
            'total_ttc': [
                r'Total\s*TTC\s*:?\s*([\d\s,\.]+)\s*€?',
                r'Net\s*à\s*payer\s*:?\s*([\d\s,\.]+)',
                r'TTC\s*:?\s*([\d\s,\.]+)\s*€',
                r'Montant\s*total\s*:?\s*([\d\s,\.]+)',
                r'Total\s*général\s*:?\s*([\d\s,\.]+)'
            ],
            'vat_amount': [
                r'TVA\s*:?\s*([\d\s,\.]+)\s*€?',
                r'VAT\s*:?\s*([\d\s,\.]+)',
                r'Taxe\s*:?\s*([\d\s,\.]+)'
            ]
        }

        for field, patterns in amount_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, ocr_text, re.IGNORECASE)
                if match:
                    amount_str = match.group(1).replace(' ', '').replace(',', '.')
                    try:
                        invoice_data[field] = float(amount_str)
                        break
                    except ValueError:
                        pass

        return invoice_data
