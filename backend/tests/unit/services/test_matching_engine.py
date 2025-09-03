"""
Unit tests for the automated matching engine.

Tests cover all major functionality including exact matching, fuzzy matching,
confidence scoring, tolerance checking, and 3-way reconciliation.

Test Coverage:
- Exact matching algorithms
- Fuzzy matching with OCR correction
- Confidence scoring with weighted factors
- Tolerance configuration and application
- 3-way matching scenarios
- Performance optimization
- Error handling and edge cases
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import Mock, AsyncMock, patch

import pandas as pd
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.matching_engine import (
    MatchingEngine, FuzzyMatcher, OCRErrorCorrector, ToleranceEngine, 
    ConfidenceScorer, MatchCandidate, MatchDecision, ProcessingMetrics
)
from app.services.three_way_matching import ThreeWayMatcher, ThreeWayMatchResult, LineItemMatch
from app.models.financial import (
    Invoice, PurchaseOrder, Receipt, Vendor, MatchResult, MatchingConfiguration,
    MatchType, MatchStatus, DocumentStatus, CurrencyCode
)


class TestOCRErrorCorrector:
    """Test OCR error correction functionality."""
    
    def test_generate_variants_basic(self):
        """Test basic OCR variant generation."""
        variants = OCRErrorCorrector.generate_variants("0123")
        
        # Should include original and common substitutions
        assert "0123" in variants
        assert "O123" in variants  # 0 -> O
        assert "0I23" in variants  # 1 -> I
        
        # Should not be excessive
        assert len(variants) <= 10
    
    def test_generate_variants_edge_cases(self):
        """Test edge cases for variant generation."""
        # Empty string
        variants = OCRErrorCorrector.generate_variants("")
        assert variants == {""}
        
        # Very long string - should limit variants
        long_string = "A" * 100
        variants = OCRErrorCorrector.generate_variants(long_string)
        assert long_string in variants
        assert len(variants) <= 10
        
        # No OCR-prone characters
        variants = OCRErrorCorrector.generate_variants("ABCD")
        assert variants == {"ABCD"}
    
    def test_common_ocr_substitutions(self):
        """Test specific OCR character substitutions."""
        # Test 0/O confusion
        variants = OCRErrorCorrector.generate_variants("A0B")
        assert "AOB" in variants
        assert "AQB" in variants
        
        # Test 1/I confusion
        variants = OCRErrorCorrector.generate_variants("A1B")
        assert "AIB" in variants
        assert "AlB" in variants
        
        # Test 5/S confusion
        variants = OCRErrorCorrector.generate_variants("A5B")
        assert "ASB" in variants


class TestFuzzyMatcher:
    """Test fuzzy matching algorithms."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = FuzzyMatcher()
        self.vendor_names = [
            "Microsoft Corporation",
            "Apple Inc.",
            "Google LLC",
            "Amazon Web Services",
            "Oracle Corporation"
        ]
        self.matcher.fit_vendor_corpus(self.vendor_names)
    
    def test_calculate_similarity_exact_match(self):
        """Test exact string matching."""
        similarity = self.matcher.calculate_similarity(
            "Microsoft Corporation", 
            "Microsoft Corporation",
            "levenshtein"
        )
        assert similarity == 1.0
    
    def test_calculate_similarity_methods(self):
        """Test different similarity calculation methods."""
        text1 = "Microsoft Corp"
        text2 = "Microsoft Corporation"
        
        # Test different methods
        levenshtein = self.matcher.calculate_similarity(text1, text2, "levenshtein")
        fuzzy_ratio = self.matcher.calculate_similarity(text1, text2, "fuzzy_ratio")
        fuzzy_token = self.matcher.calculate_similarity(text1, text2, "fuzzy_token_sort")
        composite = self.matcher.calculate_similarity(text1, text2, "composite")
        
        # All should be reasonable similarities
        assert 0.5 < levenshtein < 1.0
        assert 0.5 < fuzzy_ratio < 1.0
        assert 0.8 < fuzzy_token < 1.0  # Token matching should be high
        assert 0.5 < composite < 1.0
    
    def test_calculate_similarity_edge_cases(self):
        """Test edge cases for similarity calculation."""
        # Empty strings
        assert self.matcher.calculate_similarity("", "", "levenshtein") == 1.0
        assert self.matcher.calculate_similarity("test", "", "levenshtein") == 0.0
        assert self.matcher.calculate_similarity("", "test", "levenshtein") == 0.0
        
        # None values
        assert self.matcher.calculate_similarity(None, "test", "levenshtein") == 0.0
        assert self.matcher.calculate_similarity("test", None, "levenshtein") == 0.0
    
    def test_find_best_vendor_match(self):
        """Test finding best vendor match from candidates."""
        best_match, score = self.matcher.find_best_vendor_match(
            "Microsoft Corp", 
            self.vendor_names
        )
        
        assert best_match == "Microsoft Corporation"
        assert score > 0.7  # Should be high similarity
    
    def test_find_best_vendor_match_with_ocr_errors(self):
        """Test vendor matching with OCR errors."""
        # Simulate OCR error: O instead of 0
        best_match, score = self.matcher.find_best_vendor_match(
            "Micr0soft Corporation",  # 0 instead of o
            self.vendor_names
        )
        
        # Should still find the correct match due to OCR correction
        assert best_match == "Microsoft Corporation"
        assert score > 0.6


class TestToleranceEngine:
    """Test tolerance checking functionality."""
    
    def test_check_amount_tolerance_within_percentage(self):
        """Test amount tolerance checking with percentage."""
        tolerance_config = {
            "percentage": Decimal("0.05"),  # 5%
            "absolute": Decimal("100.00")
        }
        
        # Within percentage tolerance
        within_tolerance, variance = ToleranceEngine.check_amount_tolerance(
            Decimal("1000.00"),
            Decimal("1020.00"),  # 2% difference
            tolerance_config
        )
        
        assert within_tolerance is True
        assert variance == Decimal("0.02")  # 2% variance
    
    def test_check_amount_tolerance_within_absolute(self):
        """Test amount tolerance checking with absolute value."""
        tolerance_config = {
            "percentage": Decimal("0.01"),  # 1%
            "absolute": Decimal("50.00")
        }
        
        # Outside percentage but within absolute tolerance
        within_tolerance, variance = ToleranceEngine.check_amount_tolerance(
            Decimal("1000.00"),
            Decimal("1030.00"),  # 3% difference, $30 absolute
            tolerance_config
        )
        
        assert within_tolerance is True  # Within absolute tolerance
        assert variance == Decimal("0.03")  # 3% variance
    
    def test_check_amount_tolerance_outside_both(self):
        """Test amount tolerance when outside both limits."""
        tolerance_config = {
            "percentage": Decimal("0.01"),  # 1%
            "absolute": Decimal("10.00")
        }
        
        # Outside both percentage and absolute tolerance
        within_tolerance, variance = ToleranceEngine.check_amount_tolerance(
            Decimal("1000.00"),
            Decimal("1100.00"),  # 10% difference, $100 absolute
            tolerance_config
        )
        
        assert within_tolerance is False
        assert variance == Decimal("0.10")  # 10% variance
    
    def test_check_quantity_tolerance(self):
        """Test quantity tolerance checking."""
        tolerance_config = {
            "percentage": Decimal("0.02"),  # 2%
            "absolute": Decimal("5.0")
        }
        
        # Within tolerance
        within_tolerance, variance = ToleranceEngine.check_quantity_tolerance(
            Decimal("100.0"),
            Decimal("101.5"),  # 1.5% difference
            tolerance_config
        )
        
        assert within_tolerance is True
        assert variance == Decimal("0.015")
    
    def test_check_date_tolerance(self):
        """Test date tolerance checking."""
        base_date = datetime(2025, 1, 1)
        close_date = datetime(2025, 1, 5)  # 4 days difference
        far_date = datetime(2025, 1, 15)   # 14 days difference
        
        # Within tolerance
        within_tolerance, variance = ToleranceEngine.check_date_tolerance(
            base_date, close_date, tolerance_days=7
        )
        assert within_tolerance is True
        assert variance == 4
        
        # Outside tolerance
        within_tolerance, variance = ToleranceEngine.check_date_tolerance(
            base_date, far_date, tolerance_days=7
        )
        assert within_tolerance is False
        assert variance == 14


class TestConfidenceScorer:
    """Test confidence scoring algorithms."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.scorer = ConfidenceScorer()
    
    def test_calculate_confidence_perfect_match(self):
        """Test confidence calculation for perfect match."""
        match_factors = {
            'vendor_similarity': 1.0,
            'amount_within_tolerance': True,
            'amount_variance_percentage': Decimal('0.0'),
            'date_within_tolerance': True,
            'date_variance_days': 0,
            'reference_exact_match': True,
            'reference_similarity': 1.0
        }
        
        confidence, breakdown = self.scorer.calculate_confidence(match_factors)
        
        # Should be very high confidence
        assert confidence >= Decimal('0.90')
        
        # Check score breakdown
        assert 'vendor_name' in breakdown
        assert 'amount' in breakdown
        assert 'date' in breakdown
        assert 'reference' in breakdown
        
        # All individual scores should be high
        assert all(score >= 0.8 for score in breakdown.values())
    
    def test_calculate_confidence_partial_match(self):
        """Test confidence calculation for partial match."""
        match_factors = {
            'vendor_similarity': 0.8,
            'amount_within_tolerance': True,
            'amount_variance_percentage': Decimal('0.03'),  # 3% variance
            'date_within_tolerance': False,
            'date_variance_days': 15,  # Outside tolerance
            'reference_exact_match': False,
            'reference_similarity': 0.6
        }
        
        confidence, breakdown = self.scorer.calculate_confidence(match_factors)
        
        # Should be moderate confidence
        assert Decimal('0.50') <= confidence <= Decimal('0.80')
        
        # Vendor and reference scores should be lower
        assert breakdown['vendor_name'] < 1.0
        assert breakdown['reference'] < 1.0
        assert breakdown['date'] < 0.8  # Date penalty
    
    def test_calculate_confidence_poor_match(self):
        """Test confidence calculation for poor match."""
        match_factors = {
            'vendor_similarity': 0.3,
            'amount_within_tolerance': False,
            'amount_variance_percentage': Decimal('0.15'),  # 15% variance
            'date_within_tolerance': False,
            'date_variance_days': 60,
            'reference_exact_match': False,
            'reference_similarity': 0.2
        }
        
        confidence, breakdown = self.scorer.calculate_confidence(match_factors)
        
        # Should be low confidence
        assert confidence <= Decimal('0.50')
        
        # All scores should be low
        assert all(score <= 0.6 for score in breakdown.values())
    
    def test_custom_weights(self):
        """Test confidence calculation with custom weights."""
        # Amount-heavy weighting
        custom_weights = {
            'vendor_name': 0.1,
            'amount': 0.7,
            'date': 0.1,
            'reference': 0.1
        }
        
        scorer = ConfidenceScorer(custom_weights)
        
        match_factors = {
            'vendor_similarity': 0.3,  # Poor vendor match
            'amount_within_tolerance': True,  # Good amount match
            'amount_variance_percentage': Decimal('0.01'),
            'date_within_tolerance': True,
            'date_variance_days': 2,
            'reference_exact_match': False,
            'reference_similarity': 0.3
        }
        
        confidence, breakdown = scorer.calculate_confidence(match_factors)
        
        # Should still have reasonable confidence due to amount weight
        assert confidence >= Decimal('0.60')


@pytest.mark.asyncio
class TestMatchingEngine:
    """Test the main matching engine functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tenant_id = uuid4()
        self.engine = MatchingEngine(self.tenant_id)
        
        # Mock database session
        self.mock_db = AsyncMock(spec=AsyncSession)
    
    async def test_initialize_with_configuration(self):
        """Test matching engine initialization with configuration."""
        # Mock configuration data
        mock_config = Mock()
        mock_config.vendor_name_weight = Decimal('0.25')
        mock_config.amount_weight = Decimal('0.45')
        mock_config.date_weight = Decimal('0.20')
        mock_config.reference_weight = Decimal('0.10')
        mock_config.auto_approve_threshold = Decimal('0.90')
        mock_config.manual_review_threshold = Decimal('0.75')
        mock_config.fuzzy_matching_enabled = True
        
        # Mock database queries
        self.mock_db.execute.return_value.scalar_one_or_none.return_value = mock_config
        self.mock_db.execute.return_value.fetchall.return_value = [
            ("Microsoft Corporation",),
            ("Apple Inc.",),
            ("Google LLC",)
        ]
        
        await self.engine.initialize(self.mock_db)
        
        # Verify configuration was loaded
        assert self.engine.auto_approve_threshold == Decimal('0.90')
        assert self.engine.manual_review_threshold == Decimal('0.75')
        assert self.engine.fuzzy_enabled is True
    
    async def test_exact_match_found(self):
        """Test successful exact matching."""
        invoice_id = uuid4()
        
        # Mock invoice
        mock_invoice = Mock()
        mock_invoice.id = invoice_id
        mock_invoice.po_reference = "PO-12345"
        mock_invoice.vendor_id = uuid4()
        mock_invoice.total_amount = Decimal('1000.00')
        mock_invoice.invoice_date = datetime.now()
        
        # Mock PO
        mock_po = Mock()
        mock_po.id = uuid4()
        mock_po.po_number = "PO-12345"
        mock_po.vendor_id = mock_invoice.vendor_id
        mock_po.total_amount = Decimal('1000.00')
        mock_po.status = DocumentStatus.PENDING
        
        # Mock database queries
        self.mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_invoice,  # Load invoice
            mock_po       # Find matching PO
        ]
        self.mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_po]
        
        # Mock the private methods
        with patch.object(self.engine, '_attempt_exact_match') as mock_exact:
            mock_candidate = MatchCandidate(
                document_id=mock_po.id,
                document_type="po",
                confidence_score=Decimal('1.0'),
                match_criteria={'po_number_exact': True, 'vendor_exact': True, 'amount_exact': True},
                raw_scores={'vendor_match': 1.0, 'amount_match': 1.0, 'reference_match': 1.0},
                variance_details={}
            )
            mock_exact.return_value = mock_candidate
            
            with patch.object(self.engine, '_finalize_match_decision') as mock_finalize:
                mock_decision = MatchDecision(
                    invoice_id=invoice_id,
                    po_id=mock_po.id,
                    receipt_id=None,
                    match_type=MatchType.EXACT,
                    confidence_score=Decimal('1.0'),
                    auto_approved=True,
                    requires_review=False,
                    criteria_met={'exact_match': True},
                    tolerance_applied=None,
                    explanation="Exact match found",
                    variance_analysis={}
                )
                mock_finalize.return_value = mock_decision
                
                result = await self.engine.match_invoice(invoice_id, self.mock_db)
                
                assert result is not None
                assert result.match_type == MatchType.EXACT
                assert result.confidence_score == Decimal('1.0')
                assert result.auto_approved is True
    
    async def test_fuzzy_match_found(self):
        """Test successful fuzzy matching."""
        invoice_id = uuid4()
        
        # Mock invoice with slightly different data
        mock_invoice = Mock()
        mock_invoice.id = invoice_id
        mock_invoice.po_reference = "PO12345"  # No dash
        mock_invoice.vendor_id = uuid4()
        mock_invoice.total_amount = Decimal('1020.00')  # Slightly different amount
        mock_invoice.invoice_date = datetime.now()
        
        # Mock database queries - no exact match
        self.mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_invoice,  # Load invoice
            None          # No exact match found
        ]
        
        # Mock fuzzy match
        with patch.object(self.engine, '_attempt_exact_match', return_value=None):
            with patch.object(self.engine, '_attempt_fuzzy_match') as mock_fuzzy:
                mock_candidate = MatchCandidate(
                    document_id=uuid4(),
                    document_type="po",
                    confidence_score=Decimal('0.85'),
                    match_criteria={'fuzzy_match': True},
                    raw_scores={'vendor_match': 0.9, 'amount_match': 0.8},
                    variance_details={'amount_variance': Decimal('0.02')}
                )
                mock_fuzzy.return_value = mock_candidate
                
                with patch.object(self.engine, '_finalize_match_decision') as mock_finalize:
                    mock_decision = MatchDecision(
                        invoice_id=invoice_id,
                        po_id=mock_candidate.document_id,
                        receipt_id=None,
                        match_type=MatchType.FUZZY,
                        confidence_score=Decimal('0.85'),
                        auto_approved=True,
                        requires_review=False,
                        criteria_met={'fuzzy_match': True},
                        tolerance_applied={'amount_tolerance': '5%'},
                        explanation="Fuzzy match with high confidence",
                        variance_analysis={'amount_variance': Decimal('0.02')}
                    )
                    mock_finalize.return_value = mock_decision
                    
                    result = await self.engine.match_invoice(invoice_id, self.mock_db)
                    
                    assert result is not None
                    assert result.match_type == MatchType.FUZZY
                    assert result.confidence_score == Decimal('0.85')
    
    async def test_no_match_found(self):
        """Test when no match is found."""
        invoice_id = uuid4()
        
        # Mock invoice
        mock_invoice = Mock()
        mock_invoice.id = invoice_id
        mock_invoice.vendor_id = uuid4()
        
        self.mock_db.execute.return_value.scalar_one_or_none.return_value = mock_invoice
        
        # Mock no matches found
        with patch.object(self.engine, '_attempt_exact_match', return_value=None):
            with patch.object(self.engine, '_attempt_fuzzy_match', return_value=None):
                result = await self.engine.match_invoice(invoice_id, self.mock_db)
                
                assert result is None
    
    async def test_batch_processing(self):
        """Test batch processing of multiple invoices."""
        invoice_ids = [uuid4() for _ in range(5)]
        
        # Mock successful processing
        with patch.object(self.engine, 'match_invoice') as mock_match:
            # Mock some successful matches and some failures
            mock_decisions = [
                MatchDecision(
                    invoice_id=invoice_ids[i],
                    po_id=uuid4(),
                    receipt_id=None,
                    match_type=MatchType.EXACT if i < 3 else MatchType.FUZZY,
                    confidence_score=Decimal('0.95') if i < 3 else Decimal('0.80'),
                    auto_approved=True,
                    requires_review=False,
                    criteria_met={},
                    tolerance_applied=None,
                    explanation=f"Match for invoice {i}",
                    variance_analysis={}
                ) if i < 4 else None  # Last one fails
                for i in range(5)
            ]
            mock_match.side_effect = mock_decisions
            
            metrics = await self.engine.process_batch_matching(
                invoice_ids, self.mock_db, parallel=False
            )
            
            assert metrics.total_invoices == 5
            assert metrics.exact_matches == 3
            assert metrics.fuzzy_matches == 1
            assert metrics.unmatched == 1
            assert metrics.processing_time > 0


@pytest.mark.asyncio 
class TestThreeWayMatcher:
    """Test 3-way matching functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tenant_id = uuid4()
        self.matcher = ThreeWayMatcher(self.tenant_id)
        self.mock_db = AsyncMock(spec=AsyncSession)
    
    async def test_perfect_three_way_match(self):
        """Test perfect 3-way match scenario."""
        invoice_id = uuid4()
        po_id = uuid4()
        receipt_id = uuid4()
        
        # Mock invoice with line items
        mock_invoice = Mock()
        mock_invoice.id = invoice_id
        mock_invoice.total_amount = Decimal('1000.00')
        mock_invoice.invoice_date = datetime.now()
        mock_invoice.invoice_lines = [
            Mock(
                id=uuid4(),
                line_number=1,
                description="Test item",
                quantity=Decimal('10'),
                unit_price=Decimal('100'),
                line_total=Decimal('1000'),
                item_code="ITEM001"
            )
        ]
        
        # Mock PO with matching data
        mock_po = Mock()
        mock_po.id = po_id
        mock_po.total_amount = Decimal('1000.00')
        mock_po.po_date = datetime.now() - timedelta(days=1)
        
        # Mock PO lines
        mock_po_line = Mock()
        mock_po_line.id = uuid4()
        mock_po_line.line_number = 1
        mock_po_line.description = "Test item"
        mock_po_line.quantity = Decimal('10')
        mock_po_line.unit_price = Decimal('100')
        mock_po_line.line_total = Decimal('1000')
        mock_po_line.item_code = "ITEM001"
        
        # Mock receipt
        mock_receipt = Mock()
        mock_receipt.id = receipt_id
        mock_receipt.total_quantity = Decimal('10')
        mock_receipt.total_value = Decimal('1000')
        mock_receipt.receipt_lines = [
            Mock(
                id=uuid4(),
                po_line_id=mock_po_line.id,
                line_number=1,
                quantity_received=Decimal('10'),
                unit_cost=Decimal('100'),
                line_value=Decimal('1000')
            )
        ]
        
        # Mock database queries
        self.mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_invoice,  # Load invoice
            mock_po,       # Find matching PO
        ]
        self.mock_db.execute.return_value.scalars.return_value.all.side_effect = [
            [],  # Invoice lines (already loaded)
            [mock_receipt],  # Related receipts
            [mock_po_line],  # PO lines
            [mock_receipt.receipt_lines[0]]  # Receipt lines
        ]
        
        # Mock other methods
        with patch.object(self.matcher, '_load_invoice_with_lines', return_value=mock_invoice):
            with patch.object(self.matcher, '_find_matching_po', return_value=mock_po):
                with patch.object(self.matcher, '_find_related_receipts', return_value=[mock_receipt]):
                    result = await self.matcher.perform_three_way_match(invoice_id, self.mock_db)
                    
                    assert result is not None
                    assert result.invoice_id == invoice_id
                    assert result.po_id == po_id
                    assert receipt_id in result.receipt_ids
                    assert result.overall_confidence >= Decimal('0.90')
                    assert result.auto_approved is True
    
    def test_line_item_matching_confidence(self):
        """Test line-level matching confidence calculation."""
        # Mock invoice line
        invoice_line = Mock()
        invoice_line.item_code = "ITEM001"
        invoice_line.description = "Test Product Alpha"
        invoice_line.quantity = Decimal('10')
        invoice_line.unit_price = Decimal('100.00')
        
        # Mock PO line - exact match
        po_line_exact = Mock()
        po_line_exact.item_code = "ITEM001"
        po_line_exact.description = "Test Product Alpha"
        po_line_exact.quantity = Decimal('10')
        po_line_exact.unit_price = Decimal('100.00')
        
        confidence = self.matcher._calculate_line_match_confidence(invoice_line, po_line_exact)
        assert confidence >= Decimal('0.85')  # Should be high confidence
        
        # Mock PO line - partial match
        po_line_partial = Mock()
        po_line_partial.item_code = "ITEM002"  # Different item code
        po_line_partial.description = "Test Product Beta"  # Different description
        po_line_partial.quantity = Decimal('10')
        po_line_partial.unit_price = Decimal('100.00')
        
        confidence = self.matcher._calculate_line_match_confidence(invoice_line, po_line_partial)
        assert confidence < Decimal('0.50')  # Should be low confidence


@pytest.mark.asyncio
class TestPerformanceBenchmarks:
    """Test performance requirements and benchmarks."""
    
    def setup_method(self):
        """Set up performance test fixtures."""
        self.tenant_id = uuid4()
        self.engine = MatchingEngine(self.tenant_id)
    
    async def test_single_invoice_processing_time(self):
        """Test single invoice processing meets performance requirements."""
        invoice_id = uuid4()
        mock_db = AsyncMock(spec=AsyncSession)
        
        # Mock quick response
        mock_invoice = Mock()
        mock_invoice.id = invoice_id
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_invoice
        
        with patch.object(self.engine, '_attempt_exact_match') as mock_exact:
            mock_candidate = MatchCandidate(
                document_id=uuid4(),
                document_type="po",
                confidence_score=Decimal('1.0'),
                match_criteria={},
                raw_scores={},
                variance_details={}
            )
            mock_exact.return_value = mock_candidate
            
            with patch.object(self.engine, '_finalize_match_decision') as mock_finalize:
                mock_decision = Mock()
                mock_finalize.return_value = mock_decision
                
                start_time = datetime.now()
                result = await self.engine.match_invoice(invoice_id, mock_db)
                end_time = datetime.now()
                
                processing_time = (end_time - start_time).total_seconds()
                
                # Should process in under 1 second (requirement: sub-second)
                assert processing_time < 1.0
    
    async def test_batch_processing_performance(self):
        """Test batch processing meets performance requirements."""
        # Test with 100 invoices (requirement: 100+ in under 5 seconds)
        invoice_ids = [uuid4() for _ in range(100)]
        mock_db = AsyncMock(spec=AsyncSession)
        
        # Mock fast processing
        with patch.object(self.engine, 'match_invoice') as mock_match:
            # Return quick mock results
            mock_match.return_value = Mock()
            
            start_time = datetime.now()
            metrics = await self.engine.process_batch_matching(
                invoice_ids, mock_db, parallel=True
            )
            end_time = datetime.now()
            
            processing_time = (end_time - start_time).total_seconds()
            
            # Should process 100 invoices in under 5 seconds
            assert processing_time < 5.0
            assert metrics.total_invoices == 100


class TestErrorHandlingAndEdgeCases:
    """Test error handling and edge cases."""
    
    def test_invalid_weights_in_confidence_scorer(self):
        """Test confidence scorer with invalid weights."""
        # Weights don't sum to 1.0
        invalid_weights = {
            'vendor_name': 0.5,
            'amount': 0.3,
            'date': 0.1,
            'reference': 0.05  # Sum = 0.95, not 1.0
        }
        
        with pytest.raises(ValueError):
            ConfidenceScorer(invalid_weights)
    
    def test_tolerance_engine_edge_cases(self):
        """Test tolerance engine with edge case values."""
        # Zero amounts
        within_tolerance, variance = ToleranceEngine.check_amount_tolerance(
            Decimal('0.00'), Decimal('0.00'), {}
        )
        assert within_tolerance is True
        assert variance == Decimal('0.00')
        
        # Very small amounts
        within_tolerance, variance = ToleranceEngine.check_amount_tolerance(
            Decimal('0.01'), Decimal('0.02'), {"percentage": Decimal("0.50")}
        )
        assert within_tolerance is True  # 100% variance but within 50% tolerance
    
    def test_fuzzy_matcher_with_empty_corpus(self):
        """Test fuzzy matcher with empty vendor corpus."""
        matcher = FuzzyMatcher()
        
        # Should handle empty corpus gracefully
        matcher.fit_vendor_corpus([])
        
        best_match, score = matcher.find_best_vendor_match("Test Vendor", [])
        assert best_match == ""
        assert score == 0.0
    
    def test_ocr_corrector_performance(self):
        """Test OCR corrector doesn't create excessive variants."""
        # Test with string that could generate many variants
        test_string = "0123456789"  # All OCR-prone characters
        variants = OCRErrorCorrector.generate_variants(test_string)
        
        # Should limit variants for performance
        assert len(variants) <= 10  # Reasonable limit


if __name__ == "__main__":
    pytest.main([__file__])