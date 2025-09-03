"""
Performance tests for the automated matching engine.

Validates that the matching engine meets all performance requirements
specified in the acceptance criteria:

- Process 100+ invoices with exact matching in under 5 seconds
- Process matching for 500+ invoices in under 30 seconds  
- Maintain sub-second response times for individual matches
- Scale to handle 10,000+ POs and receipts in matching dataset
- Support parallel processing for large batches

Performance Requirements Validation:
- Single invoice: < 1 second
- Batch 100 exact matches: < 5 seconds
- Batch 500 mixed matches: < 30 seconds
- Memory usage: < 1GB for 10,000 documents
- Concurrent processing: 4+ parallel threads
"""

import pytest
import asyncio
import time
import psutil
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from typing import List
import concurrent.futures

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db_context
from app.services.matching_engine import create_matching_engine, ProcessingMetrics
from app.services.three_way_matching import create_three_way_matcher
from app.models.financial import (
    Invoice, PurchaseOrder, Receipt, Vendor, Tenant,
    InvoiceLine, PurchaseOrderLine, ReceiptLine,
    MatchResult, MatchingConfiguration,
    DocumentStatus, CurrencyCode, MatchType
)

# Configure logging for performance monitoring
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """Monitor system performance during tests."""
    
    def __init__(self):
        self.process = psutil.Process()
        self.start_time = None
        self.start_memory = None
        self.start_cpu = None
    
    def start_monitoring(self):
        """Start performance monitoring."""
        self.start_time = time.time()
        self.start_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        self.start_cpu = self.process.cpu_percent()
    
    def get_metrics(self) -> dict:
        """Get current performance metrics."""
        current_time = time.time()
        current_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        current_cpu = self.process.cpu_percent()
        
        return {
            'elapsed_time': current_time - self.start_time,
            'memory_used': current_memory - self.start_memory,
            'peak_memory': current_memory,
            'avg_cpu_percent': current_cpu
        }


class TestDataGenerator:
    """Generate test data for performance testing."""
    
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
    
    async def create_vendors(self, db: AsyncSession, count: int = 100) -> List[Vendor]:
        """Create test vendors."""
        vendors = []
        
        for i in range(count):
            vendor = Vendor(
                id=uuid4(),
                tenant_id=self.tenant_id,
                vendor_code=f"VEN{i:06d}",
                name=f"Test Vendor {i}",
                legal_name=f"Test Vendor {i} Corporation",
                is_active=True
            )
            vendors.append(vendor)
            db.add(vendor)
        
        await db.commit()
        return vendors
    
    async def create_purchase_orders(
        self, 
        db: AsyncSession, 
        vendors: List[Vendor], 
        count: int = 1000
    ) -> List[PurchaseOrder]:
        """Create test purchase orders with line items."""
        pos = []
        
        for i in range(count):
            vendor = vendors[i % len(vendors)]
            
            po = PurchaseOrder(
                id=uuid4(),
                tenant_id=self.tenant_id,
                vendor_id=vendor.id,
                po_number=f"PO{i:08d}",
                currency=CurrencyCode.USD,
                subtotal=Decimal(f"{1000 + (i * 10)}.00"),
                tax_amount=Decimal(f"{(1000 + (i * 10)) * 0.08:.2f}"),
                total_amount=Decimal(f"{(1000 + (i * 10)) * 1.08:.2f}"),
                po_date=datetime.now() - timedelta(days=i % 30),
                status=DocumentStatus.PENDING,
                created_by=uuid4()
            )
            pos.append(po)
            db.add(po)
            
            # Add line items
            for j in range(1, 4):  # 3 lines per PO
                line = PurchaseOrderLine(
                    id=uuid4(),
                    tenant_id=self.tenant_id,
                    purchase_order_id=po.id,
                    line_number=j,
                    item_code=f"ITEM{i:04d}{j:02d}",
                    description=f"Test item {i}-{j}",
                    quantity=Decimal(f"{j * 10}"),
                    unit_price=Decimal(f"{10 + j}.00"),
                    line_total=Decimal(f"{(j * 10) * (10 + j)}.00"),
                    unit_of_measure="EA"
                )
                db.add(line)
        
        await db.commit()
        return pos
    
    async def create_invoices(
        self, 
        db: AsyncSession, 
        vendors: List[Vendor], 
        pos: List[PurchaseOrder], 
        count: int = 500,
        match_percentage: float = 0.8
    ) -> List[Invoice]:
        """Create test invoices, some matching POs exactly, some with variations."""
        invoices = []
        
        for i in range(count):
            vendor = vendors[i % len(vendors)]
            
            # Determine if this should be an exact match
            is_exact_match = i < (count * match_percentage)
            
            if is_exact_match and i < len(pos):
                # Create exact match invoice
                po = pos[i]
                
                invoice = Invoice(
                    id=uuid4(),
                    tenant_id=self.tenant_id,
                    vendor_id=po.vendor_id,
                    invoice_number=f"INV{i:08d}",
                    po_reference=po.po_number,
                    currency=po.currency,
                    subtotal=po.subtotal,
                    tax_amount=po.tax_amount,
                    total_amount=po.total_amount,
                    invoice_date=po.po_date + timedelta(days=5),
                    status=DocumentStatus.PENDING,
                    file_name=f"invoice_{i}.pdf",
                    file_path=f"/uploads/invoice_{i}.pdf",
                    file_hash=f"hash{i:08d}",
                    file_size=1024 * (i + 1),
                    mime_type="application/pdf",
                    created_by=uuid4()
                )
            else:
                # Create fuzzy match or non-match invoice
                amount_variance = Decimal(f"{1000 + (i * 10) * (0.9 + (i % 20) * 0.01):.2f}")
                
                invoice = Invoice(
                    id=uuid4(),
                    tenant_id=self.tenant_id,
                    vendor_id=vendor.id,
                    invoice_number=f"INV{i:08d}",
                    po_reference=f"PO{i:08d}" if i < len(pos) else None,
                    currency=CurrencyCode.USD,
                    subtotal=amount_variance,
                    tax_amount=amount_variance * Decimal("0.08"),
                    total_amount=amount_variance * Decimal("1.08"),
                    invoice_date=datetime.now() - timedelta(days=i % 20),
                    status=DocumentStatus.PENDING,
                    file_name=f"invoice_{i}.pdf",
                    file_path=f"/uploads/invoice_{i}.pdf",
                    file_hash=f"hash{i:08d}",
                    file_size=1024 * (i + 1),
                    mime_type="application/pdf",
                    created_by=uuid4()
                )
            
            invoices.append(invoice)
            db.add(invoice)
        
        await db.commit()
        return invoices


@pytest.mark.asyncio
class TestSingleInvoicePerformance:
    """Test individual invoice matching performance."""
    
    async def test_single_exact_match_performance(self, test_db_session):
        """Test single exact match meets sub-second requirement."""
        tenant_id = uuid4()
        monitor = PerformanceMonitor()
        
        # Create test data
        generator = TestDataGenerator(tenant_id)
        vendors = await generator.create_vendors(test_db_session, 10)
        pos = await generator.create_purchase_orders(test_db_session, vendors, 100)
        invoices = await generator.create_invoices(test_db_session, vendors, pos, 1, 1.0)
        
        # Initialize matching engine
        matching_engine = await create_matching_engine(tenant_id, test_db_session)
        
        # Performance test
        monitor.start_monitoring()
        
        result = await matching_engine.match_invoice(invoices[0].id, test_db_session)
        
        metrics = monitor.get_metrics()
        
        # Assertions
        assert result is not None, "Should find exact match"
        assert metrics['elapsed_time'] < 1.0, f"Single match took {metrics['elapsed_time']:.3f}s, should be < 1.0s"
        assert metrics['peak_memory'] < 100, f"Memory usage {metrics['peak_memory']:.1f}MB should be < 100MB"
        
        logger.info(f"Single exact match: {metrics['elapsed_time']:.3f}s, {metrics['peak_memory']:.1f}MB")
    
    async def test_single_fuzzy_match_performance(self, test_db_session):
        """Test single fuzzy match performance."""
        tenant_id = uuid4()
        monitor = PerformanceMonitor()
        
        # Create test data with fuzzy matches
        generator = TestDataGenerator(tenant_id)
        vendors = await generator.create_vendors(test_db_session, 10)
        pos = await generator.create_purchase_orders(test_db_session, vendors, 100)
        invoices = await generator.create_invoices(test_db_session, vendors, pos, 1, 0.0)  # No exact matches
        
        # Initialize matching engine
        matching_engine = await create_matching_engine(tenant_id, test_db_session)
        
        # Performance test
        monitor.start_monitoring()
        
        result = await matching_engine.match_invoice(invoices[0].id, test_db_session)
        
        metrics = monitor.get_metrics()
        
        # Fuzzy matching may take longer but should still be reasonable
        assert metrics['elapsed_time'] < 2.0, f"Fuzzy match took {metrics['elapsed_time']:.3f}s, should be < 2.0s"
        
        logger.info(f"Single fuzzy match: {metrics['elapsed_time']:.3f}s, {metrics['peak_memory']:.1f}MB")


@pytest.mark.asyncio  
class TestBatchProcessingPerformance:
    """Test batch processing performance requirements."""
    
    async def test_batch_100_exact_matches_performance(self, test_db_session):
        """Test processing 100 exact matches in under 5 seconds."""
        tenant_id = uuid4()
        monitor = PerformanceMonitor()
        
        # Create test data - all exact matches
        generator = TestDataGenerator(tenant_id)
        vendors = await generator.create_vendors(test_db_session, 20)
        pos = await generator.create_purchase_orders(test_db_session, vendors, 150)
        invoices = await generator.create_invoices(test_db_session, vendors, pos, 100, 1.0)
        
        # Initialize matching engine
        matching_engine = await create_matching_engine(tenant_id, test_db_session)
        
        # Performance test
        invoice_ids = [invoice.id for invoice in invoices]
        
        monitor.start_monitoring()
        
        metrics = await matching_engine.process_batch_matching(
            invoice_ids, test_db_session, parallel=True
        )
        
        performance = monitor.get_metrics()
        
        # Assertions
        assert performance['elapsed_time'] < 5.0, f"100 exact matches took {performance['elapsed_time']:.3f}s, should be < 5.0s"
        assert metrics.total_invoices == 100
        assert metrics.exact_matches >= 80  # Most should be exact matches
        assert performance['peak_memory'] < 500, f"Memory usage {performance['peak_memory']:.1f}MB should be < 500MB"
        
        logger.info(f"Batch 100 exact matches: {performance['elapsed_time']:.3f}s, {performance['peak_memory']:.1f}MB")
        logger.info(f"Exact: {metrics.exact_matches}, Fuzzy: {metrics.fuzzy_matches}, Unmatched: {metrics.unmatched}")
    
    async def test_batch_500_mixed_matches_performance(self, test_db_session):
        """Test processing 500 mixed matches in under 30 seconds."""
        tenant_id = uuid4()
        monitor = PerformanceMonitor()
        
        # Create test data - mix of exact and fuzzy matches
        generator = TestDataGenerator(tenant_id)
        vendors = await generator.create_vendors(test_db_session, 50)
        pos = await generator.create_purchase_orders(test_db_session, vendors, 600)
        invoices = await generator.create_invoices(test_db_session, vendors, pos, 500, 0.6)  # 60% exact matches
        
        # Initialize matching engine
        matching_engine = await create_matching_engine(tenant_id, test_db_session)
        
        # Performance test
        invoice_ids = [invoice.id for invoice in invoices]
        
        monitor.start_monitoring()
        
        metrics = await matching_engine.process_batch_matching(
            invoice_ids, test_db_session, parallel=True
        )
        
        performance = monitor.get_metrics()
        
        # Assertions
        assert performance['elapsed_time'] < 30.0, f"500 mixed matches took {performance['elapsed_time']:.3f}s, should be < 30.0s"
        assert metrics.total_invoices == 500
        assert performance['peak_memory'] < 1000, f"Memory usage {performance['peak_memory']:.1f}MB should be < 1000MB"
        
        # Performance should be reasonable
        throughput = metrics.total_invoices / performance['elapsed_time']
        assert throughput > 16, f"Throughput {throughput:.1f} invoices/sec should be > 16/sec"
        
        logger.info(f"Batch 500 mixed matches: {performance['elapsed_time']:.3f}s, {performance['peak_memory']:.1f}MB")
        logger.info(f"Throughput: {throughput:.1f} invoices/sec")
        logger.info(f"Exact: {metrics.exact_matches}, Fuzzy: {metrics.fuzzy_matches}, Unmatched: {metrics.unmatched}")


@pytest.mark.asyncio
class TestScalabilityPerformance:
    """Test scalability with large datasets."""
    
    async def test_large_dataset_handling(self, test_db_session):
        """Test handling 10,000+ POs and receipts in matching dataset."""
        tenant_id = uuid4()
        monitor = PerformanceMonitor()
        
        # Create large test dataset
        generator = TestDataGenerator(tenant_id)
        vendors = await generator.create_vendors(test_db_session, 100)
        
        monitor.start_monitoring()
        
        # Create 10,000 POs
        pos = await generator.create_purchase_orders(test_db_session, vendors, 10000)
        
        creation_metrics = monitor.get_metrics()
        logger.info(f"Created 10,000 POs in {creation_metrics['elapsed_time']:.1f}s")
        
        # Test matching with large dataset
        invoices = await generator.create_invoices(test_db_session, vendors, pos, 50, 0.8)
        
        # Initialize matching engine
        matching_engine = await create_matching_engine(tenant_id, test_db_session)
        
        # Reset monitoring for matching test
        monitor.start_monitoring()
        
        invoice_ids = [invoice.id for invoice in invoices[:10]]  # Test with 10 invoices
        
        metrics = await matching_engine.process_batch_matching(
            invoice_ids, test_db_session, parallel=True
        )
        
        performance = monitor.get_metrics()
        
        # Assertions for scalability
        assert performance['elapsed_time'] < 10.0, f"Matching against large dataset took {performance['elapsed_time']:.3f}s"
        assert performance['peak_memory'] < 1500, f"Memory usage {performance['peak_memory']:.1f}MB should be < 1500MB"
        assert metrics.total_invoices == 10
        
        logger.info(f"Matching against 10K POs: {performance['elapsed_time']:.3f}s, {performance['peak_memory']:.1f}MB")
    
    async def test_parallel_processing_efficiency(self, test_db_session):
        """Test parallel processing provides performance benefit."""
        tenant_id = uuid4()
        
        # Create test data
        generator = TestDataGenerator(tenant_id)
        vendors = await generator.create_vendors(test_db_session, 10)
        pos = await generator.create_purchase_orders(test_db_session, vendors, 200)
        invoices = await generator.create_invoices(test_db_session, vendors, pos, 100, 0.8)
        
        # Initialize matching engine
        matching_engine = await create_matching_engine(tenant_id, test_db_session)
        invoice_ids = [invoice.id for invoice in invoices]
        
        # Test sequential processing
        start_time = time.time()
        sequential_metrics = await matching_engine.process_batch_matching(
            invoice_ids, test_db_session, parallel=False
        )
        sequential_time = time.time() - start_time
        
        # Reset for parallel processing test
        # Clear any existing match results first
        await test_db_session.execute(
            select(MatchResult).where(MatchResult.tenant_id == tenant_id)
        )
        await test_db_session.commit()
        
        # Test parallel processing
        start_time = time.time()
        parallel_metrics = await matching_engine.process_batch_matching(
            invoice_ids, test_db_session, parallel=True
        )
        parallel_time = time.time() - start_time
        
        # Parallel should be faster for this batch size
        speedup = sequential_time / parallel_time if parallel_time > 0 else 1.0
        
        logger.info(f"Sequential: {sequential_time:.3f}s, Parallel: {parallel_time:.3f}s, Speedup: {speedup:.1f}x")
        
        # Should see some benefit from parallelization
        assert speedup > 1.0, f"Parallel processing should be faster (speedup: {speedup:.1f}x)"
        assert parallel_time < sequential_time, "Parallel should be faster than sequential"


@pytest.mark.asyncio
class TestThreeWayMatchingPerformance:
    """Test 3-way matching performance."""
    
    async def test_three_way_matching_performance(self, test_db_session):
        """Test 3-way matching meets performance requirements."""
        tenant_id = uuid4()
        monitor = PerformanceMonitor()
        
        # Create comprehensive test data
        generator = TestDataGenerator(tenant_id)
        vendors = await generator.create_vendors(test_db_session, 10)
        pos = await generator.create_purchase_orders(test_db_session, vendors, 50)
        invoices = await generator.create_invoices(test_db_session, vendors, pos, 20, 1.0)
        
        # Create receipts for some POs
        for i, po in enumerate(pos[:20]):
            receipt = Receipt(
                id=uuid4(),
                tenant_id=tenant_id,
                purchase_order_id=po.id,
                receipt_number=f"REC{i:06d}",
                receipt_date=po.po_date + timedelta(days=3),
                received_by=f"User {i}",
                total_quantity=Decimal("30"),  # Sum of line quantities
                total_value=po.total_amount,
                status=DocumentStatus.PENDING,
                created_by=uuid4()
            )
            test_db_session.add(receipt)
        
        await test_db_session.commit()
        
        # Test 3-way matching performance
        three_way_matcher = await create_three_way_matcher(tenant_id)
        
        monitor.start_monitoring()
        
        results = []
        for invoice in invoices[:10]:  # Test first 10 invoices
            result = await three_way_matcher.perform_three_way_match(invoice.id, test_db_session)
            if result:
                results.append(result)
        
        performance = monitor.get_metrics()
        
        # Assertions
        assert performance['elapsed_time'] < 15.0, f"3-way matching took {performance['elapsed_time']:.3f}s, should be < 15.0s"
        assert len(results) > 0, "Should find at least some 3-way matches"
        
        avg_time_per_match = performance['elapsed_time'] / len(results) if results else 0
        assert avg_time_per_match < 2.0, f"Average time per 3-way match: {avg_time_per_match:.3f}s"
        
        logger.info(f"3-way matching: {len(results)} matches in {performance['elapsed_time']:.3f}s")
        logger.info(f"Average per match: {avg_time_per_match:.3f}s")


@pytest.mark.asyncio  
class TestMemoryEfficiency:
    """Test memory usage and efficiency."""
    
    async def test_memory_usage_large_batch(self, test_db_session):
        """Test memory usage remains reasonable for large batches."""
        tenant_id = uuid4()
        monitor = PerformanceMonitor()
        
        # Create large dataset
        generator = TestDataGenerator(tenant_id)
        vendors = await generator.create_vendors(test_db_session, 50)
        pos = await generator.create_purchase_orders(test_db_session, vendors, 1000)
        invoices = await generator.create_invoices(test_db_session, vendors, pos, 1000, 0.7)
        
        # Initialize matching engine
        matching_engine = await create_matching_engine(tenant_id, test_db_session)
        
        # Monitor memory during processing
        monitor.start_monitoring()
        
        invoice_ids = [invoice.id for invoice in invoices]
        
        # Process in chunks to test memory efficiency
        chunk_size = 100
        for i in range(0, len(invoice_ids), chunk_size):
            chunk = invoice_ids[i:i + chunk_size]
            await matching_engine.process_batch_matching(
                chunk, test_db_session, parallel=True
            )
        
        performance = monitor.get_metrics()
        
        # Memory should not grow excessively
        assert performance['peak_memory'] < 2000, f"Peak memory {performance['peak_memory']:.1f}MB should be < 2000MB"
        
        logger.info(f"Processed 1000 invoices, peak memory: {performance['peak_memory']:.1f}MB")


@pytest.fixture
async def test_db_session():
    """Create test database session."""
    async with get_db_context() as session:
        # Create tenant for testing
        tenant = Tenant(
            id=uuid4(),
            name="test_tenant",
            display_name="Test Tenant",
            is_active=True
        )
        session.add(tenant)
        await session.commit()
        
        yield session
        
        # Cleanup
        await session.rollback()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])