import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./invoice_db.sqlite"

    # Application settings
    APP_NAME: str = "Invoice Processor API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # File upload settings
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB

    # OCR settings - Optimized for French and English invoices
    TESSERACT_LANG: str = "fra+eng"  # French + English
    TESSERACT_CONFIG: str = "--psm 6 --oem 3"  # PSM 6: Uniform block of text, OEM 3: Default (LSTM)

    # Qwen2-VL model settings (CPU-only)
    QWEN_MODEL: str = "Qwen/Qwen2-VL-2B-Instruct"

    # Model cache directory (persistent on user machine)
    MODEL_CACHE_DIR: str = os.path.expanduser("~/.cache/invoice_processor/models")

    # Batch processing settings
    MAX_WORKERS: int = 4  # Maximum number of parallel threads for batch processing

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
