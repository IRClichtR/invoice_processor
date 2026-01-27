# Copyright 2026 Floriane TUERNAL SABOTINOV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Get database URL as string (handles Path objects)
database_url = str(settings.DATABASE_URL)

# SQLite-specific configuration
connect_args = {}
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db(reset: bool = False):
    """Create all tables if they don't exist. If reset=True, drop and recreate."""
    # Import models to ensure they're registered with Base
    from app.models.invoice import Invoice, InvoiceLine, OtherDocument
    from app.models.analysis_job import AnalysisJob
    from app.models.api_key import ApiKey
    if reset:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def clear_db():
    """Clear all data from all tables"""
    from app.models.invoice import Invoice, InvoiceLine, OtherDocument
    from app.models.analysis_job import AnalysisJob
    from app.models.api_key import ApiKey
    db = SessionLocal()
    try:
        db.query(InvoiceLine).delete()
        db.query(Invoice).delete()
        db.query(OtherDocument).delete()
        db.query(AnalysisJob).delete()
        db.query(ApiKey).delete()
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
