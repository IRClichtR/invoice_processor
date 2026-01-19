"""
Invoice API - Two-step document processing workflow.

Endpoints:
- POST /analyze: Step 1 - Analyze document quality
- POST /process: Step 2 - Process with chosen pipeline
- GET /jobs/{id}/status: Check job status
- POST /cleanup: Manual cleanup of expired jobs
- GET /cleanup/stats: Temp directory statistics
- CRUD operations for invoices and other documents
"""

import os
import shutil
import structlog
from datetime import datetime
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.models.invoice import Invoice, OtherDocument
from app.services.analysis_service import AnalysisService
from app.services.processing_service import ProcessingService
from app.services.cleanup_service import CleanupService

router = APIRouter()
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB

logger = structlog.get_logger(__name__)


# =========================================================================
# Response Models
# =========================================================================

class InvoiceLineResponse(BaseModel):
    id: int
    invoice_id: int
    designation: str | None
    quantity: float | None
    unit_price: float | None
    total_ht: float | None

    class Config:
        from_attributes = True


class InvoiceResponse(BaseModel):
    id: int
    provider: str
    date: str | None
    invoice_number: str | None
    total_without_vat: float | None
    total_with_vat: float | None
    currency: str = 'XXX'
    original_filename: str | None
    created_at: datetime | None
    updated_at: datetime | None
    lines: List[InvoiceLineResponse] = []

    class Config:
        from_attributes = True


class OtherDocumentResponse(BaseModel):
    id: int
    provider: str | None
    original_filename: str | None
    raw_text: str | None
    created_at: datetime | None

    class Config:
        from_attributes = True


class QualityDetails(BaseModel):
    """Quality analysis details"""
    blur_score: float = 0.0
    contrast_score: float = 0.0
    word_count: int = 0
    low_conf_ratio: float = 0.0


class AnalyzeResponse(BaseModel):
    """Response from /analyze endpoint (Step 1)"""
    job_id: str
    confidence_score: float
    is_handwritten: bool
    is_low_quality: bool
    suggested_pipeline: str  # 'florence' or 'claude'
    preview_text: str  # First 500 characters
    word_count: int
    page_count: int
    expires_at: str | None
    quality_classification: str
    quality_details: QualityDetails
    claude_available: bool
    claude_configured: bool
    original_filename: str | None


class ProcessRequest(BaseModel):
    """Request to process a job (Step 2)"""
    job_id: str
    pipeline: Literal['florence', 'claude']
    save_to_db: bool = True


class ProcessResponse(BaseModel):
    """Response from /process endpoint (Step 2)"""
    success: bool
    invoice_id: int | None = None
    document_id: int | None = None
    extracted_data: dict | None = None
    processing_method: str | None = None
    error: str | None = None
    requires_api_key: bool = False
    console_url: str | None = None


class JobStatusResponse(BaseModel):
    """Response from job status check"""
    found: bool
    job_id: str | None = None
    status: str | None = None
    is_expired: bool = False
    can_be_processed: bool = False
    result_invoice_id: int | None = None
    result_document_id: int | None = None
    processing_method: str | None = None
    processing_error: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class CleanupResponse(BaseModel):
    """Response from cleanup endpoint"""
    expired_jobs_cleaned: int
    files_deleted: int
    errors: List[str] = []


class TempDirStatsResponse(BaseModel):
    """Response with temp directory stats"""
    exists: bool
    file_count: int
    total_size_mb: float
    path: str


# =========================================================================
# Helpers
# =========================================================================

ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}


def _is_allowed_file(filename: str) -> bool:
    """Check if filename has an allowed extension"""
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_EXTENSIONS


def _analyze_document_in_thread(file_path: str, original_filename: str) -> Dict[str, Any]:
    """Thread-safe document analysis with database persistence"""
    db = SessionLocal()
    try:
        analysis_service = AnalysisService()
        job = analysis_service.analyze_document(file_path, original_filename, db)

        # Check Claude availability
        claude_available, claude_configured = analysis_service.check_claude_availability(db)

        return job.to_analysis_response(claude_available, claude_configured)
    finally:
        db.close()


def _process_job_in_thread(job_id: str, pipeline: str, save_to_db: bool) -> Dict[str, Any]:
    """Thread-safe job processing"""
    db = SessionLocal()
    try:
        processing_service = ProcessingService()
        return processing_service.process_job(job_id, pipeline, save_to_db, db)
    finally:
        db.close()


# =========================================================================
# Two-Step Workflow Endpoints
# =========================================================================

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Step 1: Analyze document quality and OCR confidence.

    This endpoint:
    1. Saves the uploaded file to temp storage
    2. Runs OCR and quality analysis
    3. Calculates confidence score
    4. Returns job_id for use with /process endpoint

    The job expires after 1 hour if not processed.

    Response includes:
    - job_id: Use this with /process endpoint
    - confidence_score: 0-1 score indicating OCR quality
    - suggested_pipeline: 'florence' or 'claude' based on quality
    - claude_available: Whether Claude API is configured and valid
    """
    if not _is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Allowed: PDF, JPG, JPEG, PNG, BMP, TIFF, WEBP"
        )

    # Check file size
    try:
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        if file_size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File size exceeds {MAX_FILE_SIZE_BYTES // (1024*1024)}MB limit"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error checking file size: {str(e)}")

    # Check for duplicate filename in existing invoices
    if (
        db.query(Invoice).filter(Invoice.original_filename == file.filename).first()
        or db.query(OtherDocument).filter(OtherDocument.original_filename == file.filename).first()
    ):
        raise HTTPException(status_code=400, detail="File with the same name already exists")

    # Save file temporarily
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(settings.UPLOAD_DIR, filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        result = await run_in_threadpool(_analyze_document_in_thread, file_path, file.filename)

        # Convert quality_details dict to model
        quality_details = result.get('quality_details', {})
        result['quality_details'] = QualityDetails(**quality_details)

        return AnalyzeResponse(**result)

    except Exception as e:
        logger.error("Analysis error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Analysis error: {str(e)}")
    finally:
        file.file.close()
        # Clean up the upload directory copy (job has its own copy in temp dir)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass


@router.post("/process", response_model=ProcessResponse)
async def process_document(request: ProcessRequest):
    """
    Step 2: Process document with chosen pipeline.

    After analyzing a document with /analyze, use this endpoint to:
    - Process with Florence-2 (pipeline='florence') - fast, local, good for clear documents
    - Process with Claude Vision (pipeline='claude') - better for low quality/handwritten

    If Claude is selected but no API key is configured, the response will include
    requires_api_key=true and console_url for obtaining a key.

    Args:
        job_id: The job ID from /analyze response
        pipeline: 'florence' or 'claude'
        save_to_db: Whether to save extracted invoice to database (default: true)
    """
    result = await run_in_threadpool(
        _process_job_in_thread,
        request.job_id,
        request.pipeline,
        request.save_to_db
    )
    return ProcessResponse(**result)


@router.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """
    Get the status of an analysis job.

    Returns current status, expiration info, and results if completed.
    """
    processing_service = ProcessingService()
    result = processing_service.get_job_status(job_id, db)
    return JobStatusResponse(**result)


# =========================================================================
# Cleanup Endpoints
# =========================================================================

@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_expired_jobs(db: Session = Depends(get_db)):
    """
    Manually trigger cleanup of expired jobs and temp files.

    This endpoint:
    - Finds all jobs older than 1 hour that weren't processed
    - Deletes their temp files
    - Marks them as expired
    - Cleans up orphaned files

    This is also run automatically at startup.
    """
    cleanup_service = CleanupService()
    result = cleanup_service.full_cleanup(db)

    return CleanupResponse(
        expired_jobs_cleaned=result['expired_jobs']['jobs_cleaned'],
        files_deleted=result['total_files_deleted'],
        errors=result['errors']
    )

@router.post("/cleanup-force", response_model=CleanupResponse)
async def force_cleanup_all_jobs(db: Session = Depends(get_db)):
    """
    Force cleanup of all jobs and temporary files, regardless of age.

    This endpoint:
    - Deletes all job temp files
    - Marks all jobs as expired
    - Cleans up orphaned files

    Use with caution as this will remove all job data.
    """
    cleanup_service = CleanupService()
    result = cleanup_service.force_cleanup(db)

    return CleanupResponse(
        expired_jobs_cleaned=result['expired_jobs']['jobs_cleaned'],
        files_deleted=result['total_files_deleted'],
        errors=result['errors']
    )


@router.get("/cleanup/stats", response_model=TempDirStatsResponse)
async def get_temp_dir_stats():
    """
    Get statistics about the temporary files directory.

    Useful for monitoring disk usage.
    """
    cleanup_service = CleanupService()
    stats = cleanup_service.get_temp_dir_stats()
    return TempDirStatsResponse(**stats)


# =========================================================================
# Invoice CRUD Endpoints
# =========================================================================

@router.get("/invoices", response_model=List[InvoiceResponse])
def get_invoices(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Get list of invoices"""
    invoices = db.query(Invoice).offset(skip).limit(limit).all()
    return invoices


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Get specific invoice by ID"""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Delete an invoice and its line items"""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    db.delete(invoice)
    db.commit()
    return {"message": "Invoice deleted successfully"}


# =========================================================================
# Other Documents CRUD Endpoints
# =========================================================================

@router.get("/other-documents", response_model=List[OtherDocumentResponse])
def get_other_documents(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Get list of non-invoice documents"""
    documents = db.query(OtherDocument).offset(skip).limit(limit).all()
    return documents


@router.get("/other-documents/{document_id}", response_model=OtherDocumentResponse)
def get_other_document(document_id: int, db: Session = Depends(get_db)):
    """Get specific non-invoice document by ID"""
    document = db.query(OtherDocument).filter(OtherDocument.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document
