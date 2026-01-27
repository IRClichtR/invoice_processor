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

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(255), nullable=False, index=True)
    date = Column(String(50), nullable=True)
    invoice_number = Column(String(100), nullable=True, index=True)
    total_without_vat = Column(Float, nullable=True)
    total_with_vat = Column(Float, nullable=True)
    currency = Column(String(3), nullable=False, default='XXX')  # ISO 4217 currency code
    confidence_score = Column(Float, nullable=True)
    original_filename = Column(String(255), nullable=True, index=True)
    document_path = Column(String(500), nullable=True)  # Path to permanently stored document
    raw_vlm_json = Column(JSON, nullable=True)
    raw_vlm_response = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    designation = Column(String(500), nullable=True)
    quantity = Column(Float, nullable=True)
    unit_price = Column(Float, nullable=True)
    total_ht = Column(Float, nullable=True)

    # Relationships
    invoice = relationship("Invoice", back_populates="lines")


class OtherDocument(Base):
    __tablename__ = "other_documents"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(255), nullable=True, index=True)
    original_filename = Column(String(255), nullable=True, index=True)
    raw_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
