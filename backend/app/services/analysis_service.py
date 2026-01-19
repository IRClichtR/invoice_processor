"""
Analysis Service - Document analysis for two-step processing workflow.

Step 1: Analyze document quality and OCR confidence.
Returns job_id for use with ProcessingService (Step 2).

Handles:
- PDF/Image loading
- Preprocessing and storage
- OCR extraction
- Quality analysis
- Confidence score calculation
- Job persistence to database
"""

import os
import uuid
import shutil
import statistics
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from PIL import Image
from sqlalchemy.orm import Session
import structlog

from app.core.config import settings
from app.models.analysis_job import AnalysisJob
from app.services.ocr_service import OCRService
from app.services.image_analyzer import ImageAnalyzer
from app.services.cleanup_service import CleanupService
from app.services.api_key_service import ApiKeyService
from app.utils.pdf_converter import PDFConverter

logger = structlog.get_logger(__name__)


class AnalysisService:
    """
    Service for document analysis (Step 1 of two-step workflow).

    Workflow:
    1. Generate job_id (UUID)
    2. Save original file to temp directory
    3. Convert PDF to images (if PDF)
    4. Save all page images
    5. Run OCR on all pages
    6. Calculate confidence score
    7. Determine suggested pipeline
    8. Save AnalysisJob to database
    """

    # Supported file extensions
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}

    def __init__(self):
        self.ocr_service = OCRService()
        self.image_analyzer = ImageAnalyzer()
        self.pdf_converter = PDFConverter()
        self.cleanup_service = CleanupService()
        self.api_key_service = ApiKeyService()

    def is_image_file(self, filename: str) -> bool:
        """Check if filename has an image extension"""
        ext = os.path.splitext(filename.lower())[1]
        return ext in self.IMAGE_EXTENSIONS

    def is_pdf_file(self, filename: str) -> bool:
        """Check if filename has a PDF extension"""
        return filename.lower().endswith('.pdf')

    def analyze_document(
        self,
        file_path: str,
        original_filename: str,
        db: Session
    ) -> AnalysisJob:
        """
        Analyze a document and create an AnalysisJob.

        Args:
            file_path: Path to the uploaded file
            original_filename: Original filename from upload
            db: Database session

        Returns:
            AnalysisJob with analysis results
        """
        # Ensure temp directory exists
        self.cleanup_service.ensure_temp_dir()

        # Generate job ID
        job_id = str(uuid.uuid4())
        logger.info("Starting document analysis", job_id=job_id, filename=original_filename)

        # Get file extension
        file_extension = os.path.splitext(original_filename)[1].lower()

        try:
            # Copy original file to temp directory
            original_path = self.cleanup_service.get_job_file_path(
                job_id, 'original', extension=file_extension.lstrip('.')
            )
            shutil.copy2(file_path, original_path)

            # Load and save page images
            images, page_count = self._load_and_save_images(job_id, file_path, original_filename)

            # Run OCR on first page (primary for confidence calculation)
            ocr_result = self.ocr_service.extract_spatial_text(images[0])

            # Run quality analysis
            quality_analysis = self.image_analyzer.analyze(images[0], ocr_result)

            # Calculate confidence score and suggested pipeline
            confidence_score, suggested_pipeline = self._calculate_confidence_score(
                ocr_result,
                quality_analysis
            )

            # Create analysis job
            job = AnalysisJob(
                id=job_id,
                status="analyzed",
                original_filename=original_filename,
                file_extension=file_extension,
                page_count=page_count,
                confidence_score=confidence_score,
                is_handwritten=quality_analysis.get('is_handwritten', False),
                is_low_quality=quality_analysis.get('is_low_quality', False),
                suggested_pipeline=suggested_pipeline,
                quality_classification=quality_analysis.get('quality', 'unknown'),
                ocr_full_text=ocr_result.get('full_text', ''),
                ocr_words_json=ocr_result.get('words', []),
                ocr_spatial_grid=ocr_result.get('spatial_grid', ''),
                quality_details=quality_analysis.get('details', {}),
                preprocessing_report=None  # Can be extended for preprocessing stats
            )

            # Set expiration
            job.set_expiration(settings.JOB_EXPIRATION_SECONDS)

            # Save to database
            db.add(job)
            db.commit()
            db.refresh(job)

            logger.info(
                "Document analysis complete",
                job_id=job_id,
                confidence=confidence_score,
                suggested_pipeline=suggested_pipeline,
                page_count=page_count
            )

            return job

        except Exception as e:
            # Clean up on error
            logger.error("Analysis failed, cleaning up", job_id=job_id, error=str(e))
            self.cleanup_service.cleanup_job_files(job_id)
            raise

    def _load_and_save_images(
        self,
        job_id: str,
        file_path: str,
        original_filename: str
    ) -> Tuple[List[Image.Image], int]:
        """
        Load images from file and save to temp directory.

        Args:
            job_id: Job UUID
            file_path: Path to uploaded file
            original_filename: Original filename

        Returns:
            Tuple of (list of PIL Images, page count)
        """
        if self.is_pdf_file(original_filename):
            # Convert PDF to images
            images = self.pdf_converter.pdf_to_images(file_path)
            page_count = len(images)
        else:
            # Load single image
            image = Image.open(file_path)
            if image.mode != 'RGB':
                image = image.convert('RGB')
            images = [image]
            page_count = 1

        # Save all page images
        for i, img in enumerate(images):
            page_path = self.cleanup_service.get_job_file_path(job_id, 'page', page=i)
            img.save(page_path, 'PNG')
            logger.debug("Saved page image", job_id=job_id, page=i, path=page_path)

        # Save preprocessed version of first page (main page)
        preprocessed_path = self.cleanup_service.get_job_file_path(job_id, 'preprocessed')
        images[0].save(preprocessed_path, 'PNG')

        return images, page_count

    def _calculate_confidence_score(
        self,
        ocr_data: Dict[str, Any],
        quality_analysis: Dict[str, Any]
    ) -> Tuple[float, str]:
        """
        Calculate normalized confidence score and suggest pipeline.

        Args:
            ocr_data: OCR result from OCRService
            quality_analysis: Quality analysis from ImageAnalyzer

        Returns:
            Tuple of (score 0-1, suggested_pipeline)

        Scoring criteria:
        - Base: Average Tesseract OCR confidence (normalized to 0-1)
        - Penalty for high confidence variance (mixed quality)
        - Penalty for handwritten detection
        - Penalty for blur/low contrast
        """
        confidences = [w.get('conf', 0) for w in ocr_data.get('words', []) if w.get('conf', 0) > 0]

        if not confidences:
            logger.warning("No words with confidence found")
            return 0.0, "claude"

        # Base score: average OCR confidence normalized to 0-1
        avg_conf = sum(confidences) / len(confidences) / 100
        score = avg_conf

        # Variance penalty
        if len(confidences) > 1:
            try:
                variance = statistics.variance(confidences)
                if variance > 500:
                    score *= 0.8  # High variance = problematic
                    logger.debug("Applied variance penalty", variance=variance)
            except statistics.StatisticsError:
                pass

        # Handwriting penalty
        if quality_analysis.get('is_handwritten', False):
            score *= 0.5
            logger.debug("Applied handwriting penalty")

        # Quality details penalties
        details = quality_analysis.get('details', {})
        blur_score = details.get('blur_score', 50)
        contrast_score = details.get('contrast_score', 50)

        # Low blur or contrast penalty
        if blur_score < 20:
            score *= 0.9
        if contrast_score < 30:
            score *= 0.9

        # Normalize to 0-1 range
        score = max(0.0, min(1.0, score))

        # Determine suggested pipeline using OCR_LOW_CONFIDENCE_THRESHOLD from config
        # Threshold is in percentage (0-100), convert to 0-1 range
        threshold = settings.OCR_LOW_CONFIDENCE_THRESHOLD / 100.0
        if score >= threshold and not quality_analysis.get('is_handwritten', False):
            suggested = "florence"
        else:
            suggested = "claude"

        return round(score, 3), suggested

    def get_job(self, job_id: str, db: Session) -> Optional[AnalysisJob]:
        """
        Get an analysis job by ID.

        Args:
            job_id: Job UUID
            db: Database session

        Returns:
            AnalysisJob or None if not found
        """
        return db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()

    def get_job_for_processing(self, job_id: str, db: Session) -> Tuple[Optional[AnalysisJob], Optional[str]]:
        """
        Get a job that's ready for processing.

        Args:
            job_id: Job UUID
            db: Database session

        Returns:
            Tuple of (AnalysisJob or None, error message or None)
        """
        job = self.get_job(job_id, db)

        if not job:
            return None, "Analysis job not found"

        if job.status == "completed":
            return None, "Job has already been processed"

        if job.status == "expired":
            return None, "Job has expired. Please re-upload the document."

        if job.status == "failed":
            return None, f"Job previously failed: {job.processing_error}"

        if job.is_expired:
            job.mark_expired()
            db.commit()
            return None, "Job has expired. Please re-upload the document."

        if job.status != "analyzed":
            return None, f"Job is not ready for processing (status: {job.status})"

        return job, None

    def get_job_images(self, job_id: str) -> Tuple[List[Image.Image], Optional[str]]:
        """
        Load saved page images for a job.

        Args:
            job_id: Job UUID

        Returns:
            Tuple of (list of PIL Images, error message or None)
        """
        images = []
        page = 0

        while True:
            page_path = self.cleanup_service.get_job_file_path(job_id, 'page', page=page)
            if not os.path.exists(page_path):
                break

            try:
                img = Image.open(page_path)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                images.append(img)
                page += 1
            except Exception as e:
                logger.error("Failed to load page image", job_id=job_id, page=page, error=str(e))
                return [], f"Failed to load page {page}: {str(e)}"

        if not images:
            # Try preprocessed image as fallback
            preprocessed_path = self.cleanup_service.get_job_file_path(job_id, 'preprocessed')
            if os.path.exists(preprocessed_path):
                try:
                    img = Image.open(preprocessed_path)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    images.append(img)
                except Exception as e:
                    return [], f"Failed to load preprocessed image: {str(e)}"
            else:
                return [], "No images found for job"

        return images, None

    def check_claude_availability(self, db: Session) -> Tuple[bool, bool]:
        """
        Check if Claude Vision is available and configured.

        Returns:
            Tuple of (available, configured)
            - available: Key exists and is valid
            - configured: Key exists and is valid (same as available)

        Both values are True only when a valid API key is present.
        """
        # Check database-stored key first
        api_key = self.api_key_service.get_api_key('anthropic', db)
        if api_key:
            from app.models.api_key import ApiKey
            api_key_record = db.query(ApiKey).filter(ApiKey.provider == 'anthropic').first()
            if api_key_record and api_key_record.is_valid:
                return True, True

        # Check environment variable fallback - must be valid format
        if settings.has_valid_claude_api_key():
            return True, True

        # No valid key found
        return False, False
