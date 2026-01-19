# ParseFacture API Documentation

Two-step document processing workflow for invoice extraction.

## Overview

The API uses a two-step workflow:

1. **Analyze** (`POST /analyze`) - Upload document, get quality analysis and job ID
2. **Process** (`POST /process`) - Process with chosen pipeline (Florence or Claude)

This allows users to:
- See OCR confidence before processing
- Choose the best pipeline for their document
- Handle low-quality or handwritten documents with Claude Vision

## Base URL

```
http://localhost:8000/api/v1
```

## Authentication

API keys for external services (Anthropic) are managed via the `/api-keys` endpoints.

---

## Two-Step Workflow

### Step 1: Analyze Document

**Endpoint:** `POST /analyze`

Upload a document to analyze its quality and get a job ID.

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/analyze" \
  -F "file=@invoice.pdf"
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "confidence_score": 0.72,
  "is_handwritten": false,
  "is_low_quality": true,
  "suggested_pipeline": "claude",
  "preview_text": "INVOICE\nCompany Name Inc.\nInvoice #2024-001...",
  "word_count": 156,
  "page_count": 1,
  "expires_at": "2024-01-15T13:00:00",
  "quality_classification": "low_quality",
  "quality_details": {
    "blur_score": 45.2,
    "contrast_score": 62.1,
    "word_count": 156,
    "low_conf_ratio": 0.35
  },
  "claude_available": true,
  "claude_configured": true,
  "original_filename": "invoice.pdf"
}
```

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | UUID to use with `/process` endpoint |
| `confidence_score` | float | 0-1 score indicating OCR quality |
| `is_handwritten` | bool | Whether handwriting was detected |
| `is_low_quality` | bool | Whether quality is below threshold |
| `suggested_pipeline` | string | `"florence"` or `"claude"` |
| `preview_text` | string | First 500 characters of OCR text |
| `expires_at` | string | Job expiration time (1 hour from creation) |
| `claude_available` | bool | Whether Claude API key is valid |
| `claude_configured` | bool | Whether Claude API key exists |

**Supported File Types:**
- PDF (`.pdf`)
- Images: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.tif`, `.webp`

**Max File Size:** 20 MB

---

### Step 2: Process Document

**Endpoint:** `POST /process`

Process the analyzed document with the chosen pipeline.

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/process" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "pipeline": "florence",
    "save_to_db": true
  }'
```

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | string | Yes | Job ID from `/analyze` response |
| `pipeline` | string | Yes | `"florence"` or `"claude"` |
| `save_to_db` | bool | No | Save to database (default: `true`) |

**Response (Success):**
```json
{
  "success": true,
  "invoice_id": 42,
  "document_id": null,
  "extracted_data": {
    "is_invoice": true,
    "provider": "Company Name Inc.",
    "invoice_number": "2024-001",
    "date": "2024-01-15",
    "currency": "EUR",
    "total_ht": 1000.00,
    "total_ttc": 1200.00,
    "line_items": [
      {
        "designation": "Consulting services",
        "quantity": 10,
        "unit_price": 100.00,
        "total_ht": 1000.00
      }
    ]
  },
  "processing_method": "florence",
  "error": null,
  "requires_api_key": false,
  "console_url": null
}
```

**Response (API Key Required):**
```json
{
  "success": false,
  "invoice_id": null,
  "extracted_data": null,
  "processing_method": "claude",
  "error": "Anthropic API key required. Please configure an API key.",
  "requires_api_key": true,
  "console_url": "https://platform.claude.com"
}
```

---

### Check Job Status

**Endpoint:** `GET /jobs/{job_id}/status`

Check the status of an analysis job.

**Request:**
```bash
curl "http://localhost:8000/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000/status"
```

**Response:**
```json
{
  "found": true,
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "is_expired": false,
  "can_be_processed": false,
  "result_invoice_id": 42,
  "result_document_id": null,
  "processing_method": "florence",
  "processing_error": null,
  "created_at": "2024-01-15T12:00:00",
  "expires_at": "2024-01-15T13:00:00",
  "completed_at": "2024-01-15T12:05:00"
}
```

**Job Status Values:**
| Status | Description |
|--------|-------------|
| `analyzed` | Ready to process |
| `processing` | Currently being processed |
| `completed` | Successfully processed |
| `expired` | Expired (not processed within 1 hour) |
| `failed` | Processing failed |

---

## API Key Management

### Store API Key

**Endpoint:** `POST /api-keys`

Store an encrypted API key for a provider.

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/api-keys" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "anthropic",
    "key": "sk-ant-api03-xxxxx",
    "validate": true
  }'
```

**Response:**
```json
{
  "success": true,
  "valid": true,
  "provider": "anthropic",
  "error": null
}
```

---

### Check API Key Status

**Endpoint:** `GET /api-keys/status`

Get the status of all configured API keys.

**Request:**
```bash
curl "http://localhost:8000/api/v1/api-keys/status"
```

**Response:**
```json
{
  "anthropic": {
    "provider": "anthropic",
    "configured": true,
    "valid": true,
    "key_prefix": "sk-ant-api...",
    "error": null,
    "last_validated_at": "2024-01-15T12:00:00"
  },
  "console_url": "https://platform.claude.com"
}
```

---

### Validate API Key

**Endpoint:** `POST /api-keys/{provider}/validate`

Re-validate a stored API key with the provider.

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/api-keys/anthropic/validate"
```

---

### Delete API Key

**Endpoint:** `DELETE /api-keys/{provider}`

Delete a stored API key.

**Request:**
```bash
curl -X DELETE "http://localhost:8000/api/v1/api-keys/anthropic"
```

---

## Cleanup Endpoints

### Manual Cleanup

**Endpoint:** `POST /cleanup`

Trigger cleanup of expired jobs and temp files.

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/cleanup"
```

**Response:**
```json
{
  "expired_jobs_cleaned": 5,
  "files_deleted": 15,
  "errors": []
}
```

---

### Temp Directory Stats

**Endpoint:** `GET /cleanup/stats`

Get statistics about temporary files.

**Request:**
```bash
curl "http://localhost:8000/api/v1/cleanup/stats"
```

**Response:**
```json
{
  "exists": true,
  "file_count": 24,
  "total_size_mb": 156.7,
  "path": "/tmp/parsefacture"
}
```

---

## Invoice CRUD

### List Invoices

**Endpoint:** `GET /invoices`

```bash
curl "http://localhost:8000/api/v1/invoices?skip=0&limit=100"
```

---

### Get Invoice

**Endpoint:** `GET /invoices/{invoice_id}`

```bash
curl "http://localhost:8000/api/v1/invoices/42"
```

**Response:**
```json
{
  "id": 42,
  "provider": "Company Name Inc.",
  "date": "2024-01-15",
  "invoice_number": "2024-001",
  "total_without_vat": 1000.00,
  "total_with_vat": 1200.00,
  "currency": "EUR",
  "original_filename": "invoice.pdf",
  "created_at": "2024-01-15T12:05:00",
  "updated_at": null,
  "lines": [
    {
      "id": 1,
      "invoice_id": 42,
      "designation": "Consulting services",
      "quantity": 10,
      "unit_price": 100.00,
      "total_ht": 1000.00
    }
  ]
}
```

---

### Delete Invoice

**Endpoint:** `DELETE /invoices/{invoice_id}`

```bash
curl -X DELETE "http://localhost:8000/api/v1/invoices/42"
```

---

## Other Documents

### List Other Documents

**Endpoint:** `GET /other-documents`

```bash
curl "http://localhost:8000/api/v1/other-documents"
```

---

### Get Other Document

**Endpoint:** `GET /other-documents/{document_id}`

```bash
curl "http://localhost:8000/api/v1/other-documents/5"
```

---

## Pipelines

### Florence-2 (Default)

- **Use when:** `confidence_score >= 0.6` and not handwritten
- **Pros:** Fast, runs locally, no API costs
- **Cons:** Less accurate for low-quality documents

### Claude Vision

- **Use when:** `confidence_score < 0.6` or handwritten
- **Pros:** Excellent for handwriting and low-quality scans
- **Cons:** Requires API key, per-request costs
- **Get API key:** https://platform.claude.com

---

## Error Handling

### Common Errors

| Status Code | Error | Solution |
|-------------|-------|----------|
| 400 | Invalid file type | Use PDF or supported image format |
| 400 | File size exceeds limit | File must be under 20MB |
| 400 | File already exists | Use a different filename |
| 404 | Job not found | Job expired or invalid ID |
| 500 | Processing error | Check logs for details |

### Job Expiration

Jobs expire after **1 hour** if not processed. After expiration:
- Temp files are deleted
- Job status changes to `expired`
- Must re-upload the document

---

## Example: Complete Workflow

```python
import requests

API_URL = "http://localhost:8000/api/v1"

# Step 1: Analyze document
with open("invoice.pdf", "rb") as f:
    response = requests.post(f"{API_URL}/analyze", files={"file": f})

analysis = response.json()
print(f"Confidence: {analysis['confidence_score']}")
print(f"Suggested pipeline: {analysis['suggested_pipeline']}")

# Step 2: Process with suggested pipeline
process_response = requests.post(
    f"{API_URL}/process",
    json={
        "job_id": analysis["job_id"],
        "pipeline": analysis["suggested_pipeline"],
        "save_to_db": True
    }
)

result = process_response.json()

if result["success"]:
    print(f"Invoice saved with ID: {result['invoice_id']}")
    print(f"Provider: {result['extracted_data']['provider']}")
    print(f"Total: {result['extracted_data']['total_ttc']}")
elif result["requires_api_key"]:
    print(f"API key required. Get one at: {result['console_url']}")
else:
    print(f"Error: {result['error']}")
```

---

## Interactive Documentation

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
