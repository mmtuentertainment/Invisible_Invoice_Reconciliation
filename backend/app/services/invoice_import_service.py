"""
Invoice import service with atomic transaction management and rollback capabilities.

This service orchestrates the complete import process including:
- CSV processing and validation
- Data normalization and transformation
- Vendor management and creation
- Invoice creation with duplicate detection
- Progress tracking and error reporting
- Atomic transactions with rollback support
"""

import asyncio
import csv
import io
import logging
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Generator
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.financial import (
    Invoice, Vendor, ImportBatch, ImportBatchStatus, ImportError, ImportErrorType,
    InvoiceLine, CurrencyCode, DocumentStatus
)
from app.services.csv_processor import CSVProcessor, CSVProcessingError
from app.services.validation_engine import ValidationEngine, ValidationError
from app.services.websocket_service import progress_broadcaster
from app.services.redis_service import RedisService
from app.core.config import settings

logger = logging.getLogger(__name__)


class ImportTransaction:
    """Context manager for atomic import transactions with rollback support."""
    
    def __init__(self, db: Session, batch_id: UUID):
        self.db = db
        self.batch_id = batch_id
        self.savepoint = None
        self.created_vendors: List[UUID] = []
        self.created_invoices: List[UUID] = []
        
    async def __aenter__(self):
        """Start transaction with savepoint."""
        try:
            self.savepoint = self.db.begin_nested()  # Create savepoint
            logger.info(f"Started import transaction for batch {self.batch_id}")
            return self
        except Exception as e:
            logger.error(f"Error starting import transaction: {e}")
            raise
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Handle transaction completion or rollback."""
        try:
            if exc_type is None:
                # Commit the transaction
                self.savepoint.commit()
                self.db.commit()
                logger.info(f"Import transaction committed for batch {self.batch_id}")
            else:
                # Rollback on error
                await self.rollback_transaction()
                logger.error(f"Import transaction rolled back for batch {self.batch_id}: {exc_val}")
        except Exception as e:
            logger.error(f"Error handling transaction completion: {e}")
            
    async def rollback_transaction(self):
        """Rollback transaction and clean up created records."""
        try:
            if self.savepoint:
                self.savepoint.rollback()
            
            # Additional cleanup if needed
            logger.info(f"Transaction rolled back for batch {self.batch_id}")
            
        except Exception as e:
            logger.error(f"Error during transaction rollback: {e}")
    
    def track_created_vendor(self, vendor_id: UUID):
        """Track a created vendor for potential rollback."""
        self.created_vendors.append(vendor_id)
    
    def track_created_invoice(self, invoice_id: UUID):
        """Track a created invoice for potential rollback."""
        self.created_invoices.append(invoice_id)


class InvoiceImportService:
    """Service for processing invoice imports with validation and error handling."""
    
    def __init__(self, db: Session, tenant_id: UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.redis_service = RedisService()
        
        # Processing statistics
        self.stats = {
            'total_rows': 0,
            'processed_rows': 0,
            'successful_rows': 0,
            'error_rows': 0,
            'duplicate_rows': 0,
            'vendors_created': 0,
            'vendors_matched': 0
        }
    
    async def process_import_batch(self, batch_id: UUID, user_id: UUID) -> Dict[str, Any]:
        """
        Process a complete import batch with validation and atomic transactions.
        
        Args:
            batch_id: ID of the import batch to process
            user_id: ID of the user initiating the import
            
        Returns:
            Dictionary containing processing results and statistics
        """
        import_batch = None
        processing_results = {
            'success': False,
            'message': '',
            'statistics': {},
            'errors': []
        }
        
        try:
            # Get import batch
            import_batch = self.db.query(ImportBatch).filter(
                ImportBatch.id == batch_id,
                ImportBatch.tenant_id == self.tenant_id
            ).first()
            
            if not import_batch:
                raise ValueError(f"Import batch {batch_id} not found")
            
            if import_batch.status != ImportBatchStatus.PROCESSING:
                raise ValueError(f"Import batch is not in processing status: {import_batch.status}")
            
            # Check for cancellation signal
            if await self._is_import_cancelled(batch_id):
                await self._update_batch_status(import_batch, ImportBatchStatus.CANCELLED)
                processing_results['message'] = "Import cancelled by user"
                return processing_results
            
            # Initialize processing
            await self._update_batch_progress(batch_id, 0, "Initializing import process...")
            
            # Create CSV processor and validation engine
            csv_processor = CSVProcessor(self.db, self.tenant_id)
            validation_engine = ValidationEngine(self.db, self.tenant_id, batch_id)
            
            # Process with atomic transaction
            async with ImportTransaction(self.db, batch_id) as transaction:
                
                # Stream process CSV file
                await self._update_batch_progress(batch_id, 5, "Reading CSV file...")
                
                # Get column mapping
                column_mapping = import_batch.column_mapping
                if not column_mapping:
                    raise ValueError("Column mapping not configured")
                
                # Process CSV rows
                row_count = 0
                error_count = 0
                success_count = 0
                duplicate_count = 0
                
                file_path = import_batch.storage_path
                
                # Stream process the CSV
                csv_stream = csv_processor.process_csv_stream(file_path, column_mapping, import_batch)
                
                for processed_row in csv_stream:
                    # Check for cancellation
                    if await self._is_import_cancelled(batch_id):
                        raise InterruptedError("Import cancelled by user")
                    
                    row_count += 1
                    self.stats['total_rows'] = row_count
                    
                    # Update progress periodically
                    if row_count % 50 == 0:
                        progress = min(95, 10 + (row_count / max(1, import_batch.total_records)) * 80)
                        await self._update_batch_progress(
                            batch_id, 
                            progress, 
                            f"Processing row {row_count}..."
                        )
                    
                    # Validate row
                    row_data = processed_row['normalized_data']
                    row_errors = processed_row.get('errors', [])
                    row_warnings = processed_row.get('warnings', [])
                    
                    # Run additional validation
                    enhanced_data, additional_errors = validation_engine.validate_row(
                        row_data, processed_row['row_number']
                    )
                    row_errors.extend(additional_errors)
                    
                    # Process row based on validation results
                    has_critical_errors = any(e.severity == 'error' for e in row_errors)
                    
                    if has_critical_errors:
                        # Log errors to database
                        await self._log_row_errors(batch_id, processed_row['row_number'], 
                                                 row_errors, processed_row['raw_data'])
                        error_count += 1
                        
                    elif any(e.error_type == ImportErrorType.DUPLICATE for e in row_errors):
                        # Handle duplicates
                        await self._log_row_errors(batch_id, processed_row['row_number'], 
                                                 row_errors, processed_row['raw_data'])
                        duplicate_count += 1
                        
                    else:
                        # Process successful row
                        try:
                            await self._create_invoice_record(enhanced_data, user_id, transaction)
                            success_count += 1
                            
                            # Log warnings if any
                            if row_warnings:
                                warning_errors = [ValidationError(
                                    error_type=ImportErrorType.VALIDATION,
                                    code="ROW_WARNING",
                                    message=f"Row processed with warnings: {len(row_warnings)} warnings",
                                    severity="warning"
                                )]
                                await self._log_row_errors(batch_id, processed_row['row_number'],
                                                         warning_errors, processed_row['raw_data'])
                        
                        except Exception as e:
                            logger.error(f"Error creating invoice record at row {row_count}: {e}")
                            error_errors = [ValidationError(
                                error_type=ImportErrorType.SYSTEM,
                                code="RECORD_CREATION_ERROR",
                                message=f"Failed to create record: {str(e)}",
                                severity="error"
                            )]
                            await self._log_row_errors(batch_id, processed_row['row_number'],
                                                     error_errors, processed_row['raw_data'])
                            error_count += 1
                    
                    # Update running statistics
                    self.stats.update({
                        'processed_rows': row_count,
                        'successful_rows': success_count,
                        'error_rows': error_count,
                        'duplicate_rows': duplicate_count
                    })
                
                # Final progress update
                await self._update_batch_progress(batch_id, 95, "Finalizing import...")
                
                # Update import batch with final results
                import_batch.processed_records = row_count
                import_batch.successful_records = success_count
                import_batch.error_records = error_count
                import_batch.duplicate_records = duplicate_count
                import_batch.processing_completed_at = datetime.utcnow()
                import_batch.processing_summary = {
                    'total_processed': row_count,
                    'successful': success_count,
                    'errors': error_count,
                    'duplicates': duplicate_count,
                    'validation_summary': validation_engine.get_validation_summary()
                }
                
                # Determine final status
                if error_count == 0 and success_count > 0:
                    final_status = ImportBatchStatus.COMPLETED
                    message = f"Import completed successfully. {success_count} records imported."
                elif success_count > 0:
                    final_status = ImportBatchStatus.COMPLETED
                    message = f"Import completed with warnings. {success_count} records imported, {error_count} errors."
                else:
                    final_status = ImportBatchStatus.FAILED
                    message = "Import failed. No records were imported."
                
                import_batch.status = final_status
                self.db.commit()
                
                # Final progress update
                await self._update_batch_progress(batch_id, 100, "Import completed")
                
                # Broadcast status change
                await progress_broadcaster.update_status(
                    batch_id, 
                    final_status.value, 
                    self.tenant_id,
                    {'message': message, 'statistics': self.stats}
                )
                
                processing_results.update({
                    'success': final_status == ImportBatchStatus.COMPLETED,
                    'message': message,
                    'statistics': self.stats
                })
                
                logger.info(f"Import batch {batch_id} completed: {message}")
                
        except InterruptedError as e:
            # Handle cancellation
            if import_batch:
                await self._update_batch_status(import_batch, ImportBatchStatus.CANCELLED)
            processing_results['message'] = "Import cancelled by user"
            logger.info(f"Import batch {batch_id} cancelled")
            
        except Exception as e:
            logger.error(f"Error processing import batch {batch_id}: {e}")
            
            # Update batch status to failed
            if import_batch:
                await self._update_batch_status(import_batch, ImportBatchStatus.FAILED, str(e))
            
            processing_results.update({
                'success': False,
                'message': f"Import failed: {str(e)}",
                'errors': [str(e)]
            })
        
        return processing_results
    
    async def _create_invoice_record(self, data: Dict[str, Any], user_id: UUID, 
                                   transaction: ImportTransaction) -> Invoice:
        """Create invoice and associated records."""
        try:
            # Get or create vendor
            vendor = await self._get_or_create_vendor(data, user_id, transaction)
            
            # Create invoice
            invoice = Invoice(
                id=uuid4(),
                tenant_id=self.tenant_id,
                vendor_id=vendor.id,
                invoice_number=data['invoice_number'],
                po_reference=data.get('po_reference'),
                currency=CurrencyCode.USD,  # Default, could be mapped from data
                subtotal=data.get('subtotal', data['total_amount']),
                tax_amount=data.get('tax_amount', Decimal('0.00')),
                total_amount=data['total_amount'],
                invoice_date=data['invoice_date'],
                due_date=data.get('due_date'),
                status=DocumentStatus.PENDING,
                processing_status='imported',
                file_name=f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                file_path="imported_via_csv",
                file_hash=f"csv_import_{uuid4().hex[:16]}",
                file_size=0,
                mime_type='text/csv',
                created_by=user_id
            )
            
            self.db.add(invoice)
            self.db.flush()  # Get ID without committing
            
            transaction.track_created_invoice(invoice.id)
            
            # Create invoice line if description provided
            if data.get('description'):
                invoice_line = InvoiceLine(
                    id=uuid4(),
                    tenant_id=self.tenant_id,
                    invoice_id=invoice.id,
                    line_number=1,
                    description=data['description'][:500],  # Truncate to field limit
                    quantity=Decimal('1.0'),
                    unit_price=data['total_amount'],
                    line_total=data['total_amount']
                )
                self.db.add(invoice_line)
            
            return invoice
            
        except Exception as e:
            logger.error(f"Error creating invoice record: {e}")
            raise
    
    async def _get_or_create_vendor(self, data: Dict[str, Any], user_id: UUID,
                                  transaction: ImportTransaction) -> Vendor:
        """Get existing vendor or create new one."""
        vendor_name = data['vendor_name']
        
        # Check if vendor was matched during validation
        if '_matched_vendor_id' in data:
            vendor = self.db.query(Vendor).filter(
                Vendor.id == data['_matched_vendor_id']
            ).first()
            if vendor:
                self.stats['vendors_matched'] += 1
                return vendor
        
        # Try to find existing vendor by normalized name
        existing_vendor = self.db.query(Vendor).filter(
            and_(
                Vendor.tenant_id == self.tenant_id,
                func.upper(Vendor.name) == vendor_name.upper()
            )
        ).first()
        
        if existing_vendor:
            self.stats['vendors_matched'] += 1
            return existing_vendor
        
        # Create new vendor
        vendor_code = self._generate_vendor_code(vendor_name)
        
        vendor = Vendor(
            id=uuid4(),
            tenant_id=self.tenant_id,
            vendor_code=vendor_code,
            name=vendor_name,
            legal_name=vendor_name,
            is_active=True,
            created_by=user_id
        )
        
        self.db.add(vendor)
        self.db.flush()  # Get ID without committing
        
        transaction.track_created_vendor(vendor.id)
        self.stats['vendors_created'] += 1
        
        return vendor
    
    def _generate_vendor_code(self, vendor_name: str) -> str:
        """Generate a unique vendor code from vendor name."""
        # Clean name for code generation
        cleaned_name = ''.join(c.upper() for c in vendor_name if c.isalnum())
        
        # Take first 6 characters
        base_code = cleaned_name[:6]
        if len(base_code) < 3:
            base_code = base_code.ljust(3, 'X')
        
        # Check for uniqueness
        counter = 1
        vendor_code = base_code
        
        while True:
            existing = self.db.query(Vendor).filter(
                and_(
                    Vendor.tenant_id == self.tenant_id,
                    Vendor.vendor_code == vendor_code
                )
            ).first()
            
            if not existing:
                return vendor_code
            
            # Append counter if not unique
            counter += 1
            vendor_code = f"{base_code[:4]}{counter:02d}"
            
            # Prevent infinite loop
            if counter > 99:
                vendor_code = f"{base_code[:3]}{uuid4().hex[:3].upper()}"
                break
        
        return vendor_code
    
    async def _log_row_errors(self, batch_id: UUID, row_number: int, 
                            errors: List[ValidationError], raw_data: Dict[str, Any]):
        """Log validation errors for a row to the database."""
        try:
            for error in errors:
                import_error = ImportError(
                    id=uuid4(),
                    tenant_id=self.tenant_id,
                    import_batch_id=batch_id,
                    row_number=row_number,
                    column_name=error.field,
                    error_type=error.error_type,
                    error_code=error.code,
                    error_message=error.message,
                    severity=error.severity,
                    raw_value=error.raw_value,
                    expected_format=error.expected_format,
                    suggested_fix=error.suggested_fix,
                    raw_row_data=raw_data
                )
                self.db.add(import_error)
            
            # Flush to get errors into database immediately
            self.db.flush()
            
        except Exception as e:
            logger.error(f"Error logging row errors: {e}")
    
    async def _update_batch_progress(self, batch_id: UUID, percentage: int, stage: str):
        """Update import batch progress and broadcast to WebSocket subscribers."""
        try:
            # Update database
            import_batch = self.db.query(ImportBatch).filter(
                ImportBatch.id == batch_id
            ).first()
            
            if import_batch:
                import_batch.progress_percentage = percentage
                import_batch.processing_stage = stage
                import_batch.updated_at = datetime.utcnow()
                self.db.commit()
                
                # Broadcast progress
                progress_data = {
                    'progress_percentage': percentage,
                    'processing_stage': stage,
                    'statistics': self.stats.copy()
                }
                
                await progress_broadcaster.update_progress(batch_id, progress_data)
                
        except Exception as e:
            logger.error(f"Error updating batch progress: {e}")
    
    async def _update_batch_status(self, import_batch: ImportBatch, status: ImportBatchStatus,
                                 error_message: Optional[str] = None):
        """Update import batch status."""
        try:
            import_batch.status = status
            import_batch.updated_at = datetime.utcnow()
            
            if error_message:
                import_batch.error_summary = {'error': error_message}
            
            if status in [ImportBatchStatus.COMPLETED, ImportBatchStatus.FAILED, ImportBatchStatus.CANCELLED]:
                import_batch.processing_completed_at = datetime.utcnow()
            
            self.db.commit()
            
            # Broadcast status change
            await progress_broadcaster.update_status(
                import_batch.id,
                status.value,
                self.tenant_id,
                {'error': error_message} if error_message else None
            )
            
        except Exception as e:
            logger.error(f"Error updating batch status: {e}")
    
    async def _is_import_cancelled(self, batch_id: UUID) -> bool:
        """Check if import has been cancelled via Redis signal."""
        try:
            cancel_signal = await self.redis_service.get(f"cancel_import:{batch_id}")
            return cancel_signal == "true"
        except Exception as e:
            logger.error(f"Error checking cancellation signal: {e}")
            return False
    
    async def generate_error_report(self, batch_id: UUID) -> str:
        """Generate CSV error report for download."""
        try:
            # Get import errors
            errors = self.db.query(ImportError).filter(
                and_(
                    ImportError.import_batch_id == batch_id,
                    ImportError.tenant_id == self.tenant_id
                )
            ).order_by(ImportError.row_number, ImportError.created_at).all()
            
            # Generate CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Row Number',
                'Column Name',
                'Error Type',
                'Error Code',
                'Error Message',
                'Severity',
                'Raw Value',
                'Expected Format',
                'Suggested Fix',
                'Created At'
            ])
            
            # Write error rows
            for error in errors:
                writer.writerow([
                    error.row_number,
                    error.column_name or '',
                    error.error_type.value,
                    error.error_code,
                    error.error_message,
                    error.severity,
                    error.raw_value or '',
                    error.expected_format or '',
                    error.suggested_fix or '',
                    error.created_at.strftime('%Y-%m-%d %H:%M:%S')
                ])
            
            return output.getvalue()
            
        except Exception as e:
            logger.error(f"Error generating error report: {e}")
            raise