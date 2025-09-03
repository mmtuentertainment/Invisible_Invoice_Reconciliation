"""
Pydantic schemas for matching engine API endpoints.

Provides request/response models for invoice matching operations with
validation, documentation, and type safety.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any, Union
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, validator, root_validator
from pydantic.types import PositiveInt, NonNegativeFloat, PositiveFloat


class MatchTypeResponse(str, Enum):
    """Match type enumeration for API responses."""
    EXACT = "exact"
    FUZZY = "fuzzy"
    MANUAL = "manual"
    PARTIAL = "partial"


class MatchStatusResponse(str, Enum):
    """Match status enumeration for API responses."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MANUAL_REVIEW = "manual_review"


class ThreeWayMatchTypeResponse(str, Enum):
    """3-way match type enumeration."""
    PERFECT_MATCH = "perfect_match"
    PARTIAL_RECEIPT = "partial_receipt"
    SPLIT_DELIVERY = "split_delivery"
    OVER_DELIVERY = "over_delivery"
    UNDER_DELIVERY = "under_delivery"
    PRICE_VARIANCE = "price_variance"
    QUANTITY_VARIANCE = "quantity_variance"


# Request Schemas

class MatchInvoiceRequest(BaseModel):
    """Request to match a single invoice."""
    invoice_id: UUID = Field(..., description="Invoice ID to match")
    force_rematch: bool = Field(False, description="Force re-matching even if already matched")
    three_way_matching: bool = Field(True, description="Enable 3-way matching with receipts")
    
    class Config:
        schema_extra = {
            "example": {
                "invoice_id": "123e4567-e89b-12d3-a456-426614174000",
                "force_rematch": False,
                "three_way_matching": True
            }
        }


class BatchMatchRequest(BaseModel):
    """Request to match a batch of invoices."""
    invoice_ids: List[UUID] = Field(..., min_items=1, max_items=500, description="List of invoice IDs to match")
    parallel_processing: bool = Field(True, description="Enable parallel processing for better performance")
    three_way_matching: bool = Field(True, description="Enable 3-way matching with receipts")
    
    @validator('invoice_ids')
    def validate_unique_invoices(cls, v):
        if len(v) != len(set(v)):
            raise ValueError('Duplicate invoice IDs are not allowed')
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "invoice_ids": [
                    "123e4567-e89b-12d3-a456-426614174000",
                    "456e7890-e89b-12d3-a456-426614174001"
                ],
                "parallel_processing": True,
                "three_way_matching": True
            }
        }


class UserFeedbackRequest(BaseModel):
    """User feedback on a match result."""
    match_result_id: UUID = Field(..., description="Match result ID")
    feedback_type: str = Field(..., description="Type of feedback", regex="^(approve|reject|modify)$")
    notes: Optional[str] = Field(None, max_length=1000, description="Optional feedback notes")
    confidence_override: Optional[Decimal] = Field(None, ge=0.0, le=1.0, description="Override confidence score")
    
    class Config:
        schema_extra = {
            "example": {
                "match_result_id": "789e0123-e89b-12d3-a456-426614174002",
                "feedback_type": "approve",
                "notes": "Confirmed with vendor - invoice amount is correct",
                "confidence_override": None
            }
        }


class ToleranceUpdateRequest(BaseModel):
    """Request to update matching tolerances."""
    tolerance_type: str = Field(..., description="Type of tolerance", regex="^(price|quantity|date)$")
    percentage_tolerance: Optional[Decimal] = Field(None, ge=0.0, le=1.0, description="Percentage tolerance (0.0-1.0)")
    absolute_tolerance: Optional[Decimal] = Field(None, ge=0, description="Absolute tolerance value")
    vendor_id: Optional[UUID] = Field(None, description="Vendor-specific override (optional)")
    amount_threshold: Optional[Decimal] = Field(None, ge=0, description="Apply to invoices above this amount")
    
    @root_validator
    def validate_tolerance_values(cls, values):
        percentage = values.get('percentage_tolerance')
        absolute = values.get('absolute_tolerance')
        if percentage is None and absolute is None:
            raise ValueError('Either percentage_tolerance or absolute_tolerance must be provided')
        return values
    
    class Config:
        schema_extra = {
            "example": {
                "tolerance_type": "price",
                "percentage_tolerance": 0.05,
                "absolute_tolerance": 10.00,
                "vendor_id": None,
                "amount_threshold": 1000.00
            }
        }


# Response Schemas

class VarianceDetail(BaseModel):
    """Detailed variance information."""
    amount_variance: Optional[Decimal] = Field(None, description="Amount variance as decimal")
    amount_variance_percentage: Optional[float] = Field(None, description="Amount variance as percentage")
    quantity_variance: Optional[Decimal] = Field(None, description="Quantity variance as decimal")
    quantity_variance_percentage: Optional[float] = Field(None, description="Quantity variance as percentage")
    date_variance_days: Optional[int] = Field(None, description="Date variance in days")


class MatchFactors(BaseModel):
    """Detailed match factors and scoring breakdown."""
    vendor_similarity: float = Field(..., ge=0.0, le=1.0, description="Vendor name similarity score")
    amount_within_tolerance: bool = Field(..., description="Whether amount is within tolerance")
    quantity_within_tolerance: Optional[bool] = Field(None, description="Whether quantity is within tolerance")
    date_within_tolerance: bool = Field(..., description="Whether date is within tolerance")
    reference_exact_match: bool = Field(..., description="Whether reference numbers match exactly")
    reference_similarity: float = Field(..., ge=0.0, le=1.0, description="Reference similarity score")
    
    # Weighted scoring breakdown
    vendor_score: float = Field(..., ge=0.0, le=1.0, description="Weighted vendor matching score")
    amount_score: float = Field(..., ge=0.0, le=1.0, description="Weighted amount matching score")
    date_score: float = Field(..., ge=0.0, le=1.0, description="Weighted date matching score")
    reference_score: float = Field(..., ge=0.0, le=1.0, description="Weighted reference matching score")


class MatchResultResponse(BaseModel):
    """Single match result response."""
    match_result_id: UUID = Field(..., description="Unique match result ID")
    invoice_id: UUID = Field(..., description="Matched invoice ID")
    purchase_order_id: Optional[UUID] = Field(None, description="Matched purchase order ID")
    receipt_id: Optional[UUID] = Field(None, description="Matched receipt ID")
    
    # Match details
    match_type: MatchTypeResponse = Field(..., description="Type of match performed")
    confidence_score: Decimal = Field(..., ge=0.0, le=1.0, description="Match confidence score")
    match_status: MatchStatusResponse = Field(..., description="Current match status")
    
    # Decision flags
    auto_approved: bool = Field(..., description="Whether match was automatically approved")
    requires_review: bool = Field(..., description="Whether match requires manual review")
    
    # Detailed information
    match_factors: MatchFactors = Field(..., description="Detailed match factors")
    variance_details: VarianceDetail = Field(..., description="Variance analysis details")
    explanation: str = Field(..., description="Human-readable match explanation")
    
    # Timestamps
    matched_at: datetime = Field(..., description="When match was created")
    reviewed_at: Optional[datetime] = Field(None, description="When match was reviewed")
    approved_at: Optional[datetime] = Field(None, description="When match was approved")
    
    class Config:
        schema_extra = {
            "example": {
                "match_result_id": "789e0123-e89b-12d3-a456-426614174002",
                "invoice_id": "123e4567-e89b-12d3-a456-426614174000",
                "purchase_order_id": "456e7890-e89b-12d3-a456-426614174001",
                "receipt_id": "321e6547-e89b-12d3-a456-426614174003",
                "match_type": "exact",
                "confidence_score": 0.98,
                "match_status": "approved",
                "auto_approved": True,
                "requires_review": False,
                "explanation": "Exact match found on PO number, vendor, and amount",
                "matched_at": "2025-01-03T12:00:00Z"
            }
        }


class LineItemMatchResponse(BaseModel):
    """Line-level match details for 3-way matching."""
    po_line_id: Optional[UUID] = Field(None, description="Matched PO line ID")
    invoice_line_id: Optional[UUID] = Field(None, description="Invoice line ID")
    receipt_line_id: Optional[UUID] = Field(None, description="Matched receipt line ID")
    
    # Quantities
    po_quantity: Optional[Decimal] = Field(None, description="PO line quantity")
    invoice_quantity: Optional[Decimal] = Field(None, description="Invoice line quantity")
    receipt_quantity: Optional[Decimal] = Field(None, description="Receipt line quantity")
    
    # Amounts
    po_amount: Optional[Decimal] = Field(None, description="PO line amount")
    invoice_amount: Optional[Decimal] = Field(None, description="Invoice line amount")
    receipt_amount: Optional[Decimal] = Field(None, description="Receipt line amount")
    
    # Variance analysis
    quantity_variance: Decimal = Field(..., description="Quantity variance percentage")
    amount_variance: Decimal = Field(..., description="Amount variance percentage")
    
    # Match status
    is_matched: bool = Field(..., description="Whether line was successfully matched")
    variance_within_tolerance: bool = Field(..., description="Whether variances are within tolerance")
    match_confidence: Decimal = Field(..., ge=0.0, le=1.0, description="Line-level match confidence")
    variance_explanation: str = Field(..., description="Explanation of any variances")


class ThreeWayMatchResponse(BaseModel):
    """Complete 3-way matching result."""
    invoice_id: UUID = Field(..., description="Matched invoice ID")
    po_id: Optional[UUID] = Field(None, description="Matched purchase order ID")
    receipt_ids: List[UUID] = Field(default_factory=list, description="List of matched receipt IDs")
    
    # Match classification
    match_type: ThreeWayMatchTypeResponse = Field(..., description="Type of 3-way match")
    overall_confidence: Decimal = Field(..., ge=0.0, le=1.0, description="Overall match confidence")
    
    # Line-level details
    line_matches: List[LineItemMatchResponse] = Field(..., description="Line-level match details")
    
    # Financial summary
    total_po_amount: Decimal = Field(..., description="Total PO amount")
    total_invoice_amount: Decimal = Field(..., description="Total invoice amount")
    total_receipt_amount: Decimal = Field(..., description="Total receipt amount")
    net_amount_variance: Decimal = Field(..., description="Net amount variance")
    
    total_po_quantity: Decimal = Field(..., description="Total PO quantity")
    total_invoice_quantity: Decimal = Field(..., description="Total invoice quantity")
    total_receipt_quantity: Decimal = Field(..., description="Total receipt quantity")
    net_quantity_variance: Decimal = Field(..., description="Net quantity variance")
    
    # Tolerance status
    amount_within_tolerance: bool = Field(..., description="Whether amount variance is within tolerance")
    quantity_within_tolerance: bool = Field(..., description="Whether quantity variance is within tolerance")
    
    # Decision flags
    auto_approved: bool = Field(..., description="Whether match was automatically approved")
    requires_review: bool = Field(..., description="Whether match requires manual review")
    exception_items: List[str] = Field(default_factory=list, description="List of exceptions requiring attention")
    
    # Processing information
    processed_at: datetime = Field(..., description="When 3-way match was processed")
    matching_algorithm_version: str = Field(..., description="Version of matching algorithm used")


class BatchMatchResponse(BaseModel):
    """Response for batch matching operation."""
    batch_id: str = Field(..., description="Unique batch processing ID")
    total_invoices: PositiveInt = Field(..., description="Total number of invoices processed")
    
    # Processing statistics
    exact_matches: int = Field(..., ge=0, description="Number of exact matches found")
    fuzzy_matches: int = Field(..., ge=0, description="Number of fuzzy matches found")
    three_way_matches: int = Field(..., ge=0, description="Number of 3-way matches found")
    unmatched: int = Field(..., ge=0, description="Number of unmatched invoices")
    
    # Approval statistics
    auto_approved: int = Field(..., ge=0, description="Number of automatically approved matches")
    manual_review: int = Field(..., ge=0, description="Number requiring manual review")
    exceptions: int = Field(..., ge=0, description="Number of exceptions")
    
    # Performance metrics
    processing_time_seconds: PositiveFloat = Field(..., description="Total processing time in seconds")
    average_confidence: Decimal = Field(..., ge=0.0, le=1.0, description="Average confidence score")
    
    # Individual results
    match_results: List[MatchResultResponse] = Field(..., description="Individual match results")
    
    # Processing timestamps
    started_at: datetime = Field(..., description="When batch processing started")
    completed_at: datetime = Field(..., description="When batch processing completed")
    
    class Config:
        schema_extra = {
            "example": {
                "batch_id": "batch_20250103_120000_abc123",
                "total_invoices": 50,
                "exact_matches": 35,
                "fuzzy_matches": 10,
                "three_way_matches": 45,
                "unmatched": 5,
                "auto_approved": 40,
                "manual_review": 5,
                "exceptions": 0,
                "processing_time_seconds": 12.5,
                "average_confidence": 0.87,
                "started_at": "2025-01-03T12:00:00Z",
                "completed_at": "2025-01-03T12:00:12Z"
            }
        }


class ToleranceConfigResponse(BaseModel):
    """Current tolerance configuration."""
    tolerance_id: UUID = Field(..., description="Tolerance configuration ID")
    tolerance_type: str = Field(..., description="Type of tolerance")
    percentage_tolerance: Optional[Decimal] = Field(None, description="Percentage tolerance")
    absolute_tolerance: Optional[Decimal] = Field(None, description="Absolute tolerance")
    vendor_id: Optional[UUID] = Field(None, description="Vendor-specific override")
    amount_threshold: Optional[Decimal] = Field(None, description="Amount threshold for application")
    is_active: bool = Field(..., description="Whether tolerance is active")
    priority: int = Field(..., description="Tolerance priority (higher = more important)")
    created_at: datetime = Field(..., description="When tolerance was created")
    updated_at: datetime = Field(..., description="When tolerance was last updated")


class MatchingConfigurationResponse(BaseModel):
    """Current matching configuration."""
    config_id: UUID = Field(..., description="Configuration ID")
    tenant_id: UUID = Field(..., description="Tenant ID")
    
    # Confidence thresholds
    auto_approve_threshold: Decimal = Field(..., ge=0.0, le=1.0, description="Auto-approval threshold")
    manual_review_threshold: Decimal = Field(..., ge=0.0, le=1.0, description="Manual review threshold")
    rejection_threshold: Decimal = Field(..., ge=0.0, le=1.0, description="Rejection threshold")
    
    # Feature flags
    fuzzy_matching_enabled: bool = Field(..., description="Whether fuzzy matching is enabled")
    phonetic_matching_enabled: bool = Field(..., description="Whether phonetic matching is enabled")
    ocr_correction_enabled: bool = Field(..., description="Whether OCR correction is enabled")
    
    # Scoring weights
    vendor_name_weight: Decimal = Field(..., ge=0.0, le=1.0, description="Weight for vendor name matching")
    amount_weight: Decimal = Field(..., ge=0.0, le=1.0, description="Weight for amount matching")
    date_weight: Decimal = Field(..., ge=0.0, le=1.0, description="Weight for date matching")
    reference_weight: Decimal = Field(..., ge=0.0, le=1.0, description="Weight for reference matching")
    
    # Performance settings
    batch_size: PositiveInt = Field(..., description="Default batch size for processing")
    parallel_processing_enabled: bool = Field(..., description="Whether parallel processing is enabled")
    max_concurrent_jobs: PositiveInt = Field(..., description="Maximum concurrent processing jobs")
    
    # Date range settings
    default_date_range_days: PositiveInt = Field(..., description="Default date range for matching")
    max_date_range_days: PositiveInt = Field(..., description="Maximum date range for matching")
    
    # Learning settings
    machine_learning_enabled: bool = Field(..., description="Whether ML features are enabled")
    feedback_learning_enabled: bool = Field(..., description="Whether feedback learning is enabled")
    
    # Version and status
    config_version: str = Field(..., description="Configuration version")
    is_active: bool = Field(..., description="Whether configuration is active")
    created_at: datetime = Field(..., description="When configuration was created")
    updated_at: datetime = Field(..., description="When configuration was last updated")


class MatchStatisticsResponse(BaseModel):
    """Matching performance statistics."""
    tenant_id: UUID = Field(..., description="Tenant ID")
    date_range_start: datetime = Field(..., description="Statistics start date")
    date_range_end: datetime = Field(..., description="Statistics end date")
    
    # Volume statistics
    total_invoices_processed: int = Field(..., ge=0, description="Total invoices processed")
    total_matches_found: int = Field(..., ge=0, description="Total matches found")
    match_rate: float = Field(..., ge=0.0, le=1.0, description="Overall match rate")
    
    # Match type breakdown
    exact_matches: int = Field(..., ge=0, description="Number of exact matches")
    fuzzy_matches: int = Field(..., ge=0, description="Number of fuzzy matches")
    three_way_matches: int = Field(..., ge=0, description="Number of 3-way matches")
    
    # Approval statistics
    auto_approved_matches: int = Field(..., ge=0, description="Auto-approved matches")
    manual_review_matches: int = Field(..., ge=0, description="Matches requiring manual review")
    rejected_matches: int = Field(..., ge=0, description="Rejected matches")
    
    # Performance metrics
    average_processing_time: float = Field(..., ge=0.0, description="Average processing time per invoice")
    average_confidence_score: Decimal = Field(..., ge=0.0, le=1.0, description="Average confidence score")
    
    # Accuracy metrics
    false_positive_rate: Optional[float] = Field(None, ge=0.0, le=1.0, description="False positive rate")
    false_negative_rate: Optional[float] = Field(None, ge=0.0, le=1.0, description="False negative rate")
    
    # Generated timestamp
    generated_at: datetime = Field(..., description="When statistics were generated")


# Error Response Schemas

class MatchingErrorResponse(BaseModel):
    """Error response for matching operations."""
    error_code: str = Field(..., description="Error code")
    error_message: str = Field(..., description="Human-readable error message")
    error_details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    invoice_id: Optional[UUID] = Field(None, description="Invoice ID that caused error")
    timestamp: datetime = Field(default_factory=datetime.now, description="Error timestamp")
    
    class Config:
        schema_extra = {
            "example": {
                "error_code": "MATCH_001",
                "error_message": "Invoice not found or not accessible",
                "error_details": {"invoice_id": "123e4567-e89b-12d3-a456-426614174000"},
                "invoice_id": "123e4567-e89b-12d3-a456-426614174000",
                "timestamp": "2025-01-03T12:00:00Z"
            }
        }