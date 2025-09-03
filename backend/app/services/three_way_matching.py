"""
3-Way Matching Service for Invoice-PO-Receipt Reconciliation.

This service implements advanced 3-way matching logic that correlates invoices,
purchase orders, and goods receipts to ensure complete financial accuracy and
compliance with procurement policies.

Key Features:
- Complete 3-way reconciliation (Invoice + PO + Receipt)
- Partial PO matching for split shipments
- Multiple receipts per PO handling
- Quantity and amount variance analysis
- Split shipment and partial delivery support
- Financial accuracy with decimal precision
"""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple, Any, Set
from uuid import UUID
from dataclasses import dataclass
from enum import Enum

import pandas as pd
import numpy as np
from sqlalchemy import and_, or_, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import (
    Invoice, PurchaseOrder, Receipt, PurchaseOrderLine, InvoiceLine, ReceiptLine,
    MatchResult, MatchAuditLog, MatchingTolerance,
    MatchType, MatchStatus, DocumentStatus
)
from app.services.matching_engine import (
    MatchCandidate, MatchDecision, ToleranceEngine, ConfidenceScorer
)

# Configure logging
logger = logging.getLogger(__name__)


class ThreeWayMatchType(str, Enum):
    """Types of 3-way matching scenarios."""
    PERFECT_MATCH = "perfect_match"      # Invoice = PO = Receipt (exact)
    PARTIAL_RECEIPT = "partial_receipt"  # Invoice = PO, partial receipt
    SPLIT_DELIVERY = "split_delivery"    # Invoice = PO, multiple receipts
    OVER_DELIVERY = "over_delivery"      # Receipt > PO quantity
    UNDER_DELIVERY = "under_delivery"    # Receipt < PO quantity
    PRICE_VARIANCE = "price_variance"    # Price differences within tolerance
    QUANTITY_VARIANCE = "quantity_variance"  # Quantity differences within tolerance


@dataclass
class LineItemMatch:
    """Represents a line-level match between documents."""
    po_line_id: Optional[UUID]
    invoice_line_id: Optional[UUID]
    receipt_line_id: Optional[UUID]
    
    # Quantities
    po_quantity: Optional[Decimal]
    invoice_quantity: Optional[Decimal]
    receipt_quantity: Optional[Decimal]
    
    # Amounts
    po_amount: Optional[Decimal]
    invoice_amount: Optional[Decimal]
    receipt_amount: Optional[Decimal]
    
    # Variances
    quantity_variance: Decimal
    amount_variance: Decimal
    
    # Match status
    is_matched: bool
    variance_within_tolerance: bool
    match_confidence: Decimal
    
    # Explanations
    variance_explanation: str


@dataclass
class ThreeWayMatchResult:
    """Complete 3-way matching result."""
    invoice_id: UUID
    po_id: Optional[UUID]
    receipt_ids: List[UUID]
    
    # Match classification
    match_type: ThreeWayMatchType
    overall_confidence: Decimal
    
    # Line-level matches
    line_matches: List[LineItemMatch]
    
    # Financial summary
    total_po_amount: Decimal
    total_invoice_amount: Decimal
    total_receipt_amount: Decimal
    net_amount_variance: Decimal
    
    total_po_quantity: Decimal
    total_invoice_quantity: Decimal
    total_receipt_quantity: Decimal
    net_quantity_variance: Decimal
    
    # Tolerance checks
    amount_within_tolerance: bool
    quantity_within_tolerance: bool
    
    # Decision flags
    auto_approved: bool
    requires_review: bool
    exception_items: List[str]
    
    # Audit information
    matching_algorithm_version: str
    processed_at: datetime
    
    
class ThreeWayMatcher:
    """
    Advanced 3-way matching engine that correlates invoices, POs, and receipts
    at both header and line levels with comprehensive variance analysis.
    """
    
    def __init__(self, tenant_id: UUID):
        self.tenant_id = tenant_id
        self.confidence_scorer = ConfidenceScorer()
        
        # Default thresholds - should be loaded from configuration
        self.auto_approve_threshold = Decimal('0.95')
        self.manual_review_threshold = Decimal('0.80')
        self.amount_tolerance_percentage = Decimal('0.02')  # 2%
        self.quantity_tolerance_percentage = Decimal('0.01')  # 1%
        
    async def perform_three_way_match(
        self,
        invoice_id: UUID,
        db: AsyncSession
    ) -> Optional[ThreeWayMatchResult]:
        """
        Perform comprehensive 3-way matching for an invoice.
        
        Args:
            invoice_id: Invoice to match
            db: Database session
            
        Returns:
            ThreeWayMatchResult if successful match found, None otherwise
        """
        try:
            # Load invoice with line items
            invoice = await self._load_invoice_with_lines(invoice_id, db)
            if not invoice:
                logger.warning(f"Invoice {invoice_id} not found")
                return None
            
            # Find matching PO
            matching_po = await self._find_matching_po(invoice, db)
            if not matching_po:
                logger.info(f"No matching PO found for invoice {invoice_id}")
                return None
            
            # Find related receipts
            related_receipts = await self._find_related_receipts(matching_po.id, invoice, db)
            
            # Perform line-level matching
            line_matches = await self._perform_line_level_matching(
                invoice, matching_po, related_receipts, db
            )
            
            # Calculate financial summaries
            financial_summary = self._calculate_financial_summary(
                invoice, matching_po, related_receipts, line_matches
            )
            
            # Determine match type and confidence
            match_type, confidence = self._classify_match_type(
                line_matches, financial_summary
            )
            
            # Apply tolerance checks
            tolerance_results = await self._apply_tolerance_checks(
                financial_summary, db
            )
            
            # Make approval decision
            auto_approved, requires_review, exceptions = self._make_approval_decision(
                confidence, tolerance_results, line_matches
            )
            
            # Create comprehensive result
            result = ThreeWayMatchResult(
                invoice_id=invoice.id,
                po_id=matching_po.id,
                receipt_ids=[receipt.id for receipt in related_receipts],
                match_type=match_type,
                overall_confidence=confidence,
                line_matches=line_matches,
                **financial_summary,
                amount_within_tolerance=tolerance_results['amount_within_tolerance'],
                quantity_within_tolerance=tolerance_results['quantity_within_tolerance'],
                auto_approved=auto_approved,
                requires_review=requires_review,
                exception_items=exceptions,
                matching_algorithm_version="3-way-v1.0.0",
                processed_at=datetime.now()
            )
            
            # Save results to database
            await self._save_three_way_match_result(result, db)
            
            logger.info(f"3-way match completed for invoice {invoice_id}: {match_type.value}, confidence {confidence}")
            return result
            
        except Exception as e:
            logger.error(f"Error in 3-way matching for invoice {invoice_id}: {e}")
            return None
    
    async def _load_invoice_with_lines(self, invoice_id: UUID, db: AsyncSession) -> Optional[Invoice]:
        """Load invoice with all line items."""
        query = select(Invoice).where(
            and_(
                Invoice.id == invoice_id,
                Invoice.tenant_id == self.tenant_id
            )
        )
        
        result = await db.execute(query)
        invoice = result.scalar_one_or_none()
        
        if invoice:
            # Load line items separately
            lines_query = select(InvoiceLine).where(
                InvoiceLine.invoice_id == invoice_id
            ).order_by(InvoiceLine.line_number)
            
            lines_result = await db.execute(lines_query)
            invoice.invoice_lines = lines_result.scalars().all()
        
        return invoice
    
    async def _find_matching_po(self, invoice: Invoice, db: AsyncSession) -> Optional[PurchaseOrder]:
        """Find the best matching PO for the invoice."""
        # Primary match: exact PO number match
        if invoice.po_reference:
            po_query = select(PurchaseOrder).where(
                and_(
                    PurchaseOrder.tenant_id == self.tenant_id,
                    PurchaseOrder.po_number == invoice.po_reference.strip(),
                    PurchaseOrder.vendor_id == invoice.vendor_id,
                    PurchaseOrder.status != DocumentStatus.ARCHIVED
                )
            )
            
            result = await db.execute(po_query)
            exact_match = result.scalar_one_or_none()
            if exact_match:
                return exact_match
        
        # Secondary match: fuzzy matching on amount and date
        date_range_start = invoice.invoice_date - timedelta(days=30)
        date_range_end = invoice.invoice_date + timedelta(days=7)
        
        fuzzy_query = select(PurchaseOrder).where(
            and_(
                PurchaseOrder.tenant_id == self.tenant_id,
                PurchaseOrder.vendor_id == invoice.vendor_id,
                PurchaseOrder.po_date >= date_range_start,
                PurchaseOrder.po_date <= date_range_end,
                PurchaseOrder.status != DocumentStatus.ARCHIVED,
                # Amount should be within 10% for fuzzy matching
                PurchaseOrder.total_amount >= invoice.total_amount * Decimal('0.9'),
                PurchaseOrder.total_amount <= invoice.total_amount * Decimal('1.1')
            )
        ).order_by(
            func.abs(PurchaseOrder.total_amount - invoice.total_amount)
        )
        
        fuzzy_result = await db.execute(fuzzy_query)
        return fuzzy_result.scalar_one_or_none()
    
    async def _find_related_receipts(
        self, 
        po_id: UUID, 
        invoice: Invoice, 
        db: AsyncSession
    ) -> List[Receipt]:
        """Find all receipts related to the PO within reasonable date range."""
        # Look for receipts within 60 days of PO or invoice date
        date_range_start = min(invoice.invoice_date - timedelta(days=60), datetime.now() - timedelta(days=90))
        date_range_end = max(invoice.invoice_date + timedelta(days=30), datetime.now())
        
        receipt_query = select(Receipt).where(
            and_(
                Receipt.tenant_id == self.tenant_id,
                Receipt.purchase_order_id == po_id,
                Receipt.receipt_date >= date_range_start,
                Receipt.receipt_date <= date_range_end,
                Receipt.status != DocumentStatus.ARCHIVED
            )
        ).order_by(Receipt.receipt_date)
        
        result = await db.execute(receipt_query)
        receipts = result.scalars().all()
        
        # Load receipt lines for each receipt
        for receipt in receipts:
            lines_query = select(ReceiptLine).where(
                ReceiptLine.receipt_id == receipt.id
            ).order_by(ReceiptLine.line_number)
            
            lines_result = await db.execute(lines_query)
            receipt.receipt_lines = lines_result.scalars().all()
        
        return receipts
    
    async def _perform_line_level_matching(
        self,
        invoice: Invoice,
        po: PurchaseOrder,
        receipts: List[Receipt],
        db: AsyncSession
    ) -> List[LineItemMatch]:
        """Perform detailed line-level matching between invoice, PO, and receipts."""
        
        # Load PO lines
        po_lines_query = select(PurchaseOrderLine).where(
            PurchaseOrderLine.purchase_order_id == po.id
        ).order_by(PurchaseOrderLine.line_number)
        
        po_lines_result = await db.execute(po_lines_query)
        po_lines = po_lines_result.scalars().all()
        
        # Aggregate receipt quantities by PO line
        receipt_aggregates = self._aggregate_receipt_lines(receipts, po_lines)
        
        line_matches = []
        
        # Match each invoice line
        for inv_line in invoice.invoice_lines:
            best_match = None
            best_confidence = Decimal('0.0')
            
            # Try to match with PO lines based on description, item code, or line number
            for po_line in po_lines:
                confidence = self._calculate_line_match_confidence(inv_line, po_line)
                
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = po_line
            
            if best_match and best_confidence >= Decimal('0.7'):  # Minimum line match threshold
                # Get corresponding receipt aggregate
                receipt_aggregate = receipt_aggregates.get(best_match.id, {
                    'quantity': Decimal('0'),
                    'amount': Decimal('0'),
                    'line_ids': []
                })
                
                # Calculate variances
                qty_variance = self._calculate_quantity_variance(
                    inv_line.quantity, 
                    best_match.quantity, 
                    receipt_aggregate['quantity']
                )
                
                amt_variance = self._calculate_amount_variance(
                    inv_line.line_total,
                    best_match.line_total,
                    receipt_aggregate['amount']
                )
                
                # Check if variances are within tolerance
                qty_tolerance_ok = abs(qty_variance) <= self.quantity_tolerance_percentage
                amt_tolerance_ok = abs(amt_variance) <= self.amount_tolerance_percentage
                
                line_match = LineItemMatch(
                    po_line_id=best_match.id,
                    invoice_line_id=inv_line.id,
                    receipt_line_id=receipt_aggregate['line_ids'][0] if receipt_aggregate['line_ids'] else None,
                    po_quantity=best_match.quantity,
                    invoice_quantity=inv_line.quantity,
                    receipt_quantity=receipt_aggregate['quantity'],
                    po_amount=best_match.line_total,
                    invoice_amount=inv_line.line_total,
                    receipt_amount=receipt_aggregate['amount'],
                    quantity_variance=qty_variance,
                    amount_variance=amt_variance,
                    is_matched=True,
                    variance_within_tolerance=qty_tolerance_ok and amt_tolerance_ok,
                    match_confidence=best_confidence,
                    variance_explanation=self._explain_line_variance(qty_variance, amt_variance)
                )
            else:
                # Unmatched invoice line
                line_match = LineItemMatch(
                    po_line_id=None,
                    invoice_line_id=inv_line.id,
                    receipt_line_id=None,
                    po_quantity=None,
                    invoice_quantity=inv_line.quantity,
                    receipt_quantity=None,
                    po_amount=None,
                    invoice_amount=inv_line.line_total,
                    receipt_amount=None,
                    quantity_variance=Decimal('1.0'),  # 100% variance for unmatched
                    amount_variance=Decimal('1.0'),
                    is_matched=False,
                    variance_within_tolerance=False,
                    match_confidence=Decimal('0.0'),
                    variance_explanation="No matching PO line found"
                )
            
            line_matches.append(line_match)
        
        return line_matches
    
    def _aggregate_receipt_lines(
        self, 
        receipts: List[Receipt], 
        po_lines: List[PurchaseOrderLine]
    ) -> Dict[UUID, Dict[str, Any]]:
        """Aggregate receipt line quantities and amounts by PO line."""
        aggregates = {}
        
        for receipt in receipts:
            for receipt_line in receipt.receipt_lines:
                po_line_id = receipt_line.po_line_id
                
                if po_line_id not in aggregates:
                    aggregates[po_line_id] = {
                        'quantity': Decimal('0'),
                        'amount': Decimal('0'),
                        'line_ids': []
                    }
                
                aggregates[po_line_id]['quantity'] += receipt_line.quantity_received
                aggregates[po_line_id]['amount'] += receipt_line.line_value
                aggregates[po_line_id]['line_ids'].append(receipt_line.id)
        
        return aggregates
    
    def _calculate_line_match_confidence(
        self, 
        invoice_line: InvoiceLine, 
        po_line: PurchaseOrderLine
    ) -> Decimal:
        """Calculate confidence score for matching an invoice line to a PO line."""
        factors = []
        
        # Item code exact match
        if invoice_line.item_code and po_line.item_code:
            if invoice_line.item_code.strip().upper() == po_line.item_code.strip().upper():
                factors.append(0.4)  # High weight for item code match
            else:
                factors.append(0.0)
        else:
            factors.append(0.1)  # Neutral for missing item codes
        
        # Description similarity (simplified fuzzy matching)
        desc_similarity = self._calculate_description_similarity(
            invoice_line.description, 
            po_line.description
        )
        factors.append(desc_similarity * 0.3)
        
        # Unit price similarity
        if po_line.unit_price > 0:
            price_diff = abs(invoice_line.unit_price - po_line.unit_price) / po_line.unit_price
            price_similarity = max(0.0, 1.0 - float(price_diff))
            factors.append(price_similarity * 0.2)
        else:
            factors.append(0.0)
        
        # Quantity reasonableness
        if po_line.quantity > 0:
            qty_ratio = min(float(invoice_line.quantity / po_line.quantity), 
                           float(po_line.quantity / invoice_line.quantity))
            factors.append(qty_ratio * 0.1)
        else:
            factors.append(0.0)
        
        return Decimal(str(sum(factors))).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
    
    def _calculate_description_similarity(self, desc1: str, desc2: str) -> float:
        """Calculate similarity between two descriptions (simplified)."""
        if not desc1 or not desc2:
            return 0.0
        
        # Simple word overlap calculation
        words1 = set(desc1.lower().split())
        words2 = set(desc2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def _calculate_quantity_variance(
        self, 
        invoice_qty: Decimal, 
        po_qty: Decimal, 
        receipt_qty: Decimal
    ) -> Decimal:
        """Calculate quantity variance as a percentage."""
        if po_qty == 0:
            return Decimal('1.0')  # 100% variance if no PO quantity
        
        # Use receipt quantity if available, otherwise compare invoice to PO
        compare_qty = receipt_qty if receipt_qty > 0 else invoice_qty
        return abs(compare_qty - po_qty) / po_qty
    
    def _calculate_amount_variance(
        self, 
        invoice_amount: Decimal, 
        po_amount: Decimal, 
        receipt_amount: Decimal
    ) -> Decimal:
        """Calculate amount variance as a percentage."""
        if po_amount == 0:
            return Decimal('1.0')  # 100% variance if no PO amount
        
        # Primary comparison is invoice to PO
        return abs(invoice_amount - po_amount) / po_amount
    
    def _explain_line_variance(self, qty_variance: Decimal, amt_variance: Decimal) -> str:
        """Generate human-readable explanation for line-level variances."""
        explanations = []
        
        if qty_variance > Decimal('0.05'):  # 5% threshold
            explanations.append(f"Quantity variance: {float(qty_variance):.1%}")
        
        if amt_variance > Decimal('0.05'):  # 5% threshold
            explanations.append(f"Amount variance: {float(amt_variance):.1%}")
        
        if not explanations:
            return "Within tolerance"
        
        return "; ".join(explanations)
    
    def _calculate_financial_summary(
        self,
        invoice: Invoice,
        po: PurchaseOrder,
        receipts: List[Receipt],
        line_matches: List[LineItemMatch]
    ) -> Dict[str, Any]:
        """Calculate comprehensive financial summary for the 3-way match."""
        
        # Aggregate totals
        total_po_amount = po.total_amount
        total_invoice_amount = invoice.total_amount
        total_receipt_amount = sum(receipt.total_value for receipt in receipts)
        
        total_po_quantity = sum(line.quantity for line in po.po_lines if hasattr(po, 'po_lines'))
        total_invoice_quantity = sum(line.quantity for line in invoice.invoice_lines)
        total_receipt_quantity = sum(
            receipt.total_quantity for receipt in receipts
        )
        
        # Calculate net variances
        net_amount_variance = abs(total_invoice_amount - total_po_amount)
        net_quantity_variance = abs(total_invoice_quantity - total_po_quantity) if total_po_quantity else Decimal('0')
        
        return {
            'total_po_amount': total_po_amount,
            'total_invoice_amount': total_invoice_amount,
            'total_receipt_amount': total_receipt_amount,
            'net_amount_variance': net_amount_variance,
            'total_po_quantity': total_po_quantity,
            'total_invoice_quantity': total_invoice_quantity,
            'total_receipt_quantity': total_receipt_quantity,
            'net_quantity_variance': net_quantity_variance
        }
    
    def _classify_match_type(
        self, 
        line_matches: List[LineItemMatch], 
        financial_summary: Dict[str, Any]
    ) -> Tuple[ThreeWayMatchType, Decimal]:
        """Classify the type of 3-way match and calculate overall confidence."""
        
        # Calculate match statistics
        total_lines = len(line_matches)
        matched_lines = sum(1 for match in line_matches if match.is_matched)
        lines_within_tolerance = sum(1 for match in line_matches if match.variance_within_tolerance)
        
        if total_lines == 0:
            return ThreeWayMatchType.PERFECT_MATCH, Decimal('0.0')
        
        match_percentage = Decimal(str(matched_lines / total_lines))
        tolerance_percentage = Decimal(str(lines_within_tolerance / total_lines))
        
        # Classify based on matching characteristics
        if match_percentage >= Decimal('0.95') and tolerance_percentage >= Decimal('0.95'):
            match_type = ThreeWayMatchType.PERFECT_MATCH
            confidence = Decimal('0.95')
            
        elif financial_summary['total_receipt_quantity'] < financial_summary['total_po_quantity']:
            match_type = ThreeWayMatchType.PARTIAL_RECEIPT
            confidence = match_percentage * Decimal('0.85')
            
        elif len([m for m in line_matches if m.receipt_line_id]) > len([m for m in line_matches if m.po_line_id]):
            match_type = ThreeWayMatchType.SPLIT_DELIVERY
            confidence = match_percentage * Decimal('0.80')
            
        elif financial_summary['net_amount_variance'] > financial_summary['total_po_amount'] * self.amount_tolerance_percentage:
            match_type = ThreeWayMatchType.PRICE_VARIANCE
            confidence = tolerance_percentage * Decimal('0.75')
            
        elif financial_summary['net_quantity_variance'] > financial_summary['total_po_quantity'] * self.quantity_tolerance_percentage:
            match_type = ThreeWayMatchType.QUANTITY_VARIANCE
            confidence = tolerance_percentage * Decimal('0.70')
            
        else:
            # Default to partial receipt for other cases
            match_type = ThreeWayMatchType.PARTIAL_RECEIPT
            confidence = match_percentage * tolerance_percentage * Decimal('0.80')
        
        # Ensure confidence is within bounds
        confidence = max(Decimal('0.0'), min(Decimal('1.0'), confidence))
        
        return match_type, confidence
    
    async def _apply_tolerance_checks(
        self, 
        financial_summary: Dict[str, Any], 
        db: AsyncSession
    ) -> Dict[str, bool]:
        """Apply configured tolerance checks to financial variances."""
        
        # Load tolerance configuration (simplified - would normally load from DB)
        amount_tolerance_ok = (
            financial_summary['net_amount_variance'] <= 
            financial_summary['total_po_amount'] * self.amount_tolerance_percentage
        )
        
        quantity_tolerance_ok = (
            financial_summary['net_quantity_variance'] <= 
            financial_summary['total_po_quantity'] * self.quantity_tolerance_percentage
        ) if financial_summary['total_po_quantity'] > 0 else True
        
        return {
            'amount_within_tolerance': amount_tolerance_ok,
            'quantity_within_tolerance': quantity_tolerance_ok
        }
    
    def _make_approval_decision(
        self,
        confidence: Decimal,
        tolerance_results: Dict[str, bool],
        line_matches: List[LineItemMatch]
    ) -> Tuple[bool, bool, List[str]]:
        """Make final approval decision based on confidence and tolerance checks."""
        
        exceptions = []
        
        # Check for exception conditions
        unmatched_lines = [match for match in line_matches if not match.is_matched]
        if unmatched_lines:
            exceptions.append(f"{len(unmatched_lines)} unmatched invoice lines")
        
        high_variance_lines = [
            match for match in line_matches 
            if match.is_matched and not match.variance_within_tolerance
        ]
        if high_variance_lines:
            exceptions.append(f"{len(high_variance_lines)} lines with high variance")
        
        if not tolerance_results['amount_within_tolerance']:
            exceptions.append("Total amount exceeds tolerance")
        
        if not tolerance_results['quantity_within_tolerance']:
            exceptions.append("Total quantity exceeds tolerance")
        
        # Decision logic
        auto_approved = (
            confidence >= self.auto_approve_threshold and
            not exceptions and
            all(tolerance_results.values())
        )
        
        requires_review = (
            confidence >= self.manual_review_threshold and
            not auto_approved
        )
        
        return auto_approved, requires_review, exceptions
    
    async def _save_three_way_match_result(
        self, 
        result: ThreeWayMatchResult, 
        db: AsyncSession
    ) -> None:
        """Save 3-way match result to database with complete audit trail."""
        
        try:
            # Create primary match result
            match_result = MatchResult(
                tenant_id=self.tenant_id,
                invoice_id=result.invoice_id,
                purchase_order_id=result.po_id,
                receipt_id=result.receipt_ids[0] if result.receipt_ids else None,
                match_type=MatchType.EXACT if result.match_type == ThreeWayMatchType.PERFECT_MATCH else MatchType.FUZZY,
                confidence_score=result.overall_confidence,
                match_status=MatchStatus.APPROVED if result.auto_approved else MatchStatus.PENDING,
                criteria_met={
                    'three_way_match_type': result.match_type.value,
                    'line_matches_count': len(result.line_matches),
                    'amount_within_tolerance': result.amount_within_tolerance,
                    'quantity_within_tolerance': result.quantity_within_tolerance
                },
                auto_approved=result.auto_approved,
                requires_review=result.requires_review,
                amount_variance=result.net_amount_variance,
                quantity_variance=result.net_quantity_variance,
                matched_by="3-way-system"
            )
            
            db.add(match_result)
            await db.flush()
            
            # Create detailed audit log
            audit_data = {
                'three_way_match_result': {
                    'match_type': result.match_type.value,
                    'overall_confidence': str(result.overall_confidence),
                    'line_matches_summary': {
                        'total_lines': len(result.line_matches),
                        'matched_lines': sum(1 for m in result.line_matches if m.is_matched),
                        'within_tolerance': sum(1 for m in result.line_matches if m.variance_within_tolerance)
                    },
                    'financial_summary': {
                        'po_amount': str(result.total_po_amount),
                        'invoice_amount': str(result.total_invoice_amount),
                        'receipt_amount': str(result.total_receipt_amount),
                        'amount_variance': str(result.net_amount_variance),
                        'quantity_variance': str(result.net_quantity_variance)
                    },
                    'approval_decision': {
                        'auto_approved': result.auto_approved,
                        'requires_review': result.requires_review,
                        'exceptions': result.exception_items
                    }
                }
            }
            
            import hashlib
            import json
            
            audit_hash = hashlib.sha256(
                json.dumps(audit_data, sort_keys=True, default=str).encode()
            ).hexdigest()
            
            audit_log = MatchAuditLog(
                tenant_id=self.tenant_id,
                match_result_id=match_result.id,
                event_type="match_created",
                event_description=f"3-way match completed: {result.match_type.value}",
                decision_factors=audit_data,
                algorithm_version=result.matching_algorithm_version,
                confidence_breakdown={'overall_confidence': str(result.overall_confidence)},
                event_hash=audit_hash
            )
            
            db.add(audit_log)
            await db.commit()
            
            logger.info(f"3-way match result saved for invoice {result.invoice_id}")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to save 3-way match result: {e}")
            raise


# Service factory function
async def create_three_way_matcher(tenant_id: UUID) -> ThreeWayMatcher:
    """Create a 3-way matcher instance for a tenant."""
    return ThreeWayMatcher(tenant_id)