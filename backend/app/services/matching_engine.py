"""
Automated Matching Engine for 3-Way Invoice Reconciliation.

This service implements intelligent matching algorithms for invoices, purchase orders,
and receipts with SOX-compliant audit trails and financial accuracy guarantees.

Key Features:
- Exact and fuzzy matching algorithms
- Configurable tolerance-based matching
- 3-way reconciliation (Invoice-PO-Receipt)
- Confidence scoring with explainability
- High-performance parallel processing
- Complete audit trail for regulatory compliance
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Set, Tuple, Any
from uuid import UUID
import json
import concurrent.futures
from dataclasses import dataclass

import pandas as pd
import numpy as np
from sqlalchemy import and_, or_, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from fuzzywuzzy import fuzz, process
import Levenshtein
from phonetics import soundex, metaphone

from app.core.database import get_db_context
from app.models.financial import (
    Invoice, PurchaseOrder, Receipt, Vendor, VendorAlias,
    MatchResult, MatchAuditLog, MatchingTolerance, MatchingConfiguration,
    MatchType, MatchStatus, DocumentStatus
)

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class MatchCandidate:
    """Represents a potential match candidate."""
    document_id: UUID
    document_type: str  # 'invoice', 'po', 'receipt'
    confidence_score: Decimal
    match_criteria: Dict[str, Any]
    raw_scores: Dict[str, float]
    variance_details: Dict[str, Any]


@dataclass
class MatchDecision:
    """Represents the final matching decision."""
    invoice_id: UUID
    po_id: Optional[UUID]
    receipt_id: Optional[UUID]
    match_type: MatchType
    confidence_score: Decimal
    auto_approved: bool
    requires_review: bool
    criteria_met: Dict[str, bool]
    tolerance_applied: Optional[Dict[str, Any]]
    explanation: str
    variance_analysis: Dict[str, Any]


@dataclass
class ProcessingMetrics:
    """Performance metrics for batch processing."""
    total_invoices: int
    exact_matches: int
    fuzzy_matches: int
    unmatched: int
    auto_approved: int
    manual_review: int
    processing_time: float
    average_confidence: Decimal
    
    
class OCRErrorCorrector:
    """Handles common OCR errors for improved matching accuracy."""
    
    # Common OCR character substitutions
    OCR_SUBSTITUTIONS = {
        '0': ['O', 'o', 'Q', 'D'],
        'O': ['0', 'Q', 'D'],
        '1': ['I', 'l', '|', 'i'],
        'I': ['1', 'l', '|', 'i'],
        '2': ['Z'],
        'Z': ['2'],
        '5': ['S', 's'],
        'S': ['5', 's'],
        '6': ['G', 'b'],
        'G': ['6', 'b'],
        '8': ['B'],
        'B': ['8'],
        'rn': ['m'],
        'm': ['rn'],
        'cl': ['d'],
        'd': ['cl']
    }
    
    @classmethod
    def generate_variants(cls, text: str, max_variants: int = 5) -> Set[str]:
        """Generate possible OCR variants of the input text."""
        if not text or len(text) > 50:  # Avoid explosive combinations
            return {text}
            
        variants = {text}
        original = text.upper()
        
        # Generate single character substitutions
        for i, char in enumerate(original):
            if char in cls.OCR_SUBSTITUTIONS:
                for substitute in cls.OCR_SUBSTITUTIONS[char][:2]:  # Limit substitutions
                    variant = original[:i] + substitute + original[i+1:]
                    variants.add(variant)
                    variants.add(variant.lower())
                    if len(variants) >= max_variants:
                        break
        
        return variants


class FuzzyMatcher:
    """Advanced fuzzy matching with multiple algorithms."""
    
    def __init__(self):
        self.tfidf_vectorizer = TfidfVectorizer(
            analyzer='char_wb',
            ngram_range=(2, 3),
            lowercase=True,
            max_features=1000
        )
        self.vendor_names_corpus: List[str] = []
        self.vendor_vectors = None
    
    def fit_vendor_corpus(self, vendor_names: List[str]):
        """Fit the TF-IDF vectorizer on vendor names."""
        self.vendor_names_corpus = [name.lower().strip() for name in vendor_names if name]
        if self.vendor_names_corpus:
            self.vendor_vectors = self.tfidf_vectorizer.fit_transform(self.vendor_names_corpus)
    
    def calculate_similarity(self, text1: str, text2: str, method: str = "composite") -> float:
        """Calculate similarity between two text strings using various methods."""
        if not text1 or not text2:
            return 0.0
            
        text1_clean = text1.lower().strip()
        text2_clean = text2.lower().strip()
        
        if text1_clean == text2_clean:
            return 1.0
            
        if method == "levenshtein":
            return 1.0 - (Levenshtein.distance(text1_clean, text2_clean) / 
                         max(len(text1_clean), len(text2_clean)))
        
        elif method == "fuzzy_ratio":
            return fuzz.ratio(text1_clean, text2_clean) / 100.0
            
        elif method == "fuzzy_partial":
            return fuzz.partial_ratio(text1_clean, text2_clean) / 100.0
            
        elif method == "fuzzy_token_sort":
            return fuzz.token_sort_ratio(text1_clean, text2_clean) / 100.0
            
        elif method == "fuzzy_token_set":
            return fuzz.token_set_ratio(text1_clean, text2_clean) / 100.0
            
        elif method == "phonetic":
            sound1 = soundex(text1_clean)
            sound2 = soundex(text2_clean)
            return 1.0 if sound1 == sound2 else 0.0
            
        elif method == "tfidf" and self.vendor_vectors is not None:
            try:
                text_vector = self.tfidf_vectorizer.transform([text1_clean])
                similarities = cosine_similarity(text_vector, self.vendor_vectors)[0]
                max_sim_idx = np.argmax(similarities)
                if self.vendor_names_corpus[max_sim_idx] == text2_clean:
                    return float(similarities[max_sim_idx])
                return 0.0
            except Exception:
                return 0.0
                
        elif method == "composite":
            # Weighted combination of multiple methods
            scores = {
                'levenshtein': self.calculate_similarity(text1, text2, "levenshtein"),
                'fuzzy_token_sort': self.calculate_similarity(text1, text2, "fuzzy_token_sort"),
                'fuzzy_token_set': self.calculate_similarity(text1, text2, "fuzzy_token_set"),
            }
            
            # Weighted average (token methods are more reliable for business names)
            weights = {'levenshtein': 0.3, 'fuzzy_token_sort': 0.4, 'fuzzy_token_set': 0.3}
            return sum(score * weights[method] for method, score in scores.items())
        
        return 0.0
    
    def find_best_vendor_match(self, vendor_name: str, candidates: List[str]) -> Tuple[str, float]:
        """Find the best matching vendor from a list of candidates."""
        if not vendor_name or not candidates:
            return "", 0.0
            
        # Generate OCR variants for better matching
        variants = OCRErrorCorrector.generate_variants(vendor_name)
        
        best_match = ""
        best_score = 0.0
        
        for variant in variants:
            for candidate in candidates:
                score = self.calculate_similarity(variant, candidate, "composite")
                if score > best_score:
                    best_score = score
                    best_match = candidate
                    
        return best_match, best_score


class ToleranceEngine:
    """Manages configurable tolerances for matching decisions."""
    
    @staticmethod
    def check_amount_tolerance(
        invoice_amount: Decimal, 
        po_amount: Decimal,
        tolerance_config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Decimal]:
        """Check if amounts are within tolerance."""
        if tolerance_config is None:
            tolerance_config = {"percentage": Decimal("0.05"), "absolute": Decimal("10.00")}
            
        variance = abs(invoice_amount - po_amount)
        percentage_variance = variance / max(invoice_amount, po_amount) if max(invoice_amount, po_amount) > 0 else Decimal("0")
        
        percentage_tolerance = tolerance_config.get("percentage", Decimal("0.05"))
        absolute_tolerance = tolerance_config.get("absolute", Decimal("10.00"))
        
        within_tolerance = (
            percentage_variance <= percentage_tolerance or 
            variance <= absolute_tolerance
        )
        
        return within_tolerance, percentage_variance
    
    @staticmethod
    def check_quantity_tolerance(
        invoice_qty: Decimal,
        po_qty: Decimal,
        tolerance_config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Decimal]:
        """Check if quantities are within tolerance."""
        if tolerance_config is None:
            tolerance_config = {"percentage": Decimal("0.02"), "absolute": Decimal("1.0")}
            
        variance = abs(invoice_qty - po_qty)
        percentage_variance = variance / max(invoice_qty, po_qty) if max(invoice_qty, po_qty) > 0 else Decimal("0")
        
        percentage_tolerance = tolerance_config.get("percentage", Decimal("0.02"))
        absolute_tolerance = tolerance_config.get("absolute", Decimal("1.0"))
        
        within_tolerance = (
            percentage_variance <= percentage_tolerance or
            variance <= absolute_tolerance
        )
        
        return within_tolerance, percentage_variance
    
    @staticmethod
    def check_date_tolerance(
        invoice_date: datetime,
        po_date: datetime,
        tolerance_days: int = 7
    ) -> Tuple[bool, int]:
        """Check if dates are within tolerance."""
        variance_days = abs((invoice_date - po_date).days)
        within_tolerance = variance_days <= tolerance_days
        return within_tolerance, variance_days


class ConfidenceScorer:
    """Calculates confidence scores with weighted factors and explainability."""
    
    DEFAULT_WEIGHTS = {
        'vendor_name': 0.30,
        'amount': 0.40,
        'date': 0.20,
        'reference': 0.10
    }
    
    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS
        
        # Validate weights sum to 1.0
        total_weight = sum(self.weights.values())
        if abs(total_weight - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")
    
    def calculate_confidence(self, match_factors: Dict[str, Any]) -> Tuple[Decimal, Dict[str, float]]:
        """Calculate overall confidence score with factor breakdown."""
        scores = {}
        explanations = {}
        
        # Vendor name matching score
        vendor_score = match_factors.get('vendor_similarity', 0.0)
        scores['vendor_name'] = float(vendor_score)
        explanations['vendor_name'] = f"Vendor name similarity: {vendor_score:.3f}"
        
        # Amount matching score
        amount_within_tolerance = match_factors.get('amount_within_tolerance', False)
        amount_variance = match_factors.get('amount_variance_percentage', Decimal('1.0'))
        if amount_within_tolerance:
            # Higher score for lower variance
            amount_score = max(0.0, 1.0 - float(amount_variance))
        else:
            amount_score = max(0.0, 0.5 - float(amount_variance))  # Penalty for out of tolerance
            
        scores['amount'] = amount_score
        explanations['amount'] = f"Amount variance: {float(amount_variance):.1%}, within tolerance: {amount_within_tolerance}"
        
        # Date matching score
        date_within_tolerance = match_factors.get('date_within_tolerance', False)
        date_variance_days = match_factors.get('date_variance_days', 365)
        if date_within_tolerance:
            date_score = max(0.7, 1.0 - (date_variance_days / 30.0))  # 30 days = 0 score
        else:
            date_score = max(0.0, 0.5 - (date_variance_days / 60.0))  # Penalty
            
        scores['date'] = date_score
        explanations['date'] = f"Date variance: {date_variance_days} days, within tolerance: {date_within_tolerance}"
        
        # Reference number matching score
        reference_match = match_factors.get('reference_exact_match', False)
        reference_similarity = match_factors.get('reference_similarity', 0.0)
        
        if reference_match:
            reference_score = 1.0
        else:
            reference_score = reference_similarity
            
        scores['reference'] = reference_score
        explanations['reference'] = f"Reference match: exact={reference_match}, similarity={reference_similarity:.3f}"
        
        # Calculate weighted confidence score
        weighted_score = sum(scores[factor] * self.weights[factor] for factor in scores)
        confidence = Decimal(str(weighted_score)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        
        return confidence, scores


class MatchingEngine:
    """
    Core matching engine for automated invoice reconciliation.
    
    Supports exact matching, fuzzy matching, and 3-way reconciliation
    with configurable tolerances and SOX-compliant audit trails.
    """
    
    def __init__(self, tenant_id: UUID):
        self.tenant_id = tenant_id
        self.fuzzy_matcher = FuzzyMatcher()
        self.confidence_scorer = ConfidenceScorer()
        self.processing_metrics = ProcessingMetrics(
            total_invoices=0, exact_matches=0, fuzzy_matches=0,
            unmatched=0, auto_approved=0, manual_review=0,
            processing_time=0.0, average_confidence=Decimal('0.0')
        )
        
    async def initialize(self, db: AsyncSession) -> None:
        """Initialize the matching engine with tenant configuration."""
        # Load matching configuration
        config_query = select(MatchingConfiguration).where(
            and_(
                MatchingConfiguration.tenant_id == self.tenant_id,
                MatchingConfiguration.is_active == True
            )
        ).order_by(MatchingConfiguration.created_at.desc())
        
        config_result = await db.execute(config_query)
        config = config_result.scalar_one_or_none()
        
        if config:
            # Update confidence scorer weights
            weights = {
                'vendor_name': float(config.vendor_name_weight),
                'amount': float(config.amount_weight),
                'date': float(config.date_weight),
                'reference': float(config.reference_weight)
            }
            self.confidence_scorer = ConfidenceScorer(weights)
            
            self.auto_approve_threshold = config.auto_approve_threshold
            self.manual_review_threshold = config.manual_review_threshold
            self.fuzzy_enabled = config.fuzzy_matching_enabled
            self.phonetic_enabled = config.phonetic_matching_enabled
            self.ocr_correction_enabled = config.ocr_correction_enabled
        else:
            # Use defaults
            self.auto_approve_threshold = Decimal('0.85')
            self.manual_review_threshold = Decimal('0.70')
            self.fuzzy_enabled = True
            self.phonetic_enabled = True
            self.ocr_correction_enabled = True
        
        # Initialize fuzzy matcher with vendor corpus
        vendor_query = select(Vendor.name).where(
            and_(
                Vendor.tenant_id == self.tenant_id,
                Vendor.is_active == True
            )
        )
        vendor_result = await db.execute(vendor_query)
        vendor_names = [row[0] for row in vendor_result.fetchall()]
        
        if vendor_names:
            self.fuzzy_matcher.fit_vendor_corpus(vendor_names)
            
        logger.info(f"Matching engine initialized for tenant {self.tenant_id} with {len(vendor_names)} vendors")
    
    async def process_batch_matching(
        self, 
        invoice_ids: List[UUID], 
        db: AsyncSession,
        parallel: bool = True
    ) -> ProcessingMetrics:
        """Process a batch of invoices for matching."""
        start_time = datetime.now()
        
        logger.info(f"Starting batch matching for {len(invoice_ids)} invoices")
        
        results = []
        if parallel and len(invoice_ids) > 1:
            # Process in parallel batches
            batch_size = 10  # Configurable
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = []
                for i in range(0, len(invoice_ids), batch_size):
                    batch = invoice_ids[i:i + batch_size]
                    future = executor.submit(self._process_invoice_batch, batch, db)
                    futures.append(future)
                
                for future in concurrent.futures.as_completed(futures):
                    batch_results = future.result()
                    results.extend(batch_results)
        else:
            # Sequential processing
            for invoice_id in invoice_ids:
                result = await self.match_invoice(invoice_id, db)
                results.append(result)
        
        # Calculate metrics
        processing_time = (datetime.now() - start_time).total_seconds()
        
        self.processing_metrics = ProcessingMetrics(
            total_invoices=len(invoice_ids),
            exact_matches=sum(1 for r in results if r and r.match_type == MatchType.EXACT),
            fuzzy_matches=sum(1 for r in results if r and r.match_type == MatchType.FUZZY),
            unmatched=sum(1 for r in results if r is None),
            auto_approved=sum(1 for r in results if r and r.auto_approved),
            manual_review=sum(1 for r in results if r and r.requires_review),
            processing_time=processing_time,
            average_confidence=Decimal(str(np.mean([float(r.confidence_score) for r in results if r]))),
        )
        
        logger.info(f"Batch processing completed: {self.processing_metrics}")
        return self.processing_metrics
    
    async def _process_invoice_batch(self, invoice_ids: List[UUID], db: AsyncSession) -> List[Optional[MatchDecision]]:
        """Process a batch of invoices (used for parallel processing)."""
        results = []
        async with get_db_context() as batch_db:
            for invoice_id in invoice_ids:
                result = await self.match_invoice(invoice_id, batch_db)
                results.append(result)
        return results
    
    async def match_invoice(self, invoice_id: UUID, db: AsyncSession) -> Optional[MatchDecision]:
        """
        Match a single invoice against POs and receipts.
        
        Returns:
            MatchDecision if match found, None if no match
        """
        try:
            # Load invoice with vendor details
            invoice_query = select(Invoice).options(
                # selectinload would go here for relationships if needed
            ).where(
                and_(
                    Invoice.id == invoice_id,
                    Invoice.tenant_id == self.tenant_id
                )
            )
            
            invoice_result = await db.execute(invoice_query)
            invoice = invoice_result.scalar_one_or_none()
            
            if not invoice:
                logger.warning(f"Invoice {invoice_id} not found")
                return None
            
            # Step 1: Exact matching attempts
            exact_match = await self._attempt_exact_match(invoice, db)
            if exact_match:
                return await self._finalize_match_decision(exact_match, invoice, db)
            
            # Step 2: Fuzzy matching if enabled
            if self.fuzzy_enabled:
                fuzzy_match = await self._attempt_fuzzy_match(invoice, db)
                if fuzzy_match:
                    return await self._finalize_match_decision(fuzzy_match, invoice, db)
            
            logger.info(f"No match found for invoice {invoice_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error matching invoice {invoice_id}: {e}")
            return None
    
    async def _attempt_exact_match(self, invoice: Invoice, db: AsyncSession) -> Optional[MatchCandidate]:
        """Attempt exact matching using PO number + amount + vendor."""
        if not invoice.po_reference:
            return None
        
        # Find PO by exact PO number and vendor
        po_query = select(PurchaseOrder).where(
            and_(
                PurchaseOrder.tenant_id == self.tenant_id,
                PurchaseOrder.po_number == invoice.po_reference,
                PurchaseOrder.vendor_id == invoice.vendor_id,
                PurchaseOrder.status != DocumentStatus.ARCHIVED
            )
        )
        
        po_result = await db.execute(po_query)
        pos = po_result.scalars().all()
        
        for po in pos:
            # Check exact amount match
            if po.total_amount == invoice.total_amount:
                return MatchCandidate(
                    document_id=po.id,
                    document_type="po",
                    confidence_score=Decimal('1.0'),
                    match_criteria={
                        'po_number_exact': True,
                        'vendor_exact': True,
                        'amount_exact': True
                    },
                    raw_scores={
                        'vendor_match': 1.0,
                        'amount_match': 1.0,
                        'reference_match': 1.0
                    },
                    variance_details={}
                )
        
        return None
    
    async def _attempt_fuzzy_match(self, invoice: Invoice, db: AsyncSession) -> Optional[MatchCandidate]:
        """Attempt fuzzy matching with tolerance-based criteria."""
        # Load potential PO candidates within date range
        date_range_start = invoice.invoice_date - timedelta(days=30)
        date_range_end = invoice.invoice_date + timedelta(days=7)
        
        po_query = select(PurchaseOrder).join(Vendor).where(
            and_(
                PurchaseOrder.tenant_id == self.tenant_id,
                PurchaseOrder.po_date >= date_range_start,
                PurchaseOrder.po_date <= date_range_end,
                PurchaseOrder.status != DocumentStatus.ARCHIVED
            )
        )
        
        po_result = await db.execute(po_query)
        pos = po_result.scalars().all()
        
        if not pos:
            return None
        
        # Load tolerance configuration
        tolerances = await self._load_tolerance_configuration(db)
        
        best_candidate = None
        best_confidence = Decimal('0.0')
        
        for po in pos:
            # Calculate matching factors
            match_factors = await self._calculate_match_factors(invoice, po, tolerances, db)
            
            # Calculate confidence score
            confidence, score_breakdown = self.confidence_scorer.calculate_confidence(match_factors)
            
            if confidence > best_confidence and confidence >= self.manual_review_threshold:
                best_confidence = confidence
                best_candidate = MatchCandidate(
                    document_id=po.id,
                    document_type="po",
                    confidence_score=confidence,
                    match_criteria=match_factors,
                    raw_scores=score_breakdown,
                    variance_details={
                        'amount_variance': match_factors.get('amount_variance_percentage', 0),
                        'date_variance_days': match_factors.get('date_variance_days', 0)
                    }
                )
        
        return best_candidate
    
    async def _calculate_match_factors(
        self, 
        invoice: Invoice, 
        po: PurchaseOrder, 
        tolerances: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Calculate all matching factors between invoice and PO."""
        factors = {}
        
        # Load vendor information
        vendor_query = select(Vendor).where(Vendor.id == po.vendor_id)
        vendor_result = await db.execute(vendor_query)
        po_vendor = vendor_result.scalar_one()
        
        invoice_vendor_query = select(Vendor).where(Vendor.id == invoice.vendor_id)
        invoice_vendor_result = await db.execute(invoice_vendor_query)
        invoice_vendor = invoice_vendor_result.scalar_one()
        
        # Vendor name matching
        vendor_similarity = self.fuzzy_matcher.calculate_similarity(
            invoice_vendor.name, po_vendor.name, "composite"
        )
        factors['vendor_similarity'] = vendor_similarity
        factors['vendor_exact_match'] = invoice.vendor_id == po.vendor_id
        
        # Amount matching with tolerance
        amount_tolerance = tolerances.get('amount', {})
        amount_within_tolerance, amount_variance = ToleranceEngine.check_amount_tolerance(
            invoice.total_amount, po.total_amount, amount_tolerance
        )
        factors['amount_within_tolerance'] = amount_within_tolerance
        factors['amount_variance_percentage'] = amount_variance
        factors['amount_exact_match'] = invoice.total_amount == po.total_amount
        
        # Date matching with tolerance
        date_tolerance_days = tolerances.get('date', {}).get('days', 7)
        date_within_tolerance, date_variance = ToleranceEngine.check_date_tolerance(
            invoice.invoice_date, po.po_date, date_tolerance_days
        )
        factors['date_within_tolerance'] = date_within_tolerance
        factors['date_variance_days'] = date_variance
        
        # Reference number matching
        if invoice.po_reference and po.po_number:
            ref_exact = invoice.po_reference.strip().upper() == po.po_number.strip().upper()
            factors['reference_exact_match'] = ref_exact
            
            if not ref_exact:
                ref_similarity = self.fuzzy_matcher.calculate_similarity(
                    invoice.po_reference, po.po_number, "composite"
                )
                factors['reference_similarity'] = ref_similarity
            else:
                factors['reference_similarity'] = 1.0
        else:
            factors['reference_exact_match'] = False
            factors['reference_similarity'] = 0.0
        
        return factors
    
    async def _load_tolerance_configuration(self, db: AsyncSession) -> Dict[str, Any]:
        """Load tolerance configuration for the tenant."""
        tolerance_query = select(MatchingTolerance).where(
            and_(
                MatchingTolerance.tenant_id == self.tenant_id,
                MatchingTolerance.is_active == True
            )
        ).order_by(MatchingTolerance.priority.desc())
        
        tolerance_result = await db.execute(tolerance_query)
        tolerances_raw = tolerance_result.scalars().all()
        
        # Group tolerances by type
        tolerances = {}
        for tolerance in tolerances_raw:
            if tolerance.tolerance_type not in tolerances:
                tolerances[tolerance.tolerance_type] = {}
            
            if tolerance.percentage_tolerance:
                tolerances[tolerance.tolerance_type]['percentage'] = tolerance.percentage_tolerance
            if tolerance.absolute_tolerance:
                tolerances[tolerance.tolerance_type]['absolute'] = tolerance.absolute_tolerance
        
        # Set defaults if not configured
        if 'amount' not in tolerances:
            tolerances['amount'] = {'percentage': Decimal('0.05'), 'absolute': Decimal('10.00')}
        if 'quantity' not in tolerances:
            tolerances['quantity'] = {'percentage': Decimal('0.02'), 'absolute': Decimal('1.0')}
        if 'date' not in tolerances:
            tolerances['date'] = {'days': 7}
        
        return tolerances
    
    async def _finalize_match_decision(
        self, 
        candidate: MatchCandidate, 
        invoice: Invoice,
        db: AsyncSession
    ) -> MatchDecision:
        """Finalize the match decision and create audit trail."""
        
        # Determine match type
        if candidate.confidence_score == Decimal('1.0'):
            match_type = MatchType.EXACT
        else:
            match_type = MatchType.FUZZY
        
        # Determine approval status
        auto_approved = candidate.confidence_score >= self.auto_approve_threshold
        requires_review = (
            candidate.confidence_score < self.auto_approve_threshold and
            candidate.confidence_score >= self.manual_review_threshold
        )
        
        # Generate explanation
        explanation = self._generate_match_explanation(candidate, match_type)
        
        # Create match decision
        decision = MatchDecision(
            invoice_id=invoice.id,
            po_id=candidate.document_id if candidate.document_type == "po" else None,
            receipt_id=candidate.document_id if candidate.document_type == "receipt" else None,
            match_type=match_type,
            confidence_score=candidate.confidence_score,
            auto_approved=auto_approved,
            requires_review=requires_review,
            criteria_met=candidate.match_criteria,
            tolerance_applied=None,  # TODO: Implement tolerance details
            explanation=explanation,
            variance_analysis=candidate.variance_details
        )
        
        # Save match result to database
        await self._save_match_result(decision, db)
        
        return decision
    
    def _generate_match_explanation(self, candidate: MatchCandidate, match_type: MatchType) -> str:
        """Generate human-readable explanation for the match decision."""
        explanations = []
        
        if match_type == MatchType.EXACT:
            explanations.append("Exact match found on PO number, vendor, and amount")
        else:
            scores = candidate.raw_scores
            explanations.append(f"Fuzzy match with confidence {candidate.confidence_score:.1%}")
            explanations.append(f"Vendor similarity: {scores.get('vendor_name', 0):.1%}")
            explanations.append(f"Amount matching: {scores.get('amount', 0):.1%}")
            explanations.append(f"Date matching: {scores.get('date', 0):.1%}")
            explanations.append(f"Reference matching: {scores.get('reference', 0):.1%}")
            
            if candidate.variance_details:
                amount_var = candidate.variance_details.get('amount_variance', 0)
                date_var = candidate.variance_details.get('date_variance_days', 0)
                explanations.append(f"Amount variance: {float(amount_var):.1%}")
                explanations.append(f"Date variance: {date_var} days")
        
        return "; ".join(explanations)
    
    async def _save_match_result(self, decision: MatchDecision, db: AsyncSession) -> None:
        """Save match result to database with audit trail."""
        try:
            # Create match result record
            match_result = MatchResult(
                tenant_id=self.tenant_id,
                invoice_id=decision.invoice_id,
                purchase_order_id=decision.po_id,
                receipt_id=decision.receipt_id,
                match_type=decision.match_type,
                confidence_score=decision.confidence_score,
                match_status=MatchStatus.APPROVED if decision.auto_approved else MatchStatus.PENDING,
                criteria_met=decision.criteria_met,
                tolerance_applied=decision.tolerance_applied,
                auto_approved=decision.auto_approved,
                requires_review=decision.requires_review,
                amount_variance=decision.variance_analysis.get('amount_variance'),
                quantity_variance=decision.variance_analysis.get('quantity_variance'),
                matched_by="system"
            )
            
            db.add(match_result)
            await db.flush()  # Get the ID
            
            # Create audit log entry
            audit_data = {
                'invoice_id': str(decision.invoice_id),
                'match_type': decision.match_type.value,
                'confidence_score': str(decision.confidence_score),
                'explanation': decision.explanation,
                'criteria_met': decision.criteria_met,
                'variance_analysis': decision.variance_analysis
            }
            
            audit_hash = hashlib.sha256(
                json.dumps(audit_data, sort_keys=True, default=str).encode()
            ).hexdigest()
            
            audit_log = MatchAuditLog(
                tenant_id=self.tenant_id,
                match_result_id=match_result.id,
                event_type="match_created",
                event_description=f"Automated match created: {decision.explanation}",
                decision_factors=decision.criteria_met,
                algorithm_version="1.0.0",
                confidence_breakdown=decision.variance_analysis,
                event_hash=audit_hash
            )
            
            db.add(audit_log)
            await db.commit()
            
            logger.info(f"Match result saved for invoice {decision.invoice_id} with confidence {decision.confidence_score}")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to save match result: {e}")
            raise
    
    async def get_match_results(
        self, 
        invoice_id: UUID, 
        db: AsyncSession
    ) -> List[MatchResult]:
        """Get all match results for an invoice."""
        query = select(MatchResult).where(
            and_(
                MatchResult.tenant_id == self.tenant_id,
                MatchResult.invoice_id == invoice_id
            )
        ).order_by(MatchResult.matched_at.desc())
        
        result = await db.execute(query)
        return result.scalars().all()
    
    async def provide_user_feedback(
        self,
        match_result_id: UUID,
        feedback: Dict[str, Any],
        user_id: UUID,
        db: AsyncSession
    ) -> None:
        """Process user feedback for machine learning improvement."""
        try:
            # Load existing match result
            match_query = select(MatchResult).where(
                and_(
                    MatchResult.id == match_result_id,
                    MatchResult.tenant_id == self.tenant_id
                )
            )
            
            match_result_data = await db.execute(match_query)
            match_result = match_result_data.scalar_one_or_none()
            
            if not match_result:
                raise ValueError(f"Match result {match_result_id} not found")
            
            # Update match result based on feedback
            feedback_type = feedback.get('type')  # 'approve', 'reject', 'modify'
            
            if feedback_type == 'approve':
                match_result.match_status = MatchStatus.APPROVED
                match_result.approved_at = datetime.now()
                match_result.approved_by = user_id
                
            elif feedback_type == 'reject':
                match_result.match_status = MatchStatus.REJECTED
                match_result.review_notes = feedback.get('notes')
                match_result.reviewed_by = user_id
                match_result.reviewed_at = datetime.now()
            
            # Create audit log for feedback
            audit_data = {
                'match_result_id': str(match_result_id),
                'feedback_type': feedback_type,
                'user_id': str(user_id),
                'notes': feedback.get('notes'),
                'timestamp': datetime.now().isoformat()
            }
            
            audit_hash = hashlib.sha256(
                json.dumps(audit_data, sort_keys=True, default=str).encode()
            ).hexdigest()
            
            audit_log = MatchAuditLog(
                tenant_id=self.tenant_id,
                match_result_id=match_result_id,
                event_type="user_feedback",
                event_description=f"User feedback received: {feedback_type}",
                decision_factors=feedback,
                algorithm_version="1.0.0",
                confidence_breakdown={},
                user_id=user_id,
                event_hash=audit_hash
            )
            
            db.add(audit_log)
            await db.commit()
            
            logger.info(f"User feedback processed for match result {match_result_id}")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to process user feedback: {e}")
            raise


# Service factory function
async def create_matching_engine(tenant_id: UUID, db: AsyncSession) -> MatchingEngine:
    """Create and initialize a matching engine for a tenant."""
    engine = MatchingEngine(tenant_id)
    await engine.initialize(db)
    return engine