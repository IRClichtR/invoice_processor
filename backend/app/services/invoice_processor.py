"""
Invoice Processor - Multi-step Pipeline with Quality Analysis

Pipeline:
1. PDF/Image -> OCR -> Quality Analysis
2. If quality OK: Florence-2 -> SQLite
3. If low quality: Propose Claude Vision -> User decision -> Process -> SQLite

Supports handwritten and low-quality document processing via Claude Vision.
"""

from typing import Dict, Any, Optional, Tuple
from PIL import Image
from sqlalchemy.orm import Session
import structlog
import os
import uuid

from app.utils.pdf_converter import PDFConverter
from app.services.ocr_service import OCRService
from app.services.model_manager import get_florence_service
from app.services.image_analyzer import ImageAnalyzer, DocumentQuality
from app.services.claude_vision_service import (
    ClaudeVisionService,
    ClaudeVisionError,
    APIKeyNotConfiguredError,
    APIKeyInvalidError,
    CLAUDE_API_CONSOLE_URL
)
from app.models.invoice import Invoice, InvoiceLine, OtherDocument
from app.core.config import settings

logger = structlog.get_logger(__name__)


# In-memory store for pending analyses (in production, use Redis or DB)
_pending_analyses: Dict[str, Dict[str, Any]] = {}


class InvoiceProcessor:
    """
    Process invoices with multi-step quality-aware pipeline.

    Workflow:
    1. analyze_file() - Initial analysis with quality assessment
    2. If low quality, user decides whether to use Claude Vision
    3. process_with_decision() - Complete processing based on user choice
    """

    # Supported image extensions
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}

    def __init__(self):
        self.pdf_converter = PDFConverter()
        self.ocr_service = OCRService()
        self.florence_service = get_florence_service()
        self.image_analyzer = ImageAnalyzer()
        self._claude_service = None

    @property
    def claude_service(self) -> ClaudeVisionService:
        """Lazy initialization of Claude Vision service"""
        if self._claude_service is None:
            self._claude_service = ClaudeVisionService()
        return self._claude_service

    @classmethod
    def is_image_file(cls, filename: str) -> bool:
        """Check if filename has an image extension"""
        import os
        ext = os.path.splitext(filename.lower())[1]
        return ext in cls.IMAGE_EXTENSIONS

    @classmethod
    def is_pdf_file(cls, filename: str) -> bool:
        """Check if filename has a PDF extension"""
        return filename.lower().endswith('.pdf')

    # =========================================================================
    # MULTI-STEP WORKFLOW METHODS
    # =========================================================================

    def analyze_file(
        self,
        file_path: str,
        original_filename: str = None
    ) -> Dict[str, Any]:
        """
        Step 1: Analyze file quality without saving to database.

        Returns analysis results including quality assessment and
        recommendation for processing path.

        Args:
            file_path: Path to file
            original_filename: Original filename

        Returns:
            {
                'analysis_id': str,  # Use this ID to continue processing
                'file_path': str,
                'original_filename': str,
                'quality': {
                    'quality': str,  # 'good', 'low_quality', 'handwritten', 'extremely_low_quality'
                    'ocr_confidence': float,
                    'is_low_quality': bool,
                    'is_handwritten': bool,
                    'requires_claude_vision': bool,
                    'recommendation': str
                },
                'ocr_preview': str,  # First 500 chars of OCR text
                'claude_vision_available': bool,
                'claude_api_key_configured': bool,
                'claude_console_url': str
            }
        """
        logger.info("Starting file analysis", file_path=file_path)

        # Load image
        image, page_count = self._load_image_from_file(file_path)

        # Run OCR
        ocr_result = self.ocr_service.extract_spatial_text(image)

        # Analyze quality
        quality_analysis = self.image_analyzer.analyze(image, ocr_result)

        # Check Claude API availability
        claude_available = settings.has_valid_claude_api_key()

        # Generate unique analysis ID
        analysis_id = str(uuid.uuid4())

        # Store analysis for later processing
        _pending_analyses[analysis_id] = {
            'file_path': file_path,
            'original_filename': original_filename,
            'image': image,
            'ocr_result': ocr_result,
            'quality_analysis': quality_analysis,
            'page_count': page_count
        }

        result = {
            'analysis_id': analysis_id,
            'file_path': file_path,
            'original_filename': original_filename,
            'page_count': page_count,
            'quality': quality_analysis,
            'ocr_preview': ocr_result['full_text'][:500] if ocr_result['full_text'] else '',
            'claude_vision_available': claude_available,
            'claude_api_key_configured': bool(settings.ANTHROPIC_API_KEY),
            'claude_console_url': CLAUDE_API_CONSOLE_URL
        }

        logger.info(
            "File analysis complete",
            analysis_id=analysis_id,
            quality=quality_analysis['quality'],
            requires_claude=quality_analysis['requires_claude_vision']
        )

        return result

    def process_with_decision(
        self,
        analysis_id: str,
        use_claude_vision: bool,
        db: Session,
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Step 2: Process file based on user's decision.

        Args:
            analysis_id: ID from analyze_file()
            use_claude_vision: Whether to use Claude Vision for processing
            db: Database session
            api_key: Optional API key provided by user (if not configured)

        Returns:
            Processing result with database ID
        """
        # Retrieve pending analysis
        if analysis_id not in _pending_analyses:
            return {
                'success': False,
                'error': 'Analysis not found or expired. Please re-upload the file.'
            }

        analysis = _pending_analyses[analysis_id]

        try:
            if use_claude_vision:
                result = self._process_with_claude(analysis, db, api_key)
            else:
                result = self._process_with_florence(analysis, db)

            return result

        finally:
            # Clean up stored analysis
            if analysis_id in _pending_analyses:
                del _pending_analyses[analysis_id]

    def check_claude_api_status(self) -> Dict[str, Any]:
        """
        Check Claude API key status.

        Returns:
            {
                'configured': bool,
                'valid': bool,
                'error': str or None,
                'console_url': str
            }
        """
        return self.claude_service.check_api_key_status()

    def set_api_key_temporarily(self, api_key: str) -> bool:
        """
        Temporarily set API key for this session.

        Note: This does NOT persist the key. For security, keys should be
        set via environment variables.

        Returns:
            True if key appears valid, False otherwise
        """
        if api_key and api_key.startswith('sk-ant-') and len(api_key) > 20:
            settings.ANTHROPIC_API_KEY = api_key
            self._claude_service = None  # Reset to pick up new key
            return True
        return False

    def _load_image_from_file(self, file_path: str) -> Tuple[Image.Image, int]:
        """Load image from PDF or image file"""
        if self.is_pdf_file(file_path):
            images = self.pdf_converter.pdf_to_images(file_path)
            return images[0], len(images)
        else:
            image = Image.open(file_path)
            if image.mode != 'RGB':
                image = image.convert('RGB')
            return image, 1

    def _process_with_claude(
        self,
        analysis: Dict[str, Any],
        db: Session,
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process using Claude Vision"""
        result = {
            'success': False,
            'file_path': analysis['file_path'],
            'processing_method': 'claude_vision'
        }

        # Set temporary API key if provided
        if api_key:
            if not self.set_api_key_temporarily(api_key):
                return {
                    **result,
                    'error': 'Invalid API key format',
                    'requires_api_key': True,
                    'console_url': CLAUDE_API_CONSOLE_URL
                }

        try:
            logger.info("Processing with Claude Vision")

            # Get OCR context for Claude
            ocr_context = analysis['ocr_result'].get('full_text', '')

            # Call Claude Vision
            claude_result = self.claude_service.extract_invoice_data(
                image=analysis['image'],
                ocr_context=ocr_context
            )

            invoice_data = claude_result['structured_data']
            result['page_count'] = analysis['page_count']

            # Save to database
            result = self._save_to_database(
                db,
                invoice_data,
                claude_result,
                analysis['original_filename'],
                result
            )
            result['model_used'] = claude_result.get('model_used', 'claude')

        except APIKeyNotConfiguredError as e:
            result['error'] = str(e)
            result['requires_api_key'] = True
            result['console_url'] = CLAUDE_API_CONSOLE_URL

        except APIKeyInvalidError as e:
            result['error'] = str(e)
            result['requires_api_key'] = True
            result['console_url'] = CLAUDE_API_CONSOLE_URL

        except ClaudeVisionError as e:
            result['error'] = f"Claude Vision error: {str(e)}"

        except Exception as e:
            logger.error("Claude Vision processing failed", error=str(e))
            result['error'] = str(e)

        return result

    def _process_with_florence(
        self,
        analysis: Dict[str, Any],
        db: Session
    ) -> Dict[str, Any]:
        """Process using Florence-2 (standard processing)"""
        result = {
            'success': False,
            'file_path': analysis['file_path'],
            'processing_method': 'florence'
        }

        try:
            logger.info("Processing with Florence-2")

            ocr_result = analysis['ocr_result']

            florence_result = self.florence_service.extract_invoice_data(
                image=analysis['image'],
                ocr_text=ocr_result['full_text'],
                spatial_grid=ocr_result['spatial_grid'],
                words=ocr_result['words']
            )

            invoice_data = florence_result['structured_data']
            result['page_count'] = analysis['page_count']

            # Save to database
            result = self._save_to_database(
                db,
                invoice_data,
                florence_result,
                analysis['original_filename'],
                result
            )

        except Exception as e:
            logger.error("Florence-2 processing failed", error=str(e))
            result['error'] = str(e)

        return result

    # =========================================================================
    # LEGACY DIRECT PROCESSING METHODS (for backward compatibility)
    # =========================================================================

    def process_file(
        self,
        file_path: str,
        db: Session,
        original_filename: str = None
    ) -> Dict[str, Any]:
        """
        Process a file (PDF or image) through the pipeline.
        Automatically detects file type and routes to appropriate processor.

        Args:
            file_path: Path to file
            db: Database session
            original_filename: Original filename

        Returns:
            Processing result with database ID
        """
        if self.is_image_file(file_path):
            return self.process_image(file_path, db, original_filename)
        else:
            return self.process_pdf(file_path, db, original_filename)

    def process_image(
        self,
        image_path: str,
        db: Session,
        original_filename: str = None
    ) -> Dict[str, Any]:
        """
        Process an image file directly (skip PDF conversion).
        Automatically uses Claude Vision for low-quality documents if API key is available.

        Args:
            image_path: Path to image file
            db: Database session
            original_filename: Original filename

        Returns:
            Processing result with database ID
        """
        result = {
            'success': False,
            'image_path': image_path
        }

        try:
            # Step 1: Load image directly
            logger.info("Loading image file", image_path=image_path)
            image = Image.open(image_path)
            if image.mode != 'RGB':
                image = image.convert('RGB')
            result['page_count'] = 1

            # Step 2: OCR with spatial positions
            logger.info("Running OCR extraction")
            ocr_result = self.ocr_service.extract_spatial_text(image)

            # Step 3: Check quality and choose processing method
            confidence = ocr_result.get('confidence', {})
            is_low_quality = confidence.get('is_low_quality', False)

            if is_low_quality and settings.has_valid_claude_api_key():
                # Use Claude Vision for low-quality documents
                logger.info("Low quality detected, using Claude Vision",
                           ocr_confidence=confidence.get('average'))
                result['processing_method'] = 'claude_vision'

                try:
                    claude_result = self.claude_service.extract_invoice_data(
                        image=image,
                        ocr_context=ocr_result['full_text']
                    )
                    invoice_data = claude_result['structured_data']
                    result['model_used'] = claude_result.get('model_used', 'claude')
                    result = self._save_to_database(db, invoice_data, claude_result, original_filename, result)
                except (APIKeyNotConfiguredError, APIKeyInvalidError) as e:
                    # Fall back to Florence-2 if Claude fails
                    logger.warning("Claude Vision failed, falling back to Florence-2", error=str(e))
                    result = self._process_with_florence_direct(image, ocr_result, db, original_filename, result)
            else:
                # Use Florence-2 for good quality documents or when Claude not available
                if is_low_quality:
                    logger.warning("Low quality detected but Claude API key not configured, using Florence-2")
                result = self._process_with_florence_direct(image, ocr_result, db, original_filename, result)

        except Exception as e:
            logger.error("Processing failed", error=str(e))
            result['success'] = False
            result['error'] = str(e)

        return result

    def process_pdf(
        self,
        pdf_path: str,
        db: Session,
        original_filename: str = None
    ) -> Dict[str, Any]:
        """
        Process a PDF through the pipeline.
        Automatically uses Claude Vision for low-quality documents if API key is available.

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

            # Step 3: Check quality and choose processing method
            confidence = ocr_result.get('confidence', {})
            is_low_quality = confidence.get('is_low_quality', False)

            if is_low_quality and settings.has_valid_claude_api_key():
                # Use Claude Vision for low-quality documents
                logger.info("Low quality detected, using Claude Vision",
                           ocr_confidence=confidence.get('average'))
                result['processing_method'] = 'claude_vision'

                try:
                    claude_result = self.claude_service.extract_invoice_data(
                        image=images[0],
                        ocr_context=ocr_result['full_text']
                    )
                    invoice_data = claude_result['structured_data']
                    result['model_used'] = claude_result.get('model_used', 'claude')
                    result = self._save_to_database(db, invoice_data, claude_result, original_filename, result)
                except (APIKeyNotConfiguredError, APIKeyInvalidError) as e:
                    # Fall back to Florence-2 if Claude fails
                    logger.warning("Claude Vision failed, falling back to Florence-2", error=str(e))
                    result = self._process_with_florence_direct(images[0], ocr_result, db, original_filename, result)
            else:
                # Use Florence-2 for good quality documents or when Claude not available
                if is_low_quality:
                    logger.warning("Low quality detected but Claude API key not configured, using Florence-2")
                result = self._process_with_florence_direct(images[0], ocr_result, db, original_filename, result)

        except Exception as e:
            logger.error("Processing failed", error=str(e))
            result['success'] = False
            result['error'] = str(e)

        return result

    def _process_with_florence_direct(
        self,
        image: Image.Image,
        ocr_result: Dict[str, Any],
        db: Session,
        original_filename: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Helper method to process with Florence-2"""
        logger.info("Running Florence-2 extraction")
        result['processing_method'] = 'florence'

        florence_result = self.florence_service.extract_invoice_data(
            image=image,
            ocr_text=ocr_result['full_text'],
            spatial_grid=ocr_result['spatial_grid'],
            words=ocr_result['words']
        )
        invoice_data = florence_result['structured_data']

        return self._save_to_database(db, invoice_data, florence_result, original_filename, result)

    def _save_to_database(
        self,
        db: Session,
        invoice_data: Dict[str, Any],
        florence_result: Dict[str, Any],
        original_filename: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Save extracted data to database"""
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

        return result

    def _save_invoice(
        self,
        db: Session,
        invoice_data: Dict[str, Any],
        raw_response: str,
        original_filename: str = None
    ) -> Invoice:
        """Save invoice and line items to database"""
        # Get currency, default to 'XXX' (unidentified per ISO 4217)
        currency = invoice_data.get('currency', 'XXX')[:3].upper()
        if not currency or len(currency) != 3:
            currency = 'XXX'

        invoice = Invoice(
            provider=invoice_data.get('provider', '')[:255],
            date=invoice_data.get('date', '')[:50],
            invoice_number=invoice_data.get('invoice_number', '')[:100],
            total_without_vat=invoice_data.get('total_ht'),
            total_with_vat=invoice_data.get('total_ttc'),
            currency=currency,
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
