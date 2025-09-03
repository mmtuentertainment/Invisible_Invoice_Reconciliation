"""
SQLAlchemy models for financial data - invoices, purchase orders, receipts, and matching system.
Implements SOX-compliant audit trails and multi-tenant row-level security.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4
from enum import Enum

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String, Text, Numeric,
    ForeignKey, Index, CheckConstraint, UniqueConstraint, 
    ARRAY, JSON, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.auth import Base


class DocumentStatus(str, Enum):
    """Document processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    EXCEPTION = "exception"
    ARCHIVED = "archived"


class MatchType(str, Enum):
    """Types of matching performed."""
    EXACT = "exact"
    FUZZY = "fuzzy"
    MANUAL = "manual"
    PARTIAL = "partial"


class MatchStatus(str, Enum):
    """Match decision status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MANUAL_REVIEW = "manual_review"


class CurrencyCode(str, Enum):
    """Supported currency codes."""
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CAD = "CAD"
    AUD = "AUD"


class Tenant(Base):
    """Multi-tenant organization model."""
    
    __tablename__ = "tenants"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Configuration
    settings: Mapped[dict] = mapped_column(JSON, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint("name"),
        Index("idx_tenants_name", "name"),
        Index("idx_tenants_active", "is_active"),
    )


class Vendor(Base):
    """Vendor/supplier master data."""
    
    __tablename__ = "vendors"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    
    # Vendor information
    vendor_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[Optional[str]] = mapped_column(String(255))
    tax_id: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Contact information
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    address: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Financial settings
    default_currency: Mapped[str] = mapped_column(SQLEnum(CurrencyCode), default=CurrencyCode.USD)
    payment_terms_days: Mapped[int] = mapped_column(Integer, server_default="30")
    
    # Status and settings
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    settings: Mapped[dict] = mapped_column(JSON, server_default="{}")
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    updated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    invoices: Mapped[List["Invoice"]] = relationship("Invoice", back_populates="vendor")
    purchase_orders: Mapped[List["PurchaseOrder"]] = relationship("PurchaseOrder", back_populates="vendor")
    vendor_aliases: Mapped[List["VendorAlias"]] = relationship("VendorAlias", back_populates="vendor")
    
    __table_args__ = (
        UniqueConstraint("tenant_id", "vendor_code"),
        Index("idx_vendors_tenant", "tenant_id"),
        Index("idx_vendors_code", "tenant_id", "vendor_code"),
        Index("idx_vendors_name", "name"),
        Index("idx_vendors_active", "is_active"),
    )


class VendorAlias(Base):
    """Vendor name variations for fuzzy matching."""
    
    __tablename__ = "vendor_aliases"
    
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    vendor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    
    # Alias information
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    similarity_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, server_default="false")
    
    # Source tracking
    source: Mapped[str] = mapped_column(String(50), server_default="manual")  # manual, ocr, learning
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0.0")
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="vendor_aliases")
    
    __table_args__ = (
        UniqueConstraint("tenant_id", "vendor_id", "alias"),
        CheckConstraint("similarity_score >= 0.0 AND similarity_score <= 1.0"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0"),
        Index("idx_vendor_aliases_tenant", "tenant_id"),
        Index("idx_vendor_aliases_vendor", "vendor_id"),
        Index("idx_vendor_aliases_alias", "alias"),
        Index("idx_vendor_aliases_score", "similarity_score"),
        Index("idx_vendor_aliases_approved", "approved"),
    )


class PurchaseOrder(Base):
    """Purchase Order master data."""
    
    __tablename__ = "purchase_orders"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    vendor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    
    # PO identification
    po_number: Mapped[str] = mapped_column(String(50), nullable=False)
    external_po_number: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Financial details
    currency: Mapped[str] = mapped_column(SQLEnum(CurrencyCode), default=CurrencyCode.USD)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), server_default="0.00")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    
    # Dates
    po_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_delivery_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Status and workflow
    status: Mapped[str] = mapped_column(SQLEnum(DocumentStatus), default=DocumentStatus.PENDING)
    approval_status: Mapped[str] = mapped_column(String(20), server_default="pending")
    
    # Additional information
    description: Mapped[Optional[str]] = mapped_column(Text)
    buyer_notes: Mapped[Optional[str]] = mapped_column(Text)
    delivery_address: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="purchase_orders")
    po_lines: Mapped[List["PurchaseOrderLine"]] = relationship("PurchaseOrderLine", back_populates="purchase_order")
    receipts: Mapped[List["Receipt"]] = relationship("Receipt", back_populates="purchase_order")
    match_results: Mapped[List["MatchResult"]] = relationship("MatchResult", back_populates="purchase_order")
    
    __table_args__ = (
        UniqueConstraint("tenant_id", "po_number"),
        CheckConstraint("subtotal >= 0"),
        CheckConstraint("tax_amount >= 0"),
        CheckConstraint("total_amount >= 0"),
        CheckConstraint("total_amount >= subtotal"),
        Index("idx_purchase_orders_tenant", "tenant_id"),
        Index("idx_purchase_orders_vendor", "vendor_id"),
        Index("idx_purchase_orders_number", "tenant_id", "po_number"),
        Index("idx_purchase_orders_date", "po_date"),
        Index("idx_purchase_orders_status", "status"),
        Index("idx_purchase_orders_amount", "total_amount"),
    )


class PurchaseOrderLine(Base):
    """Purchase Order line items."""
    
    __tablename__ = "purchase_order_lines"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    purchase_order_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False)
    
    # Line details
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code: Mapped[Optional[str]] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Quantity and pricing
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    
    # Units
    unit_of_measure: Mapped[str] = mapped_column(String(10), server_default="EA")
    
    # Delivery tracking
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(15, 4), server_default="0")
    quantity_invoiced: Mapped[Decimal] = mapped_column(Numeric(15, 4), server_default="0")
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="po_lines")
    
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "line_number"),
        CheckConstraint("quantity > 0"),
        CheckConstraint("unit_price >= 0"),
        CheckConstraint("line_total >= 0"),
        CheckConstraint("quantity_received >= 0"),
        CheckConstraint("quantity_invoiced >= 0"),
        CheckConstraint("quantity_received <= quantity"),
        CheckConstraint("quantity_invoiced <= quantity"),
        Index("idx_po_lines_tenant", "tenant_id"),
        Index("idx_po_lines_po", "purchase_order_id"),
        Index("idx_po_lines_item", "item_code"),
    )


class Invoice(Base):
    """Invoice document data."""
    
    __tablename__ = "invoices"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    vendor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    
    # Invoice identification
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    po_reference: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Financial details
    currency: Mapped[str] = mapped_column(SQLEnum(CurrencyCode), default=CurrencyCode.USD)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), server_default="0.00")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    
    # Dates
    invoice_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    received_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # Document processing
    status: Mapped[str] = mapped_column(SQLEnum(DocumentStatus), default=DocumentStatus.PENDING)
    processing_status: Mapped[str] = mapped_column(String(50), server_default="uploaded")
    
    # OCR and extraction data
    ocr_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    extracted_data: Mapped[Optional[dict]] = mapped_column(JSON)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    
    # File information
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="invoices")
    invoice_lines: Mapped[List["InvoiceLine"]] = relationship("InvoiceLine", back_populates="invoice")
    match_results: Mapped[List["MatchResult"]] = relationship("MatchResult", back_populates="invoice")
    
    __table_args__ = (
        UniqueConstraint("tenant_id", "vendor_id", "invoice_number"),
        CheckConstraint("subtotal >= 0"),
        CheckConstraint("tax_amount >= 0"),
        CheckConstraint("total_amount >= 0"),
        CheckConstraint("total_amount >= subtotal"),
        CheckConstraint("file_size > 0"),
        CheckConstraint("ocr_confidence IS NULL OR (ocr_confidence >= 0.0 AND ocr_confidence <= 1.0)"),
        Index("idx_invoices_tenant", "tenant_id"),
        Index("idx_invoices_vendor", "vendor_id"),
        Index("idx_invoices_number", "tenant_id", "invoice_number"),
        Index("idx_invoices_po_ref", "po_reference"),
        Index("idx_invoices_date", "invoice_date"),
        Index("idx_invoices_status", "status"),
        Index("idx_invoices_amount", "total_amount"),
        Index("idx_invoices_hash", "file_hash"),
    )


class InvoiceLine(Base):
    """Invoice line items."""
    
    __tablename__ = "invoice_lines"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    invoice_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    
    # Line details
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code: Mapped[Optional[str]] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Quantity and pricing
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    
    # Units
    unit_of_measure: Mapped[str] = mapped_column(String(10), server_default="EA")
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="invoice_lines")
    
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_number"),
        CheckConstraint("quantity > 0"),
        CheckConstraint("unit_price >= 0"),
        CheckConstraint("line_total >= 0"),
        Index("idx_invoice_lines_tenant", "tenant_id"),
        Index("idx_invoice_lines_invoice", "invoice_id"),
        Index("idx_invoice_lines_item", "item_code"),
    )


class Receipt(Base):
    """Goods receipt document data."""
    
    __tablename__ = "receipts"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    purchase_order_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False)
    
    # Receipt identification
    receipt_number: Mapped[str] = mapped_column(String(50), nullable=False)
    delivery_note: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Receipt details
    receipt_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_by: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Financial totals
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    
    # Status
    status: Mapped[str] = mapped_column(SQLEnum(DocumentStatus), default=DocumentStatus.PENDING)
    
    # Additional information
    notes: Mapped[Optional[str]] = mapped_column(Text)
    delivery_conditions: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="receipts")
    receipt_lines: Mapped[List["ReceiptLine"]] = relationship("ReceiptLine", back_populates="receipt")
    match_results: Mapped[List["MatchResult"]] = relationship("MatchResult", back_populates="receipt")
    
    __table_args__ = (
        UniqueConstraint("tenant_id", "receipt_number"),
        CheckConstraint("total_quantity >= 0"),
        CheckConstraint("total_value >= 0"),
        Index("idx_receipts_tenant", "tenant_id"),
        Index("idx_receipts_po", "purchase_order_id"),
        Index("idx_receipts_number", "tenant_id", "receipt_number"),
        Index("idx_receipts_date", "receipt_date"),
        Index("idx_receipts_status", "status"),
    )


class ReceiptLine(Base):
    """Receipt line items."""
    
    __tablename__ = "receipt_lines"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    receipt_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("receipts.id"), nullable=False)
    po_line_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("purchase_order_lines.id"), nullable=False)
    
    # Line details
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    line_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    
    # Quality information
    condition: Mapped[str] = mapped_column(String(20), server_default="good")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    receipt: Mapped["Receipt"] = relationship("Receipt", back_populates="receipt_lines")
    
    __table_args__ = (
        UniqueConstraint("receipt_id", "line_number"),
        CheckConstraint("quantity_received > 0"),
        CheckConstraint("unit_cost >= 0"),
        CheckConstraint("line_value >= 0"),
        CheckConstraint("condition IN ('good', 'damaged', 'rejected')"),
        Index("idx_receipt_lines_tenant", "tenant_id"),
        Index("idx_receipt_lines_receipt", "receipt_id"),
        Index("idx_receipt_lines_po_line", "po_line_id"),
    )


class MatchingTolerance(Base):
    """Configurable matching tolerances per tenant and vendor."""
    
    __tablename__ = "matching_tolerances"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    
    # Tolerance scope
    vendor_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("vendors.id"))
    amount_threshold: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))  # Apply to invoices above this amount
    
    # Tolerance types and values
    tolerance_type: Mapped[str] = mapped_column(String(20), nullable=False)  # price, quantity, date
    percentage_tolerance: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    absolute_tolerance: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 4))
    
    # Additional settings
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    priority: Mapped[int] = mapped_column(Integer, server_default="1")  # Higher number = higher priority
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    __table_args__ = (
        CheckConstraint("tolerance_type IN ('price', 'quantity', 'date')"),
        CheckConstraint("percentage_tolerance IS NULL OR (percentage_tolerance >= 0.0 AND percentage_tolerance <= 1.0)"),
        CheckConstraint("absolute_tolerance IS NULL OR absolute_tolerance >= 0"),
        CheckConstraint("percentage_tolerance IS NOT NULL OR absolute_tolerance IS NOT NULL"),
        CheckConstraint("priority >= 1 AND priority <= 10"),
        Index("idx_matching_tolerances_tenant", "tenant_id"),
        Index("idx_matching_tolerances_vendor", "vendor_id"),
        Index("idx_matching_tolerances_type", "tolerance_type"),
        Index("idx_matching_tolerances_active", "is_active"),
        Index("idx_matching_tolerances_priority", "priority"),
    )


class MatchResult(Base):
    """Results of the matching process with audit trail."""
    
    __tablename__ = "match_results"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    
    # Document relationships
    invoice_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    purchase_order_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("purchase_orders.id"))
    receipt_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("receipts.id"))
    
    # Match details
    match_type: Mapped[str] = mapped_column(SQLEnum(MatchType), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    match_status: Mapped[str] = mapped_column(SQLEnum(MatchStatus), default=MatchStatus.PENDING)
    
    # Match criteria met
    criteria_met: Mapped[dict] = mapped_column(JSON, nullable=False)  # Which criteria passed/failed
    tolerance_applied: Mapped[Optional[dict]] = mapped_column(JSON)  # Tolerances used
    
    # Decision details
    auto_approved: Mapped[bool] = mapped_column(Boolean, server_default="false")
    requires_review: Mapped[bool] = mapped_column(Boolean, server_default="false")
    review_notes: Mapped[Optional[str]] = mapped_column(Text)
    
    # Financial variance
    amount_variance: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))
    quantity_variance: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 4))
    
    # Timing
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # User involvement
    matched_by: Mapped[str] = mapped_column(String(20), server_default="system")  # system, user
    reviewed_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    approved_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="match_results")
    purchase_order: Mapped[Optional["PurchaseOrder"]] = relationship("PurchaseOrder", back_populates="match_results")
    receipt: Mapped[Optional["Receipt"]] = relationship("Receipt", back_populates="match_results")
    match_audit_logs: Mapped[List["MatchAuditLog"]] = relationship("MatchAuditLog", back_populates="match_result")
    
    __table_args__ = (
        CheckConstraint("confidence_score >= 0.0 AND confidence_score <= 1.0"),
        CheckConstraint("matched_by IN ('system', 'user')"),
        CheckConstraint("(match_status = 'approved') = (approved_at IS NOT NULL)"),
        CheckConstraint("(requires_review = true) OR (reviewed_at IS NULL)"),
        Index("idx_match_results_tenant", "tenant_id"),
        Index("idx_match_results_invoice", "invoice_id"),
        Index("idx_match_results_po", "purchase_order_id"),
        Index("idx_match_results_receipt", "receipt_id"),
        Index("idx_match_results_status", "match_status"),
        Index("idx_match_results_confidence", "confidence_score"),
        Index("idx_match_results_matched_at", "matched_at"),
        Index("idx_match_results_auto_approved", "auto_approved"),
        Index("idx_match_results_requires_review", "requires_review"),
    )


class MatchAuditLog(Base):
    """SOX-compliant audit log for all matching decisions and changes."""
    
    __tablename__ = "match_audit_log"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    match_result_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("match_results.id"), nullable=False)
    
    # Event details
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Decision context
    decision_factors: Mapped[dict] = mapped_column(JSON, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)
    
    # Changes made (if applicable)
    old_values: Mapped[Optional[dict]] = mapped_column(JSON)
    new_values: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # User context
    user_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    user_role: Mapped[Optional[str]] = mapped_column(String(50))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    
    # Timing and immutability
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 hash for integrity
    
    # Relationships
    match_result: Mapped["MatchResult"] = relationship("MatchResult", back_populates="match_audit_logs")
    
    __table_args__ = (
        CheckConstraint("event_type IN ('match_created', 'match_updated', 'status_changed', "
                       "'confidence_updated', 'manual_review', 'approval_granted', 'approval_denied', "
                       "'tolerance_applied', 'exception_created', 'user_feedback')"),
        Index("idx_match_audit_tenant", "tenant_id"),
        Index("idx_match_audit_match", "match_result_id"),
        Index("idx_match_audit_type", "event_type"),
        Index("idx_match_audit_time", "occurred_at"),
        Index("idx_match_audit_user", "user_id"),
        Index("idx_match_audit_hash", "event_hash"),
    )


class ImportBatchStatus(str, Enum):
    """Import batch processing status."""
    PENDING = "pending"
    UPLOADING = "uploading"  
    VALIDATING = "validating"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImportBatch(Base):
    """Import batch tracking for file uploads."""
    
    __tablename__ = "import_batches"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    
    # File information
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    
    # Processing status
    status: Mapped[str] = mapped_column(SQLEnum(ImportBatchStatus), default=ImportBatchStatus.PENDING)
    processing_stage: Mapped[Optional[str]] = mapped_column(String(50))
    progress_percentage: Mapped[int] = mapped_column(Integer, server_default="0")
    
    # Record counts
    total_records: Mapped[int] = mapped_column(Integer, server_default="0")
    processed_records: Mapped[int] = mapped_column(Integer, server_default="0")
    successful_records: Mapped[int] = mapped_column(Integer, server_default="0")
    error_records: Mapped[int] = mapped_column(Integer, server_default="0")
    duplicate_records: Mapped[int] = mapped_column(Integer, server_default="0")
    
    # Processing configuration
    csv_delimiter: Mapped[str] = mapped_column(String(1), server_default=",")
    csv_encoding: Mapped[str] = mapped_column(String(20), server_default="utf-8")
    has_header: Mapped[bool] = mapped_column(Boolean, server_default="true")
    column_mapping: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Processing times
    upload_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    upload_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Results and metadata
    processing_summary: Mapped[Optional[dict]] = mapped_column(JSON)
    error_summary: Mapped[Optional[dict]] = mapped_column(JSON)
    preview_data: Mapped[Optional[dict]] = mapped_column(JSON)  # First 10 rows
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    import_errors: Mapped[List["ImportError"]] = relationship("ImportError", back_populates="import_batch")
    
    __table_args__ = (
        CheckConstraint("file_size > 0"),
        CheckConstraint("progress_percentage >= 0 AND progress_percentage <= 100"),
        CheckConstraint("total_records >= 0"),
        CheckConstraint("processed_records >= 0"),
        CheckConstraint("successful_records >= 0"),
        CheckConstraint("error_records >= 0"),
        CheckConstraint("duplicate_records >= 0"),
        CheckConstraint("processed_records <= total_records"),
        CheckConstraint("successful_records + error_records + duplicate_records <= total_records"),
        CheckConstraint("csv_delimiter IN (',', '\t', '|', ';')"),
        CheckConstraint("csv_encoding IN ('utf-8', 'utf-16', 'ascii', 'iso-8859-1')"),
        Index("idx_import_batches_tenant", "tenant_id"),
        Index("idx_import_batches_status", "status"),
        Index("idx_import_batches_created", "created_at"),
        Index("idx_import_batches_filename", "filename"),
        Index("idx_import_batches_hash", "file_hash"),
    )


class ImportErrorType(str, Enum):
    """Types of import errors."""
    VALIDATION = "validation"
    PARSING = "parsing"
    BUSINESS_RULE = "business_rule"
    DUPLICATE = "duplicate"
    SYSTEM = "system"


class ImportError(Base):
    """Detailed error tracking for import failures."""
    
    __tablename__ = "import_errors"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    import_batch_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=False)
    
    # Error location
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    column_name: Mapped[Optional[str]] = mapped_column(String(100))
    column_index: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Error details
    error_type: Mapped[str] = mapped_column(SQLEnum(ImportErrorType), nullable=False)
    error_code: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), server_default="error")  # error, warning
    
    # Data context
    raw_value: Mapped[Optional[str]] = mapped_column(Text)
    expected_format: Mapped[Optional[str]] = mapped_column(String(100))
    suggested_fix: Mapped[Optional[str]] = mapped_column(Text)
    raw_row_data: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Resolution tracking
    is_resolved: Mapped[bool] = mapped_column(Boolean, server_default="false")
    resolution_action: Mapped[Optional[str]] = mapped_column(String(100))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    import_batch: Mapped["ImportBatch"] = relationship("ImportBatch", back_populates="import_errors")
    
    __table_args__ = (
        CheckConstraint("row_number > 0"),
        CheckConstraint("column_index IS NULL OR column_index >= 0"),
        CheckConstraint("severity IN ('error', 'warning')"),
        Index("idx_import_errors_tenant", "tenant_id"),
        Index("idx_import_errors_batch", "import_batch_id"),
        Index("idx_import_errors_row", "row_number"),
        Index("idx_import_errors_type", "error_type"),
        Index("idx_import_errors_severity", "severity"),
        Index("idx_import_errors_resolved", "is_resolved"),
    )


class MatchingConfiguration(Base):
    """Global matching configuration per tenant."""
    
    __tablename__ = "matching_configuration"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    
    # Confidence thresholds
    auto_approve_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0.85")
    manual_review_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0.70")
    rejection_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0.30")
    
    # Algorithm settings
    fuzzy_matching_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    phonetic_matching_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    ocr_correction_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    
    # Matching weights (sum must equal 1.0)
    vendor_name_weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0.30")
    amount_weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0.40")
    date_weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0.20")
    reference_weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0.10")
    
    # Performance settings
    batch_size: Mapped[int] = mapped_column(Integer, server_default="100")
    parallel_processing_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, server_default="4")
    
    # Date range matching
    default_date_range_days: Mapped[int] = mapped_column(Integer, server_default="7")
    max_date_range_days: Mapped[int] = mapped_column(Integer, server_default="30")
    
    # Learning and feedback
    machine_learning_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    feedback_learning_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    
    # Version and activation
    config_version: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    __table_args__ = (
        UniqueConstraint("tenant_id", "config_version"),
        CheckConstraint("auto_approve_threshold >= 0.0 AND auto_approve_threshold <= 1.0"),
        CheckConstraint("manual_review_threshold >= 0.0 AND manual_review_threshold <= 1.0"),
        CheckConstraint("rejection_threshold >= 0.0 AND rejection_threshold <= 1.0"),
        CheckConstraint("auto_approve_threshold >= manual_review_threshold"),
        CheckConstraint("manual_review_threshold >= rejection_threshold"),
        CheckConstraint("vendor_name_weight + amount_weight + date_weight + reference_weight = 1.0"),
        CheckConstraint("batch_size > 0 AND batch_size <= 1000"),
        CheckConstraint("max_concurrent_jobs > 0 AND max_concurrent_jobs <= 20"),
        CheckConstraint("default_date_range_days > 0 AND default_date_range_days <= max_date_range_days"),
        CheckConstraint("max_date_range_days > 0 AND max_date_range_days <= 365"),
        Index("idx_matching_config_tenant", "tenant_id"),
        Index("idx_matching_config_active", "is_active"),
        Index("idx_matching_config_version", "tenant_id", "config_version"),
    )