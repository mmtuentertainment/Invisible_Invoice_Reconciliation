"""
FastAPI endpoints for automated invoice matching operations.

Provides RESTful API for invoice matching, 3-way reconciliation,
tolerance configuration, and performance monitoring.

Key Features:
- Single and batch invoice matching
- 3-way matching with POs and receipts
- User feedback processing
- Tolerance configuration management  
- Performance statistics and monitoring
- Comprehensive error handling and validation
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.core.database import get_db_with_tenant
from app.core.security import get_current_user_with_tenant
from app.models.auth import UserProfile
from app.models.financial import (
    Invoice, MatchResult, MatchAuditLog, MatchingTolerance, MatchingConfiguration,
    MatchStatus, DocumentStatus
)
from app.schemas.matching import (
    # Request schemas
    MatchInvoiceRequest, BatchMatchRequest, UserFeedbackRequest, ToleranceUpdateRequest,
    # Response schemas  
    MatchResultResponse, BatchMatchResponse, ThreeWayMatchResponse,
    ToleranceConfigResponse, MatchingConfigurationResponse, MatchStatisticsResponse,
    MatchingErrorResponse, VarianceDetail, MatchFactors
)
from app.services.matching_engine import create_matching_engine
from app.services.three_way_matching import create_three_way_matcher

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/matching", tags=["Invoice Matching"])


@router.post(
    "/invoice",
    response_model=MatchResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Match single invoice",
    description="Match a single invoice against purchase orders and receipts with optional 3-way matching"
)
async def match_single_invoice(
    request: MatchInvoiceRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_with_tenant),
    current_user: tuple[UserProfile, UUID] = Depends(get_current_user_with_tenant)
):
    """
    Match a single invoice against available purchase orders and receipts.
    
    This endpoint performs intelligent matching using exact and fuzzy algorithms,
    with optional 3-way matching for complete reconciliation.
    """
    user, tenant_id = current_user
    
    try:
        # Verify invoice exists and belongs to tenant
        invoice_query = select(Invoice).where(
            and_(
                Invoice.id == request.invoice_id,
                Invoice.tenant_id == tenant_id,
                Invoice.status != DocumentStatus.ARCHIVED
            )
        )
        
        result = await db.execute(invoice_query)
        invoice = result.scalar_one_or_none()
        
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Invoice {request.invoice_id} not found or not accessible"
            )
        
        # Check if already matched (unless force rematch)
        if not request.force_rematch:
            existing_match_query = select(MatchResult).where(
                and_(
                    MatchResult.invoice_id == request.invoice_id,
                    MatchResult.tenant_id == tenant_id,
                    MatchResult.match_status != MatchStatus.REJECTED
                )
            )
            
            existing_result = await db.execute(existing_match_query)
            existing_match = existing_result.scalar_one_or_none()
            
            if existing_match:
                # Return existing match result
                return await _convert_match_result_to_response(existing_match, db)
        
        # Initialize matching engine
        matching_engine = await create_matching_engine(tenant_id, db)
        
        # Perform standard matching
        match_decision = await matching_engine.match_invoice(request.invoice_id, db)
        
        if match_decision:
            response = await _convert_match_decision_to_response(match_decision, db)
            
            # Perform 3-way matching if enabled and 2-way match was successful
            if request.three_way_matching and match_decision.po_id:
                background_tasks.add_task(
                    _perform_three_way_matching_background,
                    request.invoice_id,
                    tenant_id,
                    user.id
                )
            
            logger.info(f"Invoice {request.invoice_id} matched successfully by user {user.id}")
            return response
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No suitable match found for invoice {request.invoice_id}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error matching invoice {request.invoice_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during matching operation"
        )


@router.post(
    "/batch",
    response_model=BatchMatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Match batch of invoices",
    description="Match multiple invoices in parallel for improved performance"
)
async def match_invoice_batch(
    request: BatchMatchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_with_tenant),
    current_user: tuple[UserProfile, UUID] = Depends(get_current_user_with_tenant)
):
    """
    Match a batch of invoices for high-throughput processing.
    
    Supports parallel processing and provides comprehensive statistics
    on matching performance and accuracy.
    """
    user, tenant_id = current_user
    batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
    
    try:
        # Verify all invoices exist and belong to tenant
        invoice_query = select(Invoice.id).where(
            and_(
                Invoice.id.in_(request.invoice_ids),
                Invoice.tenant_id == tenant_id,
                Invoice.status != DocumentStatus.ARCHIVED
            )
        )
        
        result = await db.execute(invoice_query)
        existing_invoice_ids = {row[0] for row in result.fetchall()}
        
        missing_invoices = set(request.invoice_ids) - existing_invoice_ids
        if missing_invoices:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Invoices not found: {list(missing_invoices)}"
            )
        
        # Initialize matching engine
        matching_engine = await create_matching_engine(tenant_id, db)
        
        # Record start time
        start_time = datetime.now()
        
        # Process batch
        processing_metrics = await matching_engine.process_batch_matching(
            request.invoice_ids,
            db,
            parallel=request.parallel_processing
        )
        
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        
        # Get all match results for this batch
        match_results_query = select(MatchResult).where(
            and_(
                MatchResult.invoice_id.in_(request.invoice_ids),
                MatchResult.tenant_id == tenant_id,
                MatchResult.matched_at >= start_time
            )
        ).order_by(MatchResult.matched_at.desc())
        
        match_results_data = await db.execute(match_results_query)
        match_results = match_results_data.scalars().all()
        
        # Convert to response format
        response_matches = []
        for match_result in match_results:
            response_match = await _convert_match_result_to_response(match_result, db)
            response_matches.append(response_match)
        
        # Schedule 3-way matching for successful matches if enabled
        if request.three_way_matching:
            successful_matches = [mr for mr in match_results if mr.purchase_order_id]
            if successful_matches:
                background_tasks.add_task(
                    _perform_batch_three_way_matching,
                    [mr.invoice_id for mr in successful_matches],
                    tenant_id,
                    user.id
                )
        
        # Build response
        batch_response = BatchMatchResponse(
            batch_id=batch_id,
            total_invoices=len(request.invoice_ids),
            exact_matches=processing_metrics.exact_matches,
            fuzzy_matches=processing_metrics.fuzzy_matches,
            three_way_matches=0,  # Will be updated by background task
            unmatched=processing_metrics.unmatched,
            auto_approved=processing_metrics.auto_approved,
            manual_review=processing_metrics.manual_review,
            exceptions=0,  # Calculate from results
            processing_time_seconds=processing_time,
            average_confidence=processing_metrics.average_confidence,
            match_results=response_matches,
            started_at=start_time,
            completed_at=end_time
        )
        
        logger.info(f"Batch matching completed for {len(request.invoice_ids)} invoices by user {user.id}")
        return batch_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch matching: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during batch matching"
        )


@router.get(
    "/results/{invoice_id}",
    response_model=List[MatchResultResponse],
    summary="Get match results for invoice",
    description="Retrieve all match results for a specific invoice"
)
async def get_match_results(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db_with_tenant),
    current_user: tuple[UserProfile, UUID] = Depends(get_current_user_with_tenant)
):
    """Get all match results for a specific invoice."""
    user, tenant_id = current_user
    
    try:
        # Get match results
        query = select(MatchResult).where(
            and_(
                MatchResult.invoice_id == invoice_id,
                MatchResult.tenant_id == tenant_id
            )
        ).order_by(MatchResult.matched_at.desc())
        
        result = await db.execute(query)
        match_results = result.scalars().all()
        
        if not match_results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No match results found for invoice {invoice_id}"
            )
        
        # Convert to response format
        responses = []
        for match_result in match_results:
            response = await _convert_match_result_to_response(match_result, db)
            responses.append(response)
        
        return responses
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting match results for invoice {invoice_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error retrieving match results"
        )


@router.post(
    "/feedback",
    status_code=status.HTTP_200_OK,
    summary="Provide user feedback on match",
    description="Submit user feedback to improve matching accuracy through machine learning"
)
async def submit_user_feedback(
    request: UserFeedbackRequest,
    db: AsyncSession = Depends(get_db_with_tenant),
    current_user: tuple[UserProfile, UUID] = Depends(get_current_user_with_tenant)
):
    """
    Submit user feedback on match results to improve algorithm accuracy.
    
    Feedback is used for machine learning model training and algorithm tuning.
    """
    user, tenant_id = current_user
    
    try:
        # Initialize matching engine for feedback processing
        matching_engine = await create_matching_engine(tenant_id, db)
        
        # Process feedback
        feedback_data = {
            "type": request.feedback_type,
            "notes": request.notes,
            "confidence_override": request.confidence_override,
            "user_id": user.id,
            "submitted_at": datetime.now()
        }
        
        await matching_engine.provide_user_feedback(
            request.match_result_id,
            feedback_data,
            user.id,
            db
        )
        
        logger.info(f"User feedback processed for match {request.match_result_id} by user {user.id}")
        
        return {"message": "Feedback submitted successfully", "feedback_id": str(uuid.uuid4())}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error processing user feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error processing feedback"
        )


@router.get(
    "/three-way/{invoice_id}",
    response_model=ThreeWayMatchResponse,
    summary="Get 3-way match results",
    description="Retrieve detailed 3-way matching results for invoice-PO-receipt reconciliation"
)
async def get_three_way_match_results(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db_with_tenant),
    current_user: tuple[UserProfile, UUID] = Depends(get_current_user_with_tenant)
):
    """Get detailed 3-way matching results for an invoice."""
    user, tenant_id = current_user
    
    try:
        # Create 3-way matcher and perform matching
        three_way_matcher = await create_three_way_matcher(tenant_id)
        result = await three_way_matcher.perform_three_way_match(invoice_id, db)
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No 3-way match results found for invoice {invoice_id}"
            )
        
        # Convert to response format
        line_matches = []
        for line_match in result.line_matches:
            line_response = {
                "po_line_id": line_match.po_line_id,
                "invoice_line_id": line_match.invoice_line_id,
                "receipt_line_id": line_match.receipt_line_id,
                "po_quantity": line_match.po_quantity,
                "invoice_quantity": line_match.invoice_quantity,
                "receipt_quantity": line_match.receipt_quantity,
                "po_amount": line_match.po_amount,
                "invoice_amount": line_match.invoice_amount,
                "receipt_amount": line_match.receipt_amount,
                "quantity_variance": line_match.quantity_variance,
                "amount_variance": line_match.amount_variance,
                "is_matched": line_match.is_matched,
                "variance_within_tolerance": line_match.variance_within_tolerance,
                "match_confidence": line_match.match_confidence,
                "variance_explanation": line_match.variance_explanation
            }
            line_matches.append(line_response)
        
        response = ThreeWayMatchResponse(
            invoice_id=result.invoice_id,
            po_id=result.po_id,
            receipt_ids=result.receipt_ids,
            match_type=result.match_type,
            overall_confidence=result.overall_confidence,
            line_matches=line_matches,
            total_po_amount=result.total_po_amount,
            total_invoice_amount=result.total_invoice_amount,
            total_receipt_amount=result.total_receipt_amount,
            net_amount_variance=result.net_amount_variance,
            total_po_quantity=result.total_po_quantity,
            total_invoice_quantity=result.total_invoice_quantity,
            total_receipt_quantity=result.total_receipt_quantity,
            net_quantity_variance=result.net_quantity_variance,
            amount_within_tolerance=result.amount_within_tolerance,
            quantity_within_tolerance=result.quantity_within_tolerance,
            auto_approved=result.auto_approved,
            requires_review=result.requires_review,
            exception_items=result.exception_items,
            processed_at=result.processed_at,
            matching_algorithm_version=result.matching_algorithm_version
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting 3-way match results for invoice {invoice_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error retrieving 3-way match results"
        )


@router.get(
    "/tolerances",
    response_model=List[ToleranceConfigResponse],
    summary="Get tolerance configuration",
    description="Retrieve current matching tolerance configuration"
)
async def get_tolerance_configuration(
    tolerance_type: Optional[str] = Query(None, regex="^(price|quantity|date)$"),
    vendor_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db_with_tenant),
    current_user: tuple[UserProfile, UUID] = Depends(get_current_user_with_tenant)
):
    """Get current matching tolerance configuration."""
    user, tenant_id = current_user
    
    try:
        query = select(MatchingTolerance).where(
            and_(
                MatchingTolerance.tenant_id == tenant_id,
                MatchingTolerance.is_active == True
            )
        )
        
        if tolerance_type:
            query = query.where(MatchingTolerance.tolerance_type == tolerance_type)
        
        if vendor_id:
            query = query.where(MatchingTolerance.vendor_id == vendor_id)
            
        query = query.order_by(MatchingTolerance.priority.desc())
        
        result = await db.execute(query)
        tolerances = result.scalars().all()
        
        responses = []
        for tolerance in tolerances:
            response = ToleranceConfigResponse(
                tolerance_id=tolerance.id,
                tolerance_type=tolerance.tolerance_type,
                percentage_tolerance=tolerance.percentage_tolerance,
                absolute_tolerance=tolerance.absolute_tolerance,
                vendor_id=tolerance.vendor_id,
                amount_threshold=tolerance.amount_threshold,
                is_active=tolerance.is_active,
                priority=tolerance.priority,
                created_at=tolerance.created_at,
                updated_at=tolerance.updated_at
            )
            responses.append(response)
        
        return responses
        
    except Exception as e:
        logger.error(f"Error getting tolerance configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error retrieving tolerance configuration"
        )


@router.put(
    "/tolerances",
    response_model=ToleranceConfigResponse,
    summary="Update tolerance configuration",
    description="Update matching tolerance settings for improved accuracy"
)
async def update_tolerance_configuration(
    request: ToleranceUpdateRequest,
    db: AsyncSession = Depends(get_db_with_tenant),
    current_user: tuple[UserProfile, UUID] = Depends(get_current_user_with_tenant)
):
    """Update matching tolerance configuration."""
    user, tenant_id = current_user
    
    try:
        # Create or update tolerance configuration
        tolerance = MatchingTolerance(
            tenant_id=tenant_id,
            tolerance_type=request.tolerance_type,
            percentage_tolerance=request.percentage_tolerance,
            absolute_tolerance=request.absolute_tolerance,
            vendor_id=request.vendor_id,
            amount_threshold=request.amount_threshold,
            is_active=True,
            priority=1,  # Default priority
            created_by=user.id,
            updated_by=user.id
        )
        
        db.add(tolerance)
        await db.commit()
        await db.refresh(tolerance)
        
        response = ToleranceConfigResponse(
            tolerance_id=tolerance.id,
            tolerance_type=tolerance.tolerance_type,
            percentage_tolerance=tolerance.percentage_tolerance,
            absolute_tolerance=tolerance.absolute_tolerance,
            vendor_id=tolerance.vendor_id,
            amount_threshold=tolerance.amount_threshold,
            is_active=tolerance.is_active,
            priority=tolerance.priority,
            created_at=tolerance.created_at,
            updated_at=tolerance.updated_at
        )
        
        logger.info(f"Tolerance configuration updated by user {user.id}")
        return response
        
    except Exception as e:
        logger.error(f"Error updating tolerance configuration: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error updating tolerance configuration"
        )


@router.get(
    "/statistics",
    response_model=MatchStatisticsResponse,
    summary="Get matching performance statistics",
    description="Retrieve comprehensive matching performance and accuracy statistics"
)
async def get_matching_statistics(
    days: int = Query(30, ge=1, le=365, description="Number of days to include in statistics"),
    db: AsyncSession = Depends(get_db_with_tenant),
    current_user: tuple[UserProfile, UUID] = Depends(get_current_user_with_tenant)
):
    """Get comprehensive matching performance statistics."""
    user, tenant_id = current_user
    
    try:
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # Get basic statistics
        stats_query = select(
            func.count(MatchResult.id).label('total_matches'),
            func.count().filter(MatchResult.match_type == 'exact').label('exact_matches'),
            func.count().filter(MatchResult.match_type == 'fuzzy').label('fuzzy_matches'),
            func.count().filter(MatchResult.auto_approved == True).label('auto_approved'),
            func.count().filter(MatchResult.requires_review == True).label('manual_review'),
            func.count().filter(MatchResult.match_status == 'rejected').label('rejected'),
            func.avg(MatchResult.confidence_score).label('avg_confidence')
        ).where(
            and_(
                MatchResult.tenant_id == tenant_id,
                MatchResult.matched_at >= start_date,
                MatchResult.matched_at <= end_date
            )
        )
        
        result = await db.execute(stats_query)
        stats = result.first()
        
        # Get unique invoice count
        invoice_count_query = select(
            func.count(func.distinct(MatchResult.invoice_id))
        ).where(
            and_(
                MatchResult.tenant_id == tenant_id,
                MatchResult.matched_at >= start_date,
                MatchResult.matched_at <= end_date
            )
        )
        
        invoice_result = await db.execute(invoice_count_query)
        total_invoices = invoice_result.scalar() or 0
        
        # Calculate rates and averages
        total_matches = stats.total_matches or 0
        match_rate = total_matches / total_invoices if total_invoices > 0 else 0.0
        avg_confidence = stats.avg_confidence or 0.0
        
        response = MatchStatisticsResponse(
            tenant_id=tenant_id,
            date_range_start=start_date,
            date_range_end=end_date,
            total_invoices_processed=total_invoices,
            total_matches_found=total_matches,
            match_rate=match_rate,
            exact_matches=stats.exact_matches or 0,
            fuzzy_matches=stats.fuzzy_matches or 0,
            three_way_matches=0,  # Would need separate query
            auto_approved_matches=stats.auto_approved or 0,
            manual_review_matches=stats.manual_review or 0,
            rejected_matches=stats.rejected or 0,
            average_processing_time=0.0,  # Would need performance tracking
            average_confidence_score=avg_confidence,
            false_positive_rate=None,  # Would need feedback analysis
            false_negative_rate=None,  # Would need feedback analysis
            generated_at=datetime.now()
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error getting matching statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error retrieving statistics"
        )


# Helper functions

async def _convert_match_result_to_response(match_result: MatchResult, db: AsyncSession) -> MatchResultResponse:
    """Convert database MatchResult to API response format."""
    
    # Build match factors from stored criteria
    criteria = match_result.criteria_met or {}
    
    match_factors = MatchFactors(
        vendor_similarity=criteria.get('vendor_similarity', 0.0),
        amount_within_tolerance=criteria.get('amount_within_tolerance', False),
        quantity_within_tolerance=criteria.get('quantity_within_tolerance'),
        date_within_tolerance=criteria.get('date_within_tolerance', False),
        reference_exact_match=criteria.get('reference_exact_match', False),
        reference_similarity=criteria.get('reference_similarity', 0.0),
        vendor_score=criteria.get('vendor_score', 0.0),
        amount_score=criteria.get('amount_score', 0.0),
        date_score=criteria.get('date_score', 0.0),
        reference_score=criteria.get('reference_score', 0.0)
    )
    
    variance_details = VarianceDetail(
        amount_variance=match_result.amount_variance,
        amount_variance_percentage=float(match_result.amount_variance) if match_result.amount_variance else None,
        quantity_variance=match_result.quantity_variance,
        quantity_variance_percentage=float(match_result.quantity_variance) if match_result.quantity_variance else None,
        date_variance_days=criteria.get('date_variance_days')
    )
    
    # Generate explanation if not stored
    explanation = f"{match_result.match_type.value} match with {float(match_result.confidence_score):.1%} confidence"
    
    return MatchResultResponse(
        match_result_id=match_result.id,
        invoice_id=match_result.invoice_id,
        purchase_order_id=match_result.purchase_order_id,
        receipt_id=match_result.receipt_id,
        match_type=match_result.match_type.value,
        confidence_score=match_result.confidence_score,
        match_status=match_result.match_status.value,
        auto_approved=match_result.auto_approved,
        requires_review=match_result.requires_review,
        match_factors=match_factors,
        variance_details=variance_details,
        explanation=explanation,
        matched_at=match_result.matched_at,
        reviewed_at=match_result.reviewed_at,
        approved_at=match_result.approved_at
    )


async def _convert_match_decision_to_response(match_decision, db: AsyncSession) -> MatchResultResponse:
    """Convert MatchDecision to API response format."""
    
    match_factors = MatchFactors(
        vendor_similarity=match_decision.criteria_met.get('vendor_similarity', 0.0),
        amount_within_tolerance=match_decision.criteria_met.get('amount_within_tolerance', False),
        quantity_within_tolerance=match_decision.criteria_met.get('quantity_within_tolerance'),
        date_within_tolerance=match_decision.criteria_met.get('date_within_tolerance', False),
        reference_exact_match=match_decision.criteria_met.get('reference_exact_match', False),
        reference_similarity=match_decision.criteria_met.get('reference_similarity', 0.0),
        vendor_score=0.0,  # Would need to calculate from criteria
        amount_score=0.0,
        date_score=0.0,
        reference_score=0.0
    )
    
    variance_details = VarianceDetail(
        amount_variance=match_decision.variance_analysis.get('amount_variance'),
        amount_variance_percentage=match_decision.variance_analysis.get('amount_variance_percentage'),
        quantity_variance=match_decision.variance_analysis.get('quantity_variance'),
        quantity_variance_percentage=match_decision.variance_analysis.get('quantity_variance_percentage'),
        date_variance_days=match_decision.variance_analysis.get('date_variance_days')
    )
    
    # Generate a temporary match result ID (would normally be from database)
    temp_match_id = uuid.uuid4()
    
    return MatchResultResponse(
        match_result_id=temp_match_id,
        invoice_id=match_decision.invoice_id,
        purchase_order_id=match_decision.po_id,
        receipt_id=match_decision.receipt_id,
        match_type=match_decision.match_type.value,
        confidence_score=match_decision.confidence_score,
        match_status="approved" if match_decision.auto_approved else "pending",
        auto_approved=match_decision.auto_approved,
        requires_review=match_decision.requires_review,
        match_factors=match_factors,
        variance_details=variance_details,
        explanation=match_decision.explanation,
        matched_at=datetime.now(),
        reviewed_at=None,
        approved_at=datetime.now() if match_decision.auto_approved else None
    )


async def _perform_three_way_matching_background(invoice_id: UUID, tenant_id: UUID, user_id: UUID):
    """Background task to perform 3-way matching."""
    try:
        from app.core.database import get_db_context
        
        async with get_db_context() as db:
            three_way_matcher = await create_three_way_matcher(tenant_id)
            result = await three_way_matcher.perform_three_way_match(invoice_id, db)
            
            if result:
                logger.info(f"3-way matching completed for invoice {invoice_id}")
            else:
                logger.warning(f"3-way matching failed for invoice {invoice_id}")
                
    except Exception as e:
        logger.error(f"Error in background 3-way matching for invoice {invoice_id}: {e}")


async def _perform_batch_three_way_matching(invoice_ids: List[UUID], tenant_id: UUID, user_id: UUID):
    """Background task to perform batch 3-way matching."""
    try:
        from app.core.database import get_db_context
        
        async with get_db_context() as db:
            three_way_matcher = await create_three_way_matcher(tenant_id)
            
            for invoice_id in invoice_ids:
                try:
                    result = await three_way_matcher.perform_three_way_match(invoice_id, db)
                    if result:
                        logger.debug(f"3-way matching completed for invoice {invoice_id}")
                except Exception as e:
                    logger.warning(f"3-way matching failed for invoice {invoice_id}: {e}")
                    
        logger.info(f"Batch 3-way matching completed for {len(invoice_ids)} invoices")
        
    except Exception as e:
        logger.error(f"Error in batch 3-way matching: {e}")