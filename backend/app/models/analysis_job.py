"""
Analysis Job Model - Stores document analysis results for two-step processing workflow.

Workflow:
1. POST /analyze - Creates AnalysisJob with OCR results and quality metrics
2. POST /process - Uses stored job data to process with chosen pipeline
"""

from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, Integer, ForeignKey, JSON
from sqlalchemy.sql import func
from datetime import datetime, timedelta
from app.db.base import Base


class AnalysisJob(Base):
    """
    Stores document analysis results between analyze and process steps.

    Jobs expire after 1 hour if not processed.
    """
    __tablename__ = "analysis_jobs"

    id = Column(String(36), primary_key=True)  # UUID
    status = Column(String(20), default="analyzed", index=True)
    # Status values: analyzed, processing, completed, expired, failed

    # Source file info
    original_filename = Column(String(255))
    file_extension = Column(String(10))
    page_count = Column(Integer, default=1)

    # Analysis results
    confidence_score = Column(Float)
    is_handwritten = Column(Boolean, default=False)
    is_low_quality = Column(Boolean, default=False)
    suggested_pipeline = Column(String(20))  # florence, claude
    quality_classification = Column(String(30))  # good, low_quality, handwritten, extremely_low_quality

    # OCR data (stored to avoid re-processing)
    ocr_full_text = Column(Text)
    ocr_words_json = Column(JSON)  # List of words with positions
    ocr_spatial_grid = Column(Text)

    # Quality analysis details
    quality_details = Column(JSON)
    # Contains: blur_score, contrast_score, word_count, low_conf_ratio

    # Preprocessing report
    preprocessing_report = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, index=True)
    completed_at = Column(DateTime, nullable=True)

    # Final result (if processed)
    result_invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)
    result_document_id = Column(Integer, ForeignKey("other_documents.id", ondelete="SET NULL"), nullable=True)
    processing_method = Column(String(20), nullable=True)  # florence, claude
    processing_error = Column(Text, nullable=True)

    @property
    def is_expired(self) -> bool:
        """Check if job has expired"""
        if not self.expires_at:
            return True
        return datetime.utcnow() > self.expires_at

    @property
    def can_be_processed(self) -> bool:
        """Check if job can still be processed"""
        return self.status == "analyzed" and not self.is_expired

    @property
    def preview_text(self) -> str:
        """Get first 500 characters of OCR text"""
        if self.ocr_full_text:
            return self.ocr_full_text[:500]
        return ""

    @property
    def word_count(self) -> int:
        """Get word count from quality details"""
        if self.quality_details:
            return self.quality_details.get('word_count', 0)
        return 0

    def set_expiration(self, seconds: int = 3600):
        """Set expiration time from now"""
        self.expires_at = datetime.utcnow() + timedelta(seconds=seconds)

    def mark_processing(self):
        """Mark job as currently processing"""
        self.status = "processing"

    def mark_completed(self, invoice_id: int = None, document_id: int = None, method: str = None):
        """Mark job as successfully completed"""
        self.status = "completed"
        self.completed_at = datetime.utcnow()
        self.result_invoice_id = invoice_id
        self.result_document_id = document_id
        self.processing_method = method

    def mark_failed(self, error: str):
        """Mark job as failed"""
        self.status = "failed"
        self.completed_at = datetime.utcnow()
        self.processing_error = error

    def mark_expired(self):
        """Mark job as expired"""
        self.status = "expired"

    def to_analysis_response(self, claude_available: bool, claude_configured: bool) -> dict:
        """Convert to API response format"""
        return {
            'job_id': self.id,
            'confidence_score': self.confidence_score or 0.0,
            'is_handwritten': self.is_handwritten,
            'is_low_quality': self.is_low_quality,
            'suggested_pipeline': self.suggested_pipeline or 'florence',
            'preview_text': self.preview_text,
            'word_count': self.word_count,
            'page_count': self.page_count or 1,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'quality_classification': self.quality_classification,
            'quality_details': self.quality_details or {},
            'claude_available': claude_available,
            'claude_configured': claude_configured,
            'original_filename': self.original_filename
        }
