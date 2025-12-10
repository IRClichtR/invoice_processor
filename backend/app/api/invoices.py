import os
import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.models.invoice import Invoice, InvoiceLine, OtherDocument
from app.services.invoice_processor import InvoiceProcessor

router = APIRouter()


# Pydantic schemas for responses
class InvoiceLineResponse(BaseModel):
    id: int
    invoice_id: int
    designation: str | None
    quantity: float | None
    unit: str | None
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
    confidence_score: float | None
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


class ProcessingResultResponse(BaseModel):
    success: bool
    document_type: str | None = None
    invoice_id: int | None = None
    document_id: int | None = None
    processing_steps: dict = {}
    validation: dict | None = None
    error: str | None = None


class FileProcessingResult(BaseModel):
    filename: str
    success: bool
    document_type: str | None = None
    invoice_id: int | None = None
    document_id: int | None = None
    error: str | None = None
    processing_time: float = 0.0


class BatchProcessingResponse(BaseModel):
    total_files: int
    successful: int
    failed: int
    processing_time_seconds: float
    results: List[FileProcessingResult]


@router.post("/invoices/upload", response_model=ProcessingResultResponse)
async def upload_invoice(
    file: UploadFile = File(...),
    preprocessing_mode: str = "none",  # Options: 'none', 'adaptive', 'gentle', 'aggressive'
    db: Session = Depends(get_db),
):
    """
    Upload and process an invoice PDF

    This endpoint:
    1. Converts PDF to images
    2. Applies preprocessing (deskew, CLAHE, denoise)
    3. Extracts text with Tesseract OCR
    4. Uses Qwen2-VL for structured data extraction
    5. Validates if document is an invoice
    6. Validates VAT calculations
    7. Stores in database (invoices or other_documents table)
    """
    # Validate file type
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Validate file size
    if file.spool_max_size and file.spool_max_size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds maximum limit")

    # Validate file is not duplicate (basic check by filename)
    if (
        db.query(Invoice).filter(Invoice.original_filename == file.filename).first()
        or db.query(OtherDocument)
        .filter(OtherDocument.original_filename == file.filename)
        .first()
    ):
        raise HTTPException(
            status_code=400, detail="File with the same name already exists"
        )

    # Save uploaded file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(settings.UPLOAD_DIR, filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Process the PDF
        processor = InvoiceProcessor()
        result = processor.process_pdf(file_path, db, preprocessing_mode, file.filename)

        return ProcessingResultResponse(**result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")

    finally:
        file.file.close()


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


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Delete an invoice and its line items"""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    db.delete(invoice)
    db.commit()

    return {"message": "Invoice deleted successfully"}


def process_single_pdf(pdf_path: str, filename: str) -> FileProcessingResult:
    """
    Process a single PDF file with its own database session
    Thread-safe function for parallel processing

    Args:
        pdf_path: Path to PDF file
        filename: Original filename

    Returns:
        FileProcessingResult with processing outcome
    """
    import time

    start_time = time.time()

    # Create a new database session for this thread
    db = SessionLocal()

    try:
        processor = InvoiceProcessor()
        result = processor.process_pdf(pdf_path, db, original_filename=filename)

        processing_time = time.time() - start_time

        return FileProcessingResult(
            filename=filename,
            success=result.get("success", False),
            document_type=result.get("document_type"),
            invoice_id=result.get("invoice_id"),
            document_id=result.get("document_id"),
            error=result.get("error"),
            processing_time=processing_time,
        )

    except Exception as e:
        processing_time = time.time() - start_time
        return FileProcessingResult(
            filename=filename,
            success=False,
            error=str(e),
            processing_time=processing_time,
        )

    finally:
        db.close()


@router.post("/invoices/batch-upload", response_model=BatchProcessingResponse)
async def batch_upload_invoices(
    files: List[UploadFile] = File(...), max_workers: int = 4
):
    """
    Batch upload and process multiple PDF files with multithreading

    Upload multiple PDF files at once. Files will be processed in parallel
    using multithreading for optimal performance.

    Args:
        files: List of PDF files to process
        max_workers: Maximum number of parallel threads (default: 4)

    Returns:
        Batch processing summary with results for each file
    """
    import time

    batch_start_time = time.time()

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # Validate all files are PDFs
    for file in files:
        if not file.filename.endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"Only PDF files are allowed. Invalid file: {file.filename}",
            )

    # Save all uploaded files first
    saved_files = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        for idx, file in enumerate(files):
            filename = f"{timestamp}_{idx}_{file.filename}"
            file_path = os.path.join(settings.UPLOAD_DIR, filename)

            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            saved_files.append((file_path, file.filename))
            file.file.close()

        # Process files in parallel using ThreadPoolExecutor
        results = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_file = {
                executor.submit(process_single_pdf, file_path, original_name): (
                    file_path,
                    original_name,
                )
                for file_path, original_name in saved_files
            }

            # Collect results as they complete
            for future in as_completed(future_to_file):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    file_path, original_name = future_to_file[future]
                    results.append(
                        FileProcessingResult(
                            filename=original_name,
                            success=False,
                            error=f"Unexpected error: {str(e)}",
                            processing_time=0.0,
                        )
                    )

        # Calculate statistics
        total_files = len(results)
        successful = sum(1 for r in results if r.success)
        failed = total_files - successful
        total_time = time.time() - batch_start_time

        return BatchProcessingResponse(
            total_files=total_files,
            successful=successful,
            failed=failed,
            processing_time_seconds=round(total_time, 2),
            results=results,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch processing error: {str(e)}")


@router.post("/invoices/batch-upload-zip", response_model=BatchProcessingResponse)
async def batch_upload_from_zip(file: UploadFile = File(...), max_workers: int = 4):
    """
    Upload a ZIP file containing multiple PDF invoices and process them in parallel

    Upload a ZIP archive containing PDF files. The system will:
    1. Extract all PDF files from the ZIP
    2. Process them in parallel using multithreading
    3. Return detailed results for each file

    Args:
        file: ZIP file containing PDF invoices
        max_workers: Maximum number of parallel threads (default: 4)

    Returns:
        Batch processing summary with results for each file
    """
    import time

    batch_start_time = time.time()

    # Validate file type
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")

    # Create temporary directory for extraction
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save uploaded ZIP file
        zip_path = os.path.join(temp_dir, file.filename)

        try:
            with open(zip_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            file.file.close()

            # Extract ZIP file
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            # Find all PDF files in the extracted content
            pdf_files = []
            for root, dirs, files in os.walk(temp_dir):
                for filename in files:
                    if filename.endswith(".pdf"):
                        pdf_path = os.path.join(root, filename)
                        # Copy to uploads directory
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        new_filename = f"{timestamp}_{filename}"
                        new_path = os.path.join(settings.UPLOAD_DIR, new_filename)
                        shutil.copy2(pdf_path, new_path)
                        pdf_files.append((new_path, filename))

            if not pdf_files:
                raise HTTPException(
                    status_code=400, detail="No PDF files found in ZIP archive"
                )

            # Process files in parallel using ThreadPoolExecutor
            results = []

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_file = {
                    executor.submit(process_single_pdf, file_path, original_name): (
                        file_path,
                        original_name,
                    )
                    for file_path, original_name in pdf_files
                }

                # Collect results as they complete
                for future in as_completed(future_to_file):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        file_path, original_name = future_to_file[future]
                        results.append(
                            FileProcessingResult(
                                filename=original_name,
                                success=False,
                                error=f"Unexpected error: {str(e)}",
                                processing_time=0.0,
                            )
                        )

            # Calculate statistics
            total_files = len(results)
            successful = sum(1 for r in results if r.success)
            failed = total_files - successful
            total_time = time.time() - batch_start_time

            return BatchProcessingResponse(
                total_files=total_files,
                successful=successful,
                failed=failed,
                processing_time_seconds=round(total_time, 2),
                results=results,
            )

        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file")
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Batch processing error: {str(e)}"
            )