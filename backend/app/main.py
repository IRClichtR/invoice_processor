from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.base import engine, Base
from app.api import invoices
from app.services.model_manager import initialize_models
import os

# Database tables are managed by Alembic migrations
# To create/update tables, run: alembic upgrade head
# Base.metadata.create_all(bind=engine)  # No longer used - use migrations instead

# Create upload directory
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

# Initialize models at startup (load once, not on every request)
@app.on_event("startup")
async def startup_event():
    initialize_models()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(invoices.router, prefix="/api/v1", tags=["invoices"])


@app.get("/")
async def root():
    return {"message": "Invoice Processor API", "version": settings.APP_VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
