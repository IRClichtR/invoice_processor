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

    # Florence-2 model settings (CPU-only)
    FLORENCE_MODEL: str = "microsoft/Florence-2-base"

    # Model cache directory (persistent on user machine)
    MODEL_CACHE_DIR: str = os.path.expanduser("~/.cache/invoice_processor/models")

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
