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
Processing Service - Document processing for two-step workflow.

Step 2: Process document with chosen pipeline (Florence or Claude).
Uses job data from AnalysisService (Step 1).

Handles:
- Job retrieval and validation
- Pipeline execution (Florence-2 or Claude Vision)
- Invoice data extraction
- Database saving
- Cleanup of temp files
"""

from typing import Dict, Any, Optional
from PIL import Image
from sqlalchemy.orm import Session
import structlog

from app.core.config import settings
from app.models.analysis_job import AnalysisJob
from app.models.invoice import Invoice, InvoiceLine, OtherDocument
from app.services.analysis_service import AnalysisService
from app.services.cleanup_service import CleanupService
from app.services.api_key_service import ApiKeyService
from app.services.document_storage_service import document_storage_service
from app.services.model_manager import get_florence_service
from app.services.claude_vision_service import (
    ClaudeVisionService,
    ClaudeVisionError,
    APIKeyNotConfiguredError,
    APIKeyInvalidError,
    CLAUDE_API_CONSOLE_URL
)

logger = structlog.get_logger(__name__)


class ProcessingService:
    """
    Service for document processing (Step 2 of two-step workflow).

    Workflow:
    1. Retrieve job from database
    2. Verify job is not expired
    3. Load preprocessed images
    4. Execute chosen pipeline (Florence or Claude)
    5. Optionally save invoice to database
    6. Clean up temp files
    7. Update job status
    """

    def __init__(self):
        self.analysis_service = AnalysisService()
        self.cleanup_service = CleanupService()
        self.api_key_service = ApiKeyService()
        self.florence_service = get_florence_service()
        self._claude_service = None

    @property
    def claude_service(self) -> ClaudeVisionService:
        """Lazy initialization of Claude Vision service"""
        if self._claude_service is None:
            self._claude_service = ClaudeVisionService()
        return self._claude_service

    def process_job(
        self,
        job_id: str,
        pipeline: str,
        save_to_db: bool,
        db: Session,
        user_preference: str = 'auto'
    ) -> Dict[str, Any]:
        """
        Process a job with the chosen pipeline.

        Args:
            job_id: Job UUID from analysis step
            pipeline: Processing pipeline ('florence' or 'claude')
            save_to_db: Whether to save the result to database
            db: Database session
            user_preference: User's processing preference ('local', 'cloud', or 'auto')

        Returns:
            {
                'success': bool,
                'invoice_id': int or None,
                'document_id': int or None,
                'extracted_data': dict or None,
                'processing_method': str,
                'error': str or None,
                'requires_api_key': bool,
                'console_url': str or None,
                'requires_confirmation': bool,
                'warning': str or None,
                'suggested_pipeline': str or None
            }
        """
        result = {
            'success': False,
            'invoice_id': None,
            'document_id': None,
            'extracted_data': None,
            'processing_method': pipeline,
            'error': None,
            'requires_api_key': False,
            'console_url': None,
            'requires_confirmation': False,
            'warning': None,
            'suggested_pipeline': None
        }

        # Get and validate job
        job, error = self.analysis_service.get_job_for_processing(job_id, db)
        if error:
            result['error'] = error
            return result

        # Check user preference vs suggested pipeline
        # If user wants local only but the suggested pipeline is claude (low quality doc),
        # return a confirmation request
        if user_preference == 'local' and pipeline == 'claude':
            logger.info(
                "User preference is local but claude pipeline requested",
                job_id=job_id,
                confidence=job.confidence_score
            )
            result['requires_confirmation'] = True
            result['warning'] = 'low_quality_local'
            result['suggested_pipeline'] = 'claude'
            result['error'] = (
                'Document quality is low. Local processing may produce poor results. '
                'Consider using Cloud AI for better accuracy.'
            )
            return result

        # Mark job as processing
        job.mark_processing()
        db.commit()

        try:
            # Load images
            images, load_error = self.analysis_service.get_job_images(job_id)
            if load_error:
                job.mark_failed(load_error)
                db.commit()
                result['error'] = load_error
                return result

            # Execute pipeline
            if pipeline == 'claude':
                extraction_result = self._process_with_claude(job, images, db)
            else:
                extraction_result = self._process_with_florence(job, images)

            # Check for pipeline errors
            if extraction_result.get('error'):
                if extraction_result.get('requires_api_key'):
                    # Don't mark as failed - allow retry with API key
                    job.status = "analyzed"
                    db.commit()
                    result['error'] = extraction_result['error']
                    result['requires_api_key'] = True
                    result['console_url'] = extraction_result.get('console_url', CLAUDE_API_CONSOLE_URL)
                    return result
                else:
                    job.mark_failed(extraction_result['error'])
                    db.commit()
                    result['error'] = extraction_result['error']
                    return result

            invoice_data = extraction_result['structured_data']
            result['extracted_data'] = invoice_data
            result['processing_method'] = extraction_result.get('method', pipeline)

            # Save to database if requested
            if save_to_db:
                save_result = self._save_to_database(
                    db,
                    invoice_data,
                    extraction_result.get('raw_response', ''),
                    job.original_filename,
                    job_id=job.id,
                    file_extension=job.file_extension
                )
                result['invoice_id'] = save_result.get('invoice_id')
                result['document_id'] = save_result.get('document_id')

                # Mark job as completed
                job.mark_completed(
                    invoice_id=save_result.get('invoice_id'),
                    document_id=save_result.get('document_id'),
                    method=result['processing_method']
                )
            else:
                # Mark completed without DB save
                job.mark_completed(method=result['processing_method'])

            db.commit()
            result['success'] = True

            # Note: Don't clean up temp files here - they're needed for review page preview
            # Files will be cleaned up when user confirms review or when job expires

            logger.info(
                "Job processing complete",
                job_id=job_id,
                method=result['processing_method'],
                invoice_id=result.get('invoice_id')
            )

            return result

        except Exception as e:
            logger.error("Processing failed", job_id=job_id, error=str(e))
            job.mark_failed(str(e))
            db.commit()
            result['error'] = str(e)
            return result

    def _process_with_florence(
        self,
        job: AnalysisJob,
        images: list
    ) -> Dict[str, Any]:
        """
        Process with Florence-2 pipeline.

        Args:
            job: AnalysisJob with OCR data
            images: List of page images

        Returns:
            Extraction result dict
        """
        logger.info("Processing with Florence-2", job_id=job.id)

        try:
            # Use stored OCR data from analysis
            florence_result = self.florence_service.extract_invoice_data(
                image=images[0],
                ocr_text=job.ocr_full_text or '',
                spatial_grid=job.ocr_spatial_grid or '',
                words=job.ocr_words_json or []
            )

            return {
                'structured_data': florence_result.get('structured_data', {}),
                'raw_response': florence_result.get('raw_response', ''),
                'method': 'florence'
            }

        except Exception as e:
            logger.error("Florence processing failed", error=str(e))
            return {
                'error': f"Florence processing failed: {str(e)}",
                'structured_data': None
            }

    def _process_with_claude(
        self,
        job: AnalysisJob,
        images: list,
        db: Session
    ) -> Dict[str, Any]:
        """
        Process with Claude Vision pipeline.

        Args:
            job: AnalysisJob with OCR data
            images: List of page images
            db: Database session for API key lookup

        Returns:
            Extraction result dict
        """
        logger.info("Processing with Claude Vision", job_id=job.id)

        # Check for API key
        api_key = self.api_key_service.get_anthropic_key_for_processing(db)

        if not api_key:
            logger.warning("Claude Vision requested but no API key available")
            return {
                'error': 'Anthropic API key required. Please configure an API key.',
                'requires_api_key': True,
                'console_url': CLAUDE_API_CONSOLE_URL,
                'structured_data': None
            }

        try:
            # Call Claude service with database session (API key read from DB)
            claude_result = self.claude_service.extract_invoice_data(
                image=images[0],
                db=db,
                ocr_context=job.ocr_full_text or ''
            )

            return {
                'structured_data': claude_result.get('structured_data', {}),
                'raw_response': claude_result.get('raw_response', ''),
                'method': 'claude',
                'model_used': claude_result.get('model_used', 'claude')
            }

        except APIKeyNotConfiguredError:
            return {
                'error': 'Anthropic API key not configured.',
                'requires_api_key': True,
                'console_url': CLAUDE_API_CONSOLE_URL,
                'structured_data': None
            }

        except APIKeyInvalidError as e:
            # Mark key as invalid in database
            from app.models.api_key import ApiKey
            api_key_record = db.query(ApiKey).filter(ApiKey.provider == 'anthropic').first()
            if api_key_record:
                api_key_record.update_validation(False, str(e))
                db.commit()

            return {
                'error': f'Anthropic API key is invalid: {str(e)}',
                'requires_api_key': True,
                'console_url': CLAUDE_API_CONSOLE_URL,
                'structured_data': None
            }

        except ClaudeVisionError as e:
            logger.error("Claude Vision error", error=str(e))
            return {
                'error': f"Claude Vision error: {str(e)}",
                'structured_data': None
            }

        except Exception as e:
            logger.error("Claude processing failed", error=str(e))
            return {
                'error': f"Claude processing failed: {str(e)}",
                'structured_data': None
            }

    def _save_to_database(
        self,
        db: Session,
        invoice_data: Dict[str, Any],
        raw_response: str,
        original_filename: str,
        job_id: str = None,
        file_extension: str = None
    ) -> Dict[str, Any]:
        """
        Save extracted data to database.

        Args:
            db: Database session
            invoice_data: Extracted invoice data
            raw_response: Raw VLM response
            original_filename: Original filename
            job_id: Job ID for retrieving original document
            file_extension: File extension of original document

        Returns:
            {'invoice_id': int} or {'document_id': int}
        """
        if not invoice_data.get('is_invoice', True):
            # Not an invoice - save as other document
            other_doc = OtherDocument(
                original_filename=original_filename[:255] if original_filename else None,
                raw_text=raw_response
            )
            db.add(other_doc)
            db.commit()
            db.refresh(other_doc)

            logger.info("Saved as other document", document_id=other_doc.id)
            return {'document_id': other_doc.id}

        # Invoice - save with line items
        currency = (invoice_data.get('currency') or 'XXX')[:3].upper()
        if not currency or len(currency) != 3:
            currency = 'XXX'

        invoice = Invoice(
            provider=(invoice_data.get('provider') or '')[:255],
            date=(invoice_data.get('date') or '')[:50],
            invoice_number=(invoice_data.get('invoice_number') or '')[:100],
            total_without_vat=invoice_data.get('total_ht'),
            total_with_vat=invoice_data.get('total_ttc'),
            currency=currency,
            original_filename=original_filename[:255] if original_filename else None,
            raw_vlm_json=invoice_data,
            raw_vlm_response=raw_response
        )

        db.add(invoice)
        db.flush()

        # Store original document permanently
        if job_id and file_extension and original_filename:
            # Strip leading dot from extension (e.g., '.pdf' -> 'pdf')
            ext = file_extension.lstrip('.')
            source_path = self.cleanup_service.get_job_file_path(
                job_id, 'original', extension=ext
            )
            stored_filename = document_storage_service.store_document(
                source_path=source_path,
                invoice_id=invoice.id,
                original_filename=original_filename
            )
            if stored_filename:
                invoice.document_path = stored_filename
                logger.info(
                    "Document stored permanently",
                    invoice_id=invoice.id,
                    document_path=stored_filename
                )

        # Add line items
        for item_data in invoice_data.get('line_items', []):
            line_item = InvoiceLine(
                invoice_id=invoice.id,
                designation=(item_data.get('designation') or '')[:500],
                quantity=item_data.get('quantity'),
                unit_price=item_data.get('unit_price'),
                total_ht=item_data.get('total_ht')
            )
            db.add(line_item)

        db.commit()
        db.refresh(invoice)

        logger.info("Saved invoice", invoice_id=invoice.id, provider=invoice_data.get('provider'))
        return {'invoice_id': invoice.id}

    def get_job_status(self, job_id: str, db: Session) -> Dict[str, Any]:
        """
        Get the status of a processing job.

        Args:
            job_id: Job UUID
            db: Database session

        Returns:
            Job status information
        """
        job = self.analysis_service.get_job(job_id, db)

        if not job:
            return {
                'found': False,
                'error': 'Job not found'
            }

        return {
            'found': True,
            'job_id': job.id,
            'status': job.status,
            'is_expired': job.is_expired,
            'can_be_processed': job.can_be_processed,
            'result_invoice_id': job.result_invoice_id,
            'result_document_id': job.result_document_id,
            'processing_method': job.processing_method,
            'processing_error': job.processing_error,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'expires_at': job.expires_at.isoformat() if job.expires_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None
        }
