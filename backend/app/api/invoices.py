import os
import shutil
import tempfile
import zipfile
import structlog
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.models.invoice import Invoice, InvoiceLine, OtherDocument
from app.services.invoice_processor import InvoiceProcessor

router = APIRouter()
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB

logger = structlog.get_logger(__name__)

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
    page_count: int | None = None
    extracted_data: dict | None = None
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


def _process_upload_in_thread(file_path: str, original_filename: str) -> Dict[str, Any]:
    """Thread-safe processing with its own database session"""
    db = SessionLocal()
    try:
        logger.info("Processing uploaded file in threadpool", filename=original_filename)
        processor = InvoiceProcessor()
        result = processor.process_pdf(file_path, db, original_filename)
        return result
    finally:
        db.close()


@router.post("/invoices/upload", response_model=ProcessingResultResponse)
async def upload_invoice(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload and process an invoice PDF

    Pipeline: PDF -> Image -> Qwen2-VL -> SQLite
    """
    if not file.filename.endswith(".pdf"):
        logger.warning("Invalid file type uploaded", filename=file.filename)
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Check file size
    try:
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        if file_size > MAX_FILE_SIZE_BYTES:
            logger.warning("File size exceeds limit", filename=file.filename, size=file_size)
            raise HTTPException(
                status_code=400,
                detail=f"File size ({file_size / (1024*1024):.2f}MB) exceeds maximum limit of {MAX_FILE_SIZE_BYTES // (1024*1024)}MB"
            )
    except Exception as e:
        logger.error("Error checking file size", filename=file.filename, error=str(e))
        raise HTTPException(status_code=400, detail=f"Unable to determine file size: {str(e)}")

    # Check for duplicate filename
    if (
        db.query(Invoice).filter(Invoice.original_filename == file.filename).first()
        or db.query(OtherDocument).filter(OtherDocument.original_filename == file.filename).first()
    ):
        raise HTTPException(status_code=400, detail="File with the same name already exists")

    # Save uploaded file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(settings.UPLOAD_DIR, filename)
    logger.info("Saving uploaded file", filename=file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        result = await run_in_threadpool(_process_upload_in_thread, file_path, file.filename)
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
    """Process a single PDF file with its own database session"""
    import time
    start_time = time.time()
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
        return FileProcessingResult(
            filename=filename,
            success=False,
            error=str(e),
            processing_time=time.time() - start_time,
        )
    finally:
        db.close()


@router.post("/invoices/batch-upload", response_model=BatchProcessingResponse)
async def batch_upload_invoices(files: List[UploadFile] = File(...), max_workers: int = 4):
    """Batch upload and process multiple PDF files"""
    import time
    batch_start_time = time.time()

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    for file in files:
        if not file.filename.endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"Only PDF files are allowed. Invalid file: {file.filename}",
            )

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

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(process_single_pdf, file_path, original_name): (file_path, original_name)
                for file_path, original_name in saved_files
            }

            for future in as_completed(future_to_file):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    file_path, original_name = future_to_file[future]
                    results.append(FileProcessingResult(
                        filename=original_name,
                        success=False,
                        error=f"Unexpected error: {str(e)}",
                        processing_time=0.0,
                    ))

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
    """Upload a ZIP file containing multiple PDF invoices"""
    import time
    batch_start_time = time.time()

    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")

    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, file.filename)

        try:
            with open(zip_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            file.file.close()

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            pdf_files = []
            for root, dirs, files in os.walk(temp_dir):
                for filename in files:
                    if filename.endswith(".pdf"):
                        pdf_path = os.path.join(root, filename)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        new_filename = f"{timestamp}_{filename}"
                        new_path = os.path.join(settings.UPLOAD_DIR, new_filename)
                        shutil.copy2(pdf_path, new_path)
                        pdf_files.append((new_path, filename))

            if not pdf_files:
                raise HTTPException(status_code=400, detail="No PDF files found in ZIP archive")

            results = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {
                    executor.submit(process_single_pdf, file_path, original_name): (file_path, original_name)
                    for file_path, original_name in pdf_files
                }

                for future in as_completed(future_to_file):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        file_path, original_name = future_to_file[future]
                        results.append(FileProcessingResult(
                            filename=original_name,
                            success=False,
                            error=f"Unexpected error: {str(e)}",
                            processing_time=0.0,
                        ))

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
            raise HTTPException(status_code=500, detail=f"Batch processing error: {str(e)}")
