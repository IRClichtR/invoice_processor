FROM python:3.11-slim

WORKDIR /app

# Install system dependencies: poppler (PDF), tesseract (OCR), curl (healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-eng \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default environment for Docker (override at runtime as needed)
ENV HOST=0.0.0.0
ENV DATA_DIR=/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "run_server.py"]
