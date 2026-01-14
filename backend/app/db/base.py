from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# SQLite-specific configuration
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db(reset: bool = False):
    """Create all tables if they don't exist. If reset=True, drop and recreate."""
    # Import models to ensure they're registered with Base
    from app.models.invoice import Invoice, InvoiceLine, OtherDocument
    if reset:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def clear_db():
    """Clear all data from all tables"""
    from app.models.invoice import Invoice, InvoiceLine, OtherDocument
    db = SessionLocal()
    try:
        db.query(InvoiceLine).delete()
        db.query(Invoice).delete()
        db.query(OtherDocument).delete()
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
