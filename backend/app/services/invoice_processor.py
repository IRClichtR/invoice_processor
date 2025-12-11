"""
Invoice Processor - Simple pipeline: PDF -> Image -> Florence-2 -> SQLite
"""

from typing import Dict, Any
from PIL import Image
from sqlalchemy.orm import Session

from app.utils.pdf_converter import PDFConverter
from app.services.model_manager import get_florence_service
from app.models.invoice import Invoice, InvoiceLine, OtherDocument


class InvoiceProcessor:
    """Process invoices: PDF -> Image -> Florence-2 -> SQLite"""

    def __init__(self):
        self.pdf_converter = PDFConverter()
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
            images = self.pdf_converter.pdf_to_images(pdf_path)
            result['page_count'] = len(images)

            # Step 2: Extract data with Florence-2 (use first page)
            florence_result = self.florence_service.extract_invoice_data(images[0])
            invoice_data = florence_result['structured_data']

            # Step 3: Save to database
            if not invoice_data.get('is_invoice', True):
                # Not an invoice - save as other document
                other_doc = self._save_other_document(
                    db,
                    florence_result['raw_response'],
                    original_filename
                )
                result['success'] = True
                result['document_type'] = 'other'
                result['document_id'] = other_doc.id
            else:
                # Invoice - save with line items
                invoice = self._save_invoice(
                    db,
                    invoice_data,
                    florence_result['raw_response'],
                    original_filename
                )
                result['success'] = True
                result['document_type'] = 'invoice'
                result['invoice_id'] = invoice.id
                result['extracted_data'] = invoice_data

        except Exception as e:
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
                unit=item_data.get('unit', '')[:50] if item_data.get('unit') else None,
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
