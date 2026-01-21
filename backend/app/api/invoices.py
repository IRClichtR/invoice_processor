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
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.models.invoice import Invoice, InvoiceLine, OtherDocument
from app.services.analysis_service import AnalysisService
from app.services.processing_service import ProcessingService
from app.services.cleanup_service import CleanupService
from app.services.document_storage_service import document_storage_service

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
    document_path: str | None = None
    has_document: bool = False
    created_at: datetime | None
    updated_at: datetime | None
    lines: List[InvoiceLineResponse] = []

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_document_check(cls, invoice: Invoice):
        """Create response with document availability check"""
        data = {
            'id': invoice.id,
            'provider': invoice.provider,
            'date': invoice.date,
            'invoice_number': invoice.invoice_number,
            'total_without_vat': invoice.total_without_vat,
            'total_with_vat': invoice.total_with_vat,
            'currency': invoice.currency,
            'original_filename': invoice.original_filename,
            'document_path': invoice.document_path,
            'has_document': bool(invoice.document_path and document_storage_service.document_exists(invoice.document_path)),
            'created_at': invoice.created_at,
            'updated_at': invoice.updated_at,
            'lines': [InvoiceLineResponse.model_validate(line) for line in invoice.lines]
        }
        return cls(**data)


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
# Update Request Models
# =========================================================================

class InvoiceLineUpdate(BaseModel):
    """Model for updating or creating a line item"""
    id: int | None = None  # None for new line items
    designation: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    total_ht: float | None = None
    delete: bool = Field(default=False, alias='_delete')

    class Config:
        populate_by_name = True


class InvoiceUpdate(BaseModel):
    """Model for updating an invoice"""
    provider: str | None = None
    date: str | None = None
    invoice_number: str | None = None
    total_without_vat: float | None = None
    total_with_vat: float | None = None
    currency: str | None = None
    lines: List[InvoiceLineUpdate] | None = None


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


@router.get("/jobs/{job_id}/image")
async def get_job_image(job_id: str, page: int = 0, db: Session = Depends(get_db)):
    """
    Get the page image for an analysis job.

    Used to display the original document during review.
    """
    from app.services.analysis_service import AnalysisService

    analysis_service = AnalysisService()
    job = analysis_service.get_job(job_id, db)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get the page image path
    cleanup_service = CleanupService()
    page_path = cleanup_service.get_job_file_path(job_id, 'page', page=page)

    if not os.path.exists(page_path):
        # Try preprocessed as fallback
        page_path = cleanup_service.get_job_file_path(job_id, 'preprocessed')
        if not os.path.exists(page_path):
            raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(
        path=page_path,
        media_type="image/png",
        content_disposition_type="inline"
    )


@router.delete("/jobs/{job_id}")
async def cleanup_job(job_id: str, db: Session = Depends(get_db)):
    """
    Clean up temp files for a specific job after review is complete.
    """
    cleanup_service = CleanupService()
    result = cleanup_service.cleanup_job_files(job_id)
    return {"success": result['success'], "files_deleted": result['files_deleted']}


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
    return [InvoiceResponse.from_orm_with_document_check(inv) for inv in invoices]


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Get specific invoice by ID"""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return InvoiceResponse.from_orm_with_document_check(invoice)


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Delete an invoice, its line items, and stored document"""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Delete stored document if exists
    if invoice.document_path:
        document_storage_service.delete_document(invoice.document_path)

    db.delete(invoice)
    db.commit()
    return {"message": "Invoice deleted successfully"}


@router.get("/invoices/{invoice_id}/document")
def get_invoice_document(invoice_id: int, db: Session = Depends(get_db)):
    """
    Serve the original document for an invoice.

    Returns the file with appropriate content-type (PDF or image).
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if not invoice.document_path:
        raise HTTPException(status_code=404, detail="No document stored for this invoice")

    file_path = document_storage_service.get_document_path(invoice.document_path)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Document file not found on disk")

    media_type = document_storage_service.get_media_type(invoice.document_path)

    return FileResponse(
        path=file_path,
        media_type=media_type,
        content_disposition_type="inline"
    )


@router.put("/invoices/{invoice_id}", response_model=InvoiceResponse)
def update_invoice(
    invoice_id: int,
    update_data: InvoiceUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an invoice and its line items.

    For line items:
    - Items with id: Update existing line item
    - Items without id: Create new line item
    - Items with _delete=true: Delete the line item
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Update invoice fields (only non-None values)
    if update_data.provider is not None:
        invoice.provider = update_data.provider[:255]
    if update_data.date is not None:
        invoice.date = update_data.date[:50] if update_data.date else None
    if update_data.invoice_number is not None:
        invoice.invoice_number = update_data.invoice_number[:100] if update_data.invoice_number else None
    if update_data.total_without_vat is not None:
        invoice.total_without_vat = update_data.total_without_vat
    if update_data.total_with_vat is not None:
        invoice.total_with_vat = update_data.total_with_vat
    if update_data.currency is not None:
        currency = update_data.currency[:3].upper() if update_data.currency else 'XXX'
        invoice.currency = currency if len(currency) == 3 else 'XXX'

    # Handle line items
    if update_data.lines is not None:
        # Get existing line IDs
        existing_line_ids = {line.id for line in invoice.lines}

        for line_update in update_data.lines:
            if line_update.delete and line_update.id:
                # Delete existing line
                line = db.query(InvoiceLine).filter(
                    InvoiceLine.id == line_update.id,
                    InvoiceLine.invoice_id == invoice_id
                ).first()
                if line:
                    db.delete(line)
            elif line_update.id and line_update.id in existing_line_ids:
                # Update existing line
                line = db.query(InvoiceLine).filter(
                    InvoiceLine.id == line_update.id,
                    InvoiceLine.invoice_id == invoice_id
                ).first()
                if line:
                    if line_update.designation is not None:
                        line.designation = line_update.designation[:500] if line_update.designation else None
                    if line_update.quantity is not None:
                        line.quantity = line_update.quantity
                    if line_update.unit_price is not None:
                        line.unit_price = line_update.unit_price
                    if line_update.total_ht is not None:
                        line.total_ht = line_update.total_ht
            elif not line_update.id and not line_update.delete:
                # Create new line
                new_line = InvoiceLine(
                    invoice_id=invoice_id,
                    designation=line_update.designation[:500] if line_update.designation else None,
                    quantity=line_update.quantity,
                    unit_price=line_update.unit_price,
                    total_ht=line_update.total_ht
                )
                db.add(new_line)

    db.commit()
    db.refresh(invoice)

    return InvoiceResponse.from_orm_with_document_check(invoice)


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
