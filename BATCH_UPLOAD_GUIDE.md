# Batch Upload Guide

The Invoice Processor API now supports batch processing of multiple PDF files with **multithreading optimization** for parallel processing.

## Two Batch Upload Methods

### 1. Multiple Files Upload
Upload multiple PDF files directly in a single request.

**Endpoint**: `POST /api/v1/invoices/batch-upload`

**Parameters**:
- `files`: List of PDF files
- `max_workers`: Number of parallel threads (default: 4)

**Example using cURL**:
```bash
curl -X POST "http://localhost:8000/api/v1/invoices/batch-upload?max_workers=4" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@invoice1.pdf" \
  -F "files=@invoice2.pdf" \
  -F "files=@invoice3.pdf" \
  -F "files=@invoice4.pdf"
```

**Example using Python**:
```python
import requests

files = [
    ('files', open('invoice1.pdf', 'rb')),
    ('files', open('invoice2.pdf', 'rb')),
    ('files', open('invoice3.pdf', 'rb')),
]

response = requests.post(
    'http://localhost:8000/api/v1/invoices/batch-upload',
    files=files,
    params={'max_workers': 4}
)

print(response.json())
```

### 2. ZIP Archive Upload
Upload a single ZIP file containing multiple PDF invoices.

**Endpoint**: `POST /api/v1/invoices/batch-upload-zip`

**Parameters**:
- `file`: ZIP archive containing PDF files
- `max_workers`: Number of parallel threads (default: 4)

**Example using cURL**:
```bash
curl -X POST "http://localhost:8000/api/v1/invoices/batch-upload-zip?max_workers=6" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@invoices.zip"
```

**Example using Python**:
```python
import requests

with open('invoices.zip', 'rb') as f:
    response = requests.post(
        'http://localhost:8000/api/v1/invoices/batch-upload-zip',
        files={'file': f},
        params={'max_workers': 6}
    )

print(response.json())
```

## Response Format

Both endpoints return a `BatchProcessingResponse` with detailed results:

```json
{
  "total_files": 10,
  "successful": 8,
  "failed": 2,
  "processing_time_seconds": 45.67,
  "results": [
    {
      "filename": "invoice1.pdf",
      "success": true,
      "document_type": "invoice",
      "invoice_id": 123,
      "document_id": null,
      "error": null,
      "processing_time": 5.23
    },
    {
      "filename": "invoice2.pdf",
      "success": true,
      "document_type": "other",
      "invoice_id": null,
      "document_id": 45,
      "error": null,
      "processing_time": 4.87
    },
    {
      "filename": "corrupted.pdf",
      "success": false,
      "document_type": null,
      "invoice_id": null,
      "document_id": null,
      "error": "Error converting PDF to images: PDF file is corrupted",
      "processing_time": 0.12
    }
  ]
}
```

## Multithreading Optimization

### How It Works

1. **Thread Pool**: Uses `ThreadPoolExecutor` to create a pool of worker threads
2. **Parallel Processing**: Each PDF is processed in its own thread
3. **Independent Sessions**: Each thread has its own database session to avoid conflicts
4. **Async Completion**: Results are collected as they complete (not in order)

### Performance Benefits

**Single-threaded (sequential)**:
- 10 invoices × 10 seconds each = **100 seconds total**

**Multi-threaded (4 workers)**:
- 10 invoices / 4 threads = 2.5 batches
- 2.5 batches × 10 seconds = **~25-30 seconds total**

**Speed improvement**: ~70% faster!

### Choosing max_workers

The optimal number of workers depends on your system:

- **CPU-only processing**:
  - 2-4 workers for dual-core
  - 4-8 workers for quad-core
  - 8-16 workers for high-end systems

- **GPU processing**:
  - 1-2 workers (Florence-2 model benefits from GPU but is memory-intensive)
  - Multiple workers compete for GPU memory

- **Recommended**:
  - Start with 4 workers
  - Increase gradually while monitoring CPU/memory usage
  - Don't exceed CPU core count × 2

### Memory Considerations

Each worker loads:
- PDF into memory
- Converted images
- OCR data
- Florence-2 model (if not cached)

**Estimate**: ~500MB-1GB per worker

For 4 workers: **2-4GB RAM recommended**
For 8 workers: **4-8GB RAM recommended**

## Best Practices

### 1. ZIP Archive Method (Recommended for Many Files)

✓ **Advantages**:
- Single upload operation
- Preserves directory structure
- Easier to organize
- Reduces HTTP overhead

```bash
# Create ZIP archive
zip -r invoices.zip invoice_folder/

# Upload
curl -X POST "http://localhost:8000/api/v1/invoices/batch-upload-zip" \
  -F "file=@invoices.zip"
```

### 2. Direct Multiple Files (For Few Files)

✓ **Advantages**:
- No need to create archive
- Direct file selection
- Simpler for small batches

### 3. Optimal Worker Configuration

```python
import os

# Auto-detect optimal workers
cpu_count = os.cpu_count()
max_workers = min(cpu_count, 8)  # Cap at 8

response = requests.post(
    'http://localhost:8000/api/v1/invoices/batch-upload-zip',
    files={'file': open('invoices.zip', 'rb')},
    params={'max_workers': max_workers}
)
```

### 4. Error Handling

```python
response_data = response.json()

# Check overall success
if response_data['failed'] > 0:
    print(f"⚠️  {response_data['failed']} files failed")

    # List failed files
    for result in response_data['results']:
        if not result['success']:
            print(f"❌ {result['filename']}: {result['error']}")

# List successful invoices
print(f"✓ Successfully processed {response_data['successful']} invoices")
for result in response_data['results']:
    if result['success'] and result['document_type'] == 'invoice':
        print(f"✓ {result['filename']} → Invoice ID: {result['invoice_id']}")
```

## Example: Processing a Directory

Here's a complete Python script to process all PDFs in a directory:

```python
import os
import zipfile
import requests
from pathlib import Path

def batch_process_directory(directory_path, api_url="http://localhost:8000"):
    """Process all PDFs in a directory using batch upload"""

    # Create temporary ZIP file
    zip_path = "temp_invoices.zip"

    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for pdf_file in Path(directory_path).glob("*.pdf"):
            zipf.write(pdf_file, pdf_file.name)

    # Upload and process
    with open(zip_path, 'rb') as f:
        response = requests.post(
            f"{api_url}/api/v1/invoices/batch-upload-zip",
            files={'file': f},
            params={'max_workers': 6}
        )

    # Clean up
    os.remove(zip_path)

    # Process results
    data = response.json()
    print(f"\n📊 Batch Processing Results:")
    print(f"   Total files: {data['total_files']}")
    print(f"   ✓ Successful: {data['successful']}")
    print(f"   ❌ Failed: {data['failed']}")
    print(f"   ⏱️  Processing time: {data['processing_time_seconds']}s")

    return data

# Usage
results = batch_process_directory("./invoice_folder")
```

## Performance Monitoring

Track processing performance:

```python
results = response.json()

# Overall metrics
total_time = results['processing_time_seconds']
total_files = results['total_files']
avg_time_per_file = total_time / total_files

print(f"Average processing time per file: {avg_time_per_file:.2f}s")

# Individual file times
for result in results['results']:
    print(f"{result['filename']}: {result['processing_time']:.2f}s")
```

## Troubleshooting

### Issue: Out of Memory

**Solution**: Reduce `max_workers`
```bash
# Use fewer workers
curl -X POST "...?max_workers=2"
```

### Issue: Slow Processing

**Potential causes**:
1. Too many workers (CPU contention)
2. Large PDF files
3. Poor quality scans (OCR takes longer)

**Solutions**:
- Adjust worker count
- Process in smaller batches
- Pre-filter poor quality PDFs

### Issue: Database Lock Errors

**Solution**: Already handled! Each thread has its own database session.

## API Documentation

Interactive documentation available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

Try out the batch endpoints directly in the Swagger UI!
