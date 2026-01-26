# Invoicator

[![Donate using Liberapay](https://liberapay.com/assets/widgets/donate.svg)](https://liberapay.com/IRClichtR/donate)

A desktop application for processing invoices locally using OCR and vision-language models. Built with Tauri, Vue.js, and a Python/FastAPI backend.

## Features

- **Local-first processing**: Documents are processed on your machine -- no cloud upload required
- **PDF and image support**: Process PDF documents and image files (JPG, PNG, TIFF, WEBP)
- **OCR extraction**: Tesseract OCR optimized for French and English text
- **VLM extraction**: Florence-2 Vision-Language Model for structured data extraction
- **Claude API fallback**: Optional external processing via Anthropic Claude for documents that cannot be processed locally
- **Invoice validation**: Automatic detection of invoice documents and VAT validation
- **Cross-platform**: Builds for Linux, macOS (ARM), and Windows

## Architecture

```
Invoicator (Tauri shell)
├── Frontend: Vue.js + TypeScript + Tailwind CSS
├── Rust layer: Backend lifecycle management, health checks
└── Backend: Python/FastAPI (bundled via PyInstaller)
    ├── Tesseract OCR (bundled)
    ├── Poppler (bundled)
    ├── Florence-2 (auto-downloaded on first run)
    └── SQLite database
```

In production, Tauri spawns the Python backend as a child process and monitors it via a `/health` endpoint. In development, the backend runs separately and the Vite dev server proxies API requests.

## Tech Stack

- **Desktop**: Tauri 2 (Rust)
- **Frontend**: Vue.js 3, TypeScript, Tailwind CSS
- **Backend**: Python, FastAPI, Uvicorn
- **Database**: SQLite
- **OCR**: Tesseract (French + English)
- **ML**: Florence-2 (local), Anthropic Claude API (optional fallback)
- **Packaging**: PyInstaller (backend), Tauri bundler (desktop)
- **CI/CD**: GitHub Actions (Linux, macOS ARM, Windows)

## Installation (End Users)

Download the latest installer from the
[Releases](https://github.com/IRClichtR/invoice_processor/releases) page:

- **Windows**: `.msi` installer
- **macOS**: `.dmg` disk image
- **Linux**: `.deb` package or `.AppImage`

All dependencies are bundled. No developer tools required.

> The Florence-2 ML model (~1.8 GB) downloads automatically on first use.

## Development Setup

### Prerequisites

- GNU Make (`make` — pre-installed on Linux/macOS; on Windows: `choco install make`)
- Python 3.11+
- Node.js (LTS)
- Rust (stable)

### Getting Started

1. Install system build dependencies:

```bash
make setup
```

2. Build the app:

```bash
make
```

### Running in Development

1. Start the backend:

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python run_server.py
```

2. In a separate terminal, start the Tauri dev app:

```bash
cd tauri-app
npm install
npm run tauri dev
```

The Vite dev server proxies `/api/*` requests to the backend at `localhost:8000`.

### Production Build

Build everything with Make:

```bash
make           # Full build: backend + Tauri app
```

Or run individual stages:

```bash
make setup             # Install system build dependencies
make vendor-deps       # Fetch platform vendor binaries
make backend           # Build backend with PyInstaller
make resources         # Copy backend into Tauri resources
make frontend-deps     # Install npm dependencies
make tauri             # Build the Tauri desktop app
make clean             # Remove all build artifacts
make help              # Show all targets
```

On Windows, install GNU Make via `choco install make`.

Installers are output to `tauri-app/src-tauri/target/release/bundle/`.

## CI/CD

The GitHub Actions workflow (`.github/workflows/build.yml`) builds for all three platforms on every push to `main` and on pull requests. The workflow delegates build steps to Makefile targets (`make resources frontend-deps`), then uses `tauri-action` for the final Tauri build with signing and bundling. A draft GitHub release can be created via manual workflow dispatch.

## API Endpoints

The backend exposes a REST API under `/api/v1`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/invoices/upload` | Upload a PDF/image for processing |
| `GET` | `/api/v1/invoices` | List all invoices |
| `GET` | `/api/v1/invoices/{id}` | Get invoice by ID |
| `DELETE` | `/api/v1/invoices/{id}` | Delete an invoice |
| `GET` | `/api/v1/other-documents` | List non-invoice documents |
| `GET` | `/health` | Basic health check |
| `GET` | `/health/detailed` | Detailed health check with component status |

When the backend is running, interactive API docs are available at `http://localhost:8000/docs`.

## Processing Pipeline

1. **PDF to images** -- Convert each page to 300 DPI images via Poppler
2. **Preprocessing** -- Deskew, CLAHE contrast enhancement, denoising, binarization
3. **OCR** -- Tesseract extracts text with word positions and confidence scores
4. **VLM extraction** -- Florence-2 performs structured data extraction (table detection, column identification, line items)
5. **Validation** -- Invoice detection, VAT calculation verification, line item sum check
6. **Storage** -- Invoices and line items stored in SQLite; non-invoice documents stored separately

## Database Schema

### Invoices

`id`, `provider`, `date`, `invoice_number`, `total_without_vat`, `total_with_vat`, `confidence_score`, `raw_vlm_json`, `raw_vlm_response`, `created_at`, `updated_at`

### Invoice Lines

`id`, `invoice_id` (FK), `designation`, `quantity`, `unit`, `unit_price`, `total_ht`

### Other Documents

`id`, `provider`, `raw_text`, `created_at`, `updated_at`

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | OS-specific | Base directory for database and uploads |
| `PORT` | `8000` | Backend server port |
| `HOST` | `127.0.0.1` | Backend bind address |
| `DEBUG` | `false` | Enable debug logging |
| `ANTHROPIC_API_KEY` | (none) | Claude API key for fallback processing |

## Troubleshooting

### Florence-2 model download

The Florence-2 model (~1.5 GB) downloads automatically on first run. Ensure you have internet connectivity and sufficient disk space.

### Low OCR confidence

- Check the source document quality
- Verify correct language settings (`fra+eng`)
- Adjust preprocessing parameters

### Memory

Florence-2 requires at least 4 GB RAM. If you encounter out-of-memory errors, ensure sufficient RAM is available.

## License

MIT

## TODOs

- Test Anthropic handwriting model for handwritten invoices
- Contact https://www.transkribus.org/ for handwritten invoice processing options
