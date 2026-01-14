# Invoice Processor API

A comprehensive backend API for processing invoices in PDF format with OCR, VLM extraction, and validation.

## Features

- **PDF Processing**: Convert PDF documents to images
- **Image Preprocessing**: Deskew, CLAHE contrast enhancement, denoising, and binarization
- **OCR Extraction**: Tesseract OCR optimized for French and English text with position and confidence data
- **VLM Extraction**: Florence-2 Vision-Language Model for structured data extraction
- **Invoice Validation**: Automatic detection of invoice documents and VAT validation
- **Database Storage**: PostgreSQL database with separate tables for invoices, invoice lines, and other documents

## Tech Stack

- **FastAPI**: Modern Python web framework
- **PostgreSQL**: Relational database
- **Tesseract OCR**: Text extraction with French and English support
- **Florence-2**: Vision-Language Model for structured data extraction
- **OpenCV**: Image preprocessing
- **Docker**: Containerized deployment

## Database Schema

### Invoices Table
- `id`: Primary key
- `provider`: Supplier/provider name
- `date`: Invoice date
- `invoice_number`: Invoice number
- `total_without_vat`: Total amount HT
- `total_with_vat`: Total amount TTC
- `confidence_score`: OCR confidence score
- `raw_vlm_json`: Raw VLM extraction JSON (for debugging)
- `raw_vlm_response`: Raw VLM response text (for debugging)
- `created_at`: Creation timestamp
- `updated_at`: Update timestamp

### Invoice Lines Table
- `id`: Primary key
- `invoice_id`: Foreign key to invoices
- `designation`: Item description
- `quantity`: Quantity
- `unit`: Unit of measure
- `unit_price`: Unit price
- `total_ht`: Line total without VAT

### Other Documents Table
- `id`: Primary key
- `provider`: Document provider (if detectable)
- `raw_text`: Full OCR text
- `created_at`: Creation timestamp
- `updated_at`: Update timestamp

## Setup

### Prerequisites

- Docker and Docker Compose
- At least 4GB RAM (for Florence-2 model)
- GPU (optional, for faster processing)

### Installation

1. Clone the repository:
```bash
cd invoice_processor
```

2. Build and start the containers:
```bash
docker-compose up --build
```

3. The API will be available at `http://localhost:8000`

### API Documentation

Once running, access the interactive API documentation at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## API Endpoints

### Upload Invoice
```
POST /api/v1/invoices/upload
```
Upload a PDF file for processing. The system will:
1. Convert PDF to images
2. Preprocess images (deskew, CLAHE, denoise)
3. Extract text with Tesseract OCR
4. Use Florence-2 for structured extraction
5. Validate if document is an invoice
6. Validate VAT calculations
7. Store in appropriate database table

**Request**: multipart/form-data with PDF file

**Response**:
```json
{
  "success": true,
  "document_type": "invoice",
  "invoice_id": 1,
  "processing_steps": {
    "pdf_conversion": {"success": true, "page_count": 2},
    "preprocessing": {"success": true, "images_processed": 2},
    "ocr": {"success": true, "average_confidence": 87.5},
    "validation": {"is_invoice": true, "confidence": 0.8}
  },
  "validation": {
    "overall_valid": true,
    "validations": {
      "vat": {"is_valid": true, "difference": 0.01}
    }
  }
}
```

### Get All Invoices
```
GET /api/v1/invoices?skip=0&limit=100
```

### Get Invoice by ID
```
GET /api/v1/invoices/{invoice_id}
```

### Get Other Documents
```
GET /api/v1/other-documents?skip=0&limit=100
```

### Delete Invoice
```
DELETE /api/v1/invoices/{invoice_id}
```

## Processing Pipeline

1. **PDF to Images**: Convert each PDF page to high-resolution images (300 DPI)

2. **Preprocessing**:
   - **Deskew**: Correct rotation/skew
   - **CLAHE**: Enhance contrast
   - **Denoise**: Remove noise
   - **Binarization**: Optional black/white conversion

3. **OCR with Tesseract**:
   - Extract text with French and English language models
   - Capture word positions and confidence scores
   - Organize text by blocks and lines

4. **VLM Extraction with Florence-2**:
   - Sophisticated table detection
   - Column identification (designation, quantity, price, total)
   - Line item extraction using spatial analysis
   - Fallback methods for non-tabular formats

5. **Validation**:
   - Document type detection (invoice vs. other)
   - VAT calculation validation
   - Line item sum verification
   - Completeness check

6. **Database Storage**:
   - Invoices stored in `invoices` and `invoice_lines` tables
   - Non-invoice documents in `other_documents` table
   - Raw data preserved for debugging

## Configuration

Edit `backend/.env` to configure:

```env
DATABASE_URL=postgresql://postgres:postgres@db:5432/invoice_db
TESSERACT_LANG=fra+eng  # OCR languages
DEVICE=cpu  # or 'cuda' for GPU
```

## Development

### Running Locally

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Database Migrations

The application automatically creates tables on startup. For production, consider using Alembic migrations.

## Testing

Upload a sample invoice:

```bash
curl -X POST "http://localhost:8000/api/v1/invoices/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@sample_invoice.pdf"
```

## Performance Notes

- **OCR**: ~2-5 seconds per page
- **Florence-2**: ~5-15 seconds (CPU), ~1-3 seconds (GPU)
- **Total**: ~10-25 seconds per invoice on CPU

## Troubleshooting

### Tesseract Language Data
If you encounter "Error loading language data" errors, ensure French and English language packs are installed:

```bash
# In Docker container
apt-get update
apt-get install tesseract-ocr-fra tesseract-ocr-eng
```

### Memory Issues
Florence-2 requires significant RAM. If you encounter OOM errors:
- Increase Docker memory limit
- Use CPU instead of GPU
- Process one page at a time

### Low OCR Confidence
If OCR confidence is low:
- Check PDF quality
- Adjust preprocessing parameters
- Verify correct language settings

## License

MIT

## TODOS
- test anthropic handwritting model for handwritten invoices
- contact https://www.transkribus.org/ for handwritten invoice processing options
