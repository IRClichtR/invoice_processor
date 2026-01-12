"""
Invoice Processor - Pipeline: PDF -> Image -> VLM -> SQLite

Dual pipeline based on document type:
- Printed documents: Tesseract OCR + Florence-2
- Handwritten documents: VisionOCR (skips Tesseract for better accuracy)
"""

from typing import Dict, Any
from PIL import Image
from sqlalchemy.orm import Session
import structlog

from app.utils.pdf_converter import PDFConverter
from app.utils.adaptive_preprocessor import AdaptivePreprocessor
from app.services.ocr_service import OCRService
from app.services.model_manager import get_florence_service, get_visionocr_service
from app.models.invoice import Invoice, InvoiceLine, OtherDocument

logger = structlog.get_logger(__name__)


IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')


class InvoiceProcessor:
    """Process invoices with optimized pipelines for printed vs handwritten documents"""

    def __init__(self):
        self.pdf_converter = PDFConverter()
        self.ocr_service = OCRService()
        self.florence_service = get_florence_service()
        self.visionocr_service = get_visionocr_service()

    def _is_image_file(self, file_path: str) -> bool:
        """Check if file is an image based on extension"""
        return file_path.lower().endswith(IMAGE_EXTENSIONS)

    def process_pdf(
        self,
        pdf_path: str,
        db: Session,
        original_filename: str = None
    ) -> Dict[str, Any]:
        """
        Process a PDF or image through the pipeline

        Args:
            pdf_path: Path to PDF or image file
            db: Database session
            original_filename: Original filename

        Returns:
            Processing result with database ID
        """
        result = {
            'success': False,
            'pdf_path': pdf_path
        }

        try:
            # Step 1: Get image(s) - skip conversion if already an image
            if self._is_image_file(pdf_path):
                logger.info("Loading image file directly", file_path=pdf_path)
                images = [Image.open(pdf_path)]
                result['page_count'] = 1
            else:
                logger.info("Converting PDF to images", pdf_path=pdf_path)
                images = self.pdf_converter.pdf_to_images(pdf_path)
                result['page_count'] = len(images)

            # Step 2: Preprocess image (auto-detect handwritten and enhance)
            logger.info("Preprocessing image for VLM")
            preprocessed_image, preprocess_report = AdaptivePreprocessor.preprocess_for_ocr(
                images[0], mode='auto'
            )
            result['preprocessing'] = preprocess_report
            is_handwritten = preprocess_report.get('is_handwritten', False)
            result['is_handwritten'] = is_handwritten

            logger.info(
                "Preprocessing completed",
                is_handwritten=is_handwritten,
                operations=preprocess_report.get('operations', [])
            )

            # Step 3: Extract invoice data using appropriate pipeline
            if is_handwritten:
                # Handwritten pipeline: VisionOCR (skip Tesseract OCR)
                logger.info("Using VisionOCR pipeline for handwritten document")
                vlm_result = self.visionocr_service.extract_invoice_data(
                    image=preprocessed_image
                )
                invoice_data = vlm_result['structured_data']
                result['pipeline'] = 'visionocr'
            else:
                # Printed pipeline: Tesseract OCR + Florence-2
                logger.info("Using Florence-2 pipeline for printed document")

                # OCR with spatial positions
                logger.info("Running Tesseract OCR extraction")
                ocr_result = self.ocr_service.extract_spatial_text(preprocessed_image)
                logger.info("OCR extraction completed", text_length=len(ocr_result['full_text']))

                # Florence-2 with dual modality
                logger.info("Running Florence-2 extraction")
                vlm_result = self.florence_service.extract_invoice_data(
                    image=preprocessed_image,
                    ocr_text=ocr_result['full_text'],
                    spatial_grid=ocr_result['spatial_grid'],
                    words=ocr_result['words']
                )
                invoice_data = vlm_result['structured_data']
                result['pipeline'] = 'florence'

            # Step 4: Save to database
            if not invoice_data.get('is_invoice', True):
                # Not an invoice - save as other document
                other_doc = self._save_other_document(
                    db,
                    vlm_result.get('raw_response', ''),
                    original_filename
                )
                result['success'] = True
                result['document_type'] = 'other'
                result['document_id'] = other_doc.id
                logger.info("Saved as other document", document_id=other_doc.id)
            else:
                # Invoice - save with line items
                invoice = self._save_invoice(
                    db,
                    invoice_data,
                    vlm_result.get('raw_response', ''),
                    original_filename
                )
                result['success'] = True
                result['document_type'] = 'invoice'
                result['invoice_id'] = invoice.id
                result['extracted_data'] = invoice_data
                logger.info("Saved invoice", invoice_id=invoice.id, provider=invoice_data.get('provider'))

        except Exception as e:
            logger.error("Processing failed", error=str(e))
            result['success'] = False
            result['error'] = str(e)

        return result

    def _save_invoice(
        self,
        db: Session,
        invoice_data: Dict[str, Any],
        raw_response: str,
        original_filename: str = None
    ) -> Invoice:
        """Save invoice and line items to database"""
        invoice = Invoice(
            provider=invoice_data.get('provider', '')[:255],
            date=invoice_data.get('date', '')[:50],
            invoice_number=invoice_data.get('invoice_number', '')[:100],
            total_without_vat=invoice_data.get('total_ht'),
            total_with_vat=invoice_data.get('total_ttc'),
            currency=invoice_data.get('currency', 'EUR'),
            original_filename=original_filename[:255] if original_filename else None,
            raw_vlm_json=invoice_data,
            raw_vlm_response=raw_response
        )

        db.add(invoice)
        db.flush()

        for item_data in invoice_data.get('line_items', []):
            line_item = InvoiceLine(
                invoice_id=invoice.id,
                designation=item_data.get('designation', '')[:500],
                quantity=item_data.get('quantity'),
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
        other_doc = OtherDocument(
            original_filename=original_filename[:255] if original_filename else None,
            raw_text=raw_text
        )

        db.add(other_doc)
        db.commit()
        db.refresh(other_doc)
        return other_doc
