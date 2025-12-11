"""
Invoice Processor - Pipeline: PDF -> Image -> OCR -> Florence-2 -> SQLite

Dual-modality: Uses Tesseract OCR for text + positions, then Florence-2
for visual understanding with text context.
"""

from typing import Dict, Any
from PIL import Image
from sqlalchemy.orm import Session
import structlog

from app.utils.pdf_converter import PDFConverter
from app.services.ocr_service import OCRService
from app.services.model_manager import get_florence_service
from app.models.invoice import Invoice, InvoiceLine, OtherDocument

logger = structlog.get_logger(__name__)


class InvoiceProcessor:
    """Process invoices: PDF -> Image -> OCR -> Florence-2 -> SQLite"""

    def __init__(self):
        self.pdf_converter = PDFConverter()
        self.ocr_service = OCRService()
        self.florence_service = get_florence_service()

    def process_pdf(
        self,
        pdf_path: str,
        db: Session,
        original_filename: str = None
    ) -> Dict[str, Any]:
        """
        Process a PDF through the pipeline

        Args:
            pdf_path: Path to PDF file
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
            # Step 1: PDF -> Images
            logger.info("Converting PDF to images", pdf_path=pdf_path)
            images = self.pdf_converter.pdf_to_images(pdf_path)
            result['page_count'] = len(images)

            # Step 2: OCR with spatial positions (first page)
            logger.info("Running OCR extraction")
            ocr_result = self.ocr_service.extract_spatial_text(images[0])

            # Step 3: Florence-2 with dual modality (image + OCR context)
            logger.info("Running Florence-2 extraction")
            florence_result = self.florence_service.extract_invoice_data(
                image=images[0],
                ocr_text=ocr_result['full_text'],
                spatial_grid=ocr_result['spatial_grid'],
                words=ocr_result['words']
            )
            invoice_data = florence_result['structured_data']

            # Step 4: Save to database
            if not invoice_data.get('is_invoice', True):
                # Not an invoice - save as other document
                other_doc = self._save_other_document(
                    db,
                    florence_result.get('raw_response', ''),
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
                    florence_result.get('raw_response', ''),
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
