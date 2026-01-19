# Database Migrations Guide

This project uses Alembic for managing database schema changes with SQLite.

## Common Migration Commands

All commands should be run inside the Docker container:

```bash
docker exec invoice_backend alembic <command>
```

### Check Current Migration Status

```bash
docker exec invoice_backend alembic current
```

### Create a New Migration

After modifying models in `app/models/`, generate a new migration:

```bash
docker exec invoice_backend alembic revision --autogenerate -m "description_of_changes"
```

This will:
- Compare your SQLAlchemy models with the current database schema
- Generate a migration file in `alembic/versions/`
- Detect added/removed columns, tables, indexes, etc.

### Apply Migrations

Apply all pending migrations:

```bash
docker exec invoice_backend alembic upgrade head
```

### Rollback Migrations

Rollback the last migration:

```bash
docker exec invoice_backend alembic downgrade -1
```

Rollback to a specific revision:

```bash
docker exec invoice_backend alembic downgrade <revision_id>
```

### View Migration History

```bash
docker exec invoice_backend alembic history
```

Show detailed history with verbose output:

```bash
docker exec invoice_backend alembic history --verbose
```

## Workflow for Schema Changes

1. **Modify your models** in `app/models/invoice.py` or other model files
2. **Generate migration**: `docker exec invoice_backend alembic revision --autogenerate -m "add_new_field"`
3. **Review the migration file** in `alembic/versions/` to ensure it's correct
4. **Apply the migration**: `docker exec invoice_backend alembic upgrade head`
5. **Test your changes** to ensure everything works as expected

## Important Notes

- Always review auto-generated migrations before applying them
- Alembic might not detect all changes (like changes to column types in some cases)
- For production deployments, run migrations before starting the application
- The database connection is configured in `alembic/env.py` using settings from `app/core/config.py`

## Initial Setup (Already Done)

The initial migration has been created and applied. The `alembic_version` table tracks which migrations have been applied.

Current schema includes:
- `invoices` - Invoice records with extracted data
- `invoice_lines` - Line items for each invoice
- `other_documents` - Non-invoice documents
- `analysis_jobs` - Two-step workflow job tracking
- `api_keys` - Encrypted API key storage

### Analysis Jobs Table

Stores analysis results between the `/analyze` and `/process` steps:

```sql
CREATE TABLE analysis_jobs (
    id VARCHAR(36) PRIMARY KEY,           -- UUID
    status VARCHAR(20) DEFAULT 'analyzed', -- analyzed, processing, completed, expired, failed
    original_filename VARCHAR(255),
    file_extension VARCHAR(10),
    page_count INTEGER DEFAULT 1,
    confidence_score FLOAT,
    is_handwritten BOOLEAN DEFAULT FALSE,
    is_low_quality BOOLEAN DEFAULT FALSE,
    suggested_pipeline VARCHAR(20),        -- florence, claude
    quality_classification VARCHAR(30),
    ocr_full_text TEXT,
    ocr_words_json JSON,
    ocr_spatial_grid TEXT,
    quality_details JSON,
    preprocessing_report JSON,
    created_at DATETIME,
    expires_at DATETIME,                   -- Job expiration (1 hour)
    completed_at DATETIME,
    result_invoice_id INTEGER REFERENCES invoices(id),
    result_document_id INTEGER REFERENCES other_documents(id),
    processing_method VARCHAR(20),
    processing_error TEXT
);
```

### API Keys Table

Stores encrypted API keys for external services:

```sql
CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY,
    provider VARCHAR(50) UNIQUE,           -- anthropic, openai, etc.
    encrypted_key TEXT NOT NULL,           -- Fernet encrypted
    key_prefix VARCHAR(20),                -- For identification (e.g., "sk-ant-...")
    is_valid BOOLEAN DEFAULT TRUE,
    validation_error VARCHAR(255),
    created_at DATETIME,
    updated_at DATETIME,
    last_validated_at DATETIME
);
```

## Troubleshooting

### Migration conflicts
If you have migration conflicts, you may need to merge branches:
```bash
docker exec invoice_backend alembic merge -m "merge migrations" <rev1> <rev2>
```

### Reset migrations (DESTRUCTIVE - only for development)
If you need to completely reset:
```bash
# Delete the SQLite database file (will lose all data!)
docker exec invoice_backend rm -f /app/invoice_db.sqlite
# Apply all migrations from scratch to create new database
docker exec invoice_backend alembic upgrade head
```
