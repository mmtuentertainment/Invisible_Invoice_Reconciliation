"""
Invoice upload API endpoints with chunked upload support and progress tracking.

This module provides RESTful endpoints for:
- File upload with chunked support
- CSV metadata analysis  
- Import status tracking
- Error report generation
- Import cancellation
"""

import asyncio
import hashlib
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Request, Response,
    UploadFile, BackgroundTasks, status
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_tenant_id
from app.core.config import settings
from app.core.security import check_file_security
from app.models.auth import User
from app.models.financial import ImportBatch, ImportBatchStatus, ImportError
from app.services.csv_processor import CSVProcessor, CSVProcessingError
from app.services.invoice_import_service import InvoiceImportService
from app.services.redis_service import RedisService
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for request/response
class FileUploadResponse(BaseModel):
    """Response model for file upload."""
    batch_id: UUID
    filename: str
    file_size: int
    status: str
    message: str
    metadata: Optional[Dict[str, Any]] = None


class ImportStatusResponse(BaseModel):
    """Response model for import status."""
    batch_id: UUID
    status: str
    progress_percentage: int
    total_records: int
    processed_records: int
    successful_records: int
    error_records: int
    duplicate_records: int
    processing_stage: Optional[str] = None
    created_at: datetime
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    error_summary: Optional[Dict[str, Any]] = None


class ColumnMappingRequest(BaseModel):
    """Request model for column mapping configuration."""
    column_mapping: Dict[str, str] = Field(
        ..., description="Mapping of CSV columns to field names"
    )
    processing_options: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Additional processing options"
    )
    
    @validator('column_mapping')
    def validate_column_mapping(cls, v):
        required_fields = {'invoice_number', 'vendor', 'amount', 'invoice_date'}
        mapped_fields = set(v.values())
        
        missing_fields = required_fields - mapped_fields
        if missing_fields:
            raise ValueError(f"Missing required field mappings: {missing_fields}")
        
        return v


class ChunkedUploadRequest(BaseModel):
    """Request model for chunked upload."""
    chunk_number: int = Field(..., ge=0)
    total_chunks: int = Field(..., ge=1)
    chunk_size: int = Field(..., gt=0)
    total_size: int = Field(..., gt=0)
    filename: str = Field(..., min_length=1)
    file_hash: Optional[str] = None


@router.post("/upload", response_model=FileUploadResponse)
async def upload_invoice_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> FileUploadResponse:
    """
    Upload invoice CSV file for processing.
    
    Supports files up to 50MB with automatic format detection and validation.
    Returns metadata about the file structure for column mapping configuration.
    """
    try:
        # Validate file
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No filename provided"
            )
        
        # Check file extension
        allowed_extensions = {'.csv', '.txt'}
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        
        # Validate file size
        max_size = 50 * 1024 * 1024  # 50MB
        if file_size > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size {file_size} exceeds maximum allowed size {max_size}"
            )
        
        if file_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File is empty"
            )
        
        # Security validation
        await check_file_security(file_content, file.filename)
        
        # Generate file hash
        file_hash = hashlib.sha256(file_content).hexdigest()
        
        # Create temporary file
        temp_dir = Path(tempfile.gettempdir()) / "invoice_uploads"
        temp_dir.mkdir(exist_ok=True)
        
        batch_id = uuid4()
        temp_filename = f"{batch_id}_{file.filename}"
        temp_file_path = temp_dir / temp_filename
        
        # Write file to temporary location
        with open(temp_file_path, 'wb') as temp_file:
            temp_file.write(file_content)
        
        # Create import batch record
        import_batch = ImportBatch(
            id=batch_id,
            tenant_id=tenant_id,
            filename=temp_filename,
            original_filename=file.filename,
            file_size=file_size,
            file_hash=file_hash,
            mime_type=file.content_type or 'text/csv',
            storage_path=str(temp_file_path),
            status=ImportBatchStatus.PENDING,
            created_by=current_user.id,
            upload_started_at=datetime.utcnow(),
            upload_completed_at=datetime.utcnow()
        )
        
        db.add(import_batch)
        db.commit()
        
        # Process CSV metadata in background
        background_tasks.add_task(
            process_csv_metadata_task,
            str(temp_file_path),
            batch_id,
            tenant_id
        )
        
        # Log audit event
        audit_service = AuditService(db)
        await audit_service.log_event(
            event_type="file_upload",
            entity_type="import_batch",
            entity_id=batch_id,
            user_id=current_user.id,
            tenant_id=tenant_id,
            details={
                "filename": file.filename,
                "file_size": file_size,
                "file_hash": file_hash
            }
        )
        
        return FileUploadResponse(
            batch_id=batch_id,
            filename=file.filename,
            file_size=file_size,
            status=ImportBatchStatus.PENDING.value,
            message="File uploaded successfully. Processing metadata...",
            metadata=None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )


@router.post("/upload/chunked", response_model=FileUploadResponse)
async def upload_chunked_file(
    request: Request,
    background_tasks: BackgroundTasks,
    chunk: UploadFile = File(...),
    chunk_info: str = Form(...),  # JSON string of ChunkedUploadRequest
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> FileUploadResponse:
    """
    Upload file chunks for large file support with resume capability.
    
    This endpoint handles chunked uploads for files larger than standard limits,
    providing resume capability for interrupted uploads.
    """
    try:
        # Parse chunk info
        import json
        chunk_data = ChunkedUploadRequest.parse_obj(json.loads(chunk_info))
        
        # Validate chunk
        if not chunk.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No chunk filename provided"
            )
        
        chunk_content = await chunk.read()
        
        # Create chunks directory
        chunks_dir = Path(tempfile.gettempdir()) / "invoice_chunks" / chunk_data.filename
        chunks_dir.mkdir(parents=True, exist_ok=True)
        
        # Save chunk
        chunk_path = chunks_dir / f"chunk_{chunk_data.chunk_number:04d}"
        with open(chunk_path, 'wb') as chunk_file:
            chunk_file.write(chunk_content)
        
        # Check if all chunks received
        expected_chunks = set(range(chunk_data.total_chunks))
        received_chunks = set()
        
        for chunk_file in chunks_dir.glob("chunk_*"):
            chunk_num = int(chunk_file.stem.split('_')[1])
            received_chunks.add(chunk_num)
        
        # If all chunks received, reassemble file
        if received_chunks == expected_chunks:
            batch_id = uuid4()
            temp_filename = f"{batch_id}_{chunk_data.filename}"
            
            # Create final file
            temp_dir = Path(tempfile.gettempdir()) / "invoice_uploads"
            temp_dir.mkdir(exist_ok=True)
            final_path = temp_dir / temp_filename
            
            # Reassemble chunks
            with open(final_path, 'wb') as final_file:
                for chunk_num in sorted(expected_chunks):
                    chunk_path = chunks_dir / f"chunk_{chunk_num:04d}"
                    with open(chunk_path, 'rb') as chunk_file:
                        final_file.write(chunk_file.read())
            
            # Verify file integrity
            with open(final_path, 'rb') as final_file:
                file_content = final_file.read()
                file_hash = hashlib.sha256(file_content).hexdigest()
            
            if chunk_data.file_hash and file_hash != chunk_data.file_hash:
                # Clean up
                final_path.unlink()
                chunks_dir.rmdir()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File integrity check failed"
                )
            
            # Security validation
            await check_file_security(file_content, chunk_data.filename)
            
            # Create import batch record
            import_batch = ImportBatch(
                id=batch_id,
                tenant_id=tenant_id,
                filename=temp_filename,
                original_filename=chunk_data.filename,
                file_size=chunk_data.total_size,
                file_hash=file_hash,
                mime_type='text/csv',
                storage_path=str(final_path),
                status=ImportBatchStatus.PENDING,
                created_by=current_user.id,
                upload_started_at=datetime.utcnow(),
                upload_completed_at=datetime.utcnow()
            )
            
            db.add(import_batch)
            db.commit()
            
            # Clean up chunks
            for chunk_file in chunks_dir.glob("chunk_*"):
                chunk_file.unlink()
            chunks_dir.rmdir()
            
            # Process metadata in background
            background_tasks.add_task(
                process_csv_metadata_task,
                str(final_path),
                batch_id,
                tenant_id
            )
            
            return FileUploadResponse(
                batch_id=batch_id,
                filename=chunk_data.filename,
                file_size=chunk_data.total_size,
                status=ImportBatchStatus.PENDING.value,
                message="File reassembled successfully. Processing metadata...",
                metadata=None
            )
        else:
            # Return progress status
            progress = (len(received_chunks) / chunk_data.total_chunks) * 100
            return FileUploadResponse(
                batch_id=uuid4(),  # Temporary ID for tracking
                filename=chunk_data.filename,
                file_size=chunk_data.total_size,
                status="uploading",
                message=f"Received {len(received_chunks)}/{chunk_data.total_chunks} chunks ({progress:.1f}%)",
                metadata={"chunks_received": len(received_chunks), "total_chunks": chunk_data.total_chunks}
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chunked upload: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process chunk: {str(e)}"
        )


@router.get("/{batch_id}/status", response_model=ImportStatusResponse)
async def get_import_status(
    batch_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> ImportStatusResponse:
    """
    Get current import status and progress information.
    
    Returns detailed status including progress, record counts, and error summaries.
    """
    try:
        import_batch = db.query(ImportBatch).filter(
            ImportBatch.id == batch_id,
            ImportBatch.tenant_id == tenant_id
        ).first()
        
        if not import_batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Import batch not found"
            )
        
        return ImportStatusResponse(
            batch_id=import_batch.id,
            status=import_batch.status,
            progress_percentage=import_batch.progress_percentage,
            total_records=import_batch.total_records,
            processed_records=import_batch.processed_records,
            successful_records=import_batch.successful_records,
            error_records=import_batch.error_records,
            duplicate_records=import_batch.duplicate_records,
            processing_stage=import_batch.processing_stage,
            created_at=import_batch.created_at,
            processing_started_at=import_batch.processing_started_at,
            processing_completed_at=import_batch.processing_completed_at,
            error_summary=import_batch.error_summary
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting import status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get import status"
        )


@router.get("/{batch_id}/metadata")
async def get_csv_metadata(
    batch_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get CSV file metadata including structure, preview data, and column analysis.
    
    Used by frontend to configure column mapping before processing.
    """
    try:
        import_batch = db.query(ImportBatch).filter(
            ImportBatch.id == batch_id,
            ImportBatch.tenant_id == tenant_id
        ).first()
        
        if not import_batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Import batch not found"
            )
        
        # Get metadata from preview_data field or Redis cache
        redis_service = RedisService()
        cache_key = f"csv_metadata:{batch_id}"
        metadata = await redis_service.get_json(cache_key)
        
        if not metadata and import_batch.preview_data:
            metadata = import_batch.preview_data
        
        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="CSV metadata not available. File may still be processing."
            )
        
        return metadata
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting CSV metadata: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get CSV metadata"
        )


@router.post("/{batch_id}/process")
async def start_processing(
    batch_id: UUID,
    mapping_config: ColumnMappingRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Start processing CSV file with provided column mapping configuration.
    
    Begins the validation and import process in the background with real-time
    progress updates via WebSocket.
    """
    try:
        import_batch = db.query(ImportBatch).filter(
            ImportBatch.id == batch_id,
            ImportBatch.tenant_id == tenant_id
        ).first()
        
        if not import_batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Import batch not found"
            )
        
        if import_batch.status != ImportBatchStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Import batch is not in pending status: {import_batch.status}"
            )
        
        # Update batch with column mapping
        import_batch.column_mapping = mapping_config.column_mapping
        import_batch.status = ImportBatchStatus.PROCESSING
        import_batch.processing_started_at = datetime.utcnow()
        import_batch.updated_by = current_user.id
        
        db.commit()
        
        # Start processing in background
        background_tasks.add_task(
            process_invoice_import_task,
            batch_id,
            tenant_id,
            current_user.id
        )
        
        return {
            "message": "Processing started",
            "batch_id": batch_id,
            "status": ImportBatchStatus.PROCESSING.value
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting processing: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start processing"
        )


@router.delete("/{batch_id}/cancel")
async def cancel_import(
    batch_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Cancel an in-progress import operation.
    
    Attempts to gracefully stop processing and clean up resources.
    """
    try:
        import_batch = db.query(ImportBatch).filter(
            ImportBatch.id == batch_id,
            ImportBatch.tenant_id == tenant_id
        ).first()
        
        if not import_batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Import batch not found"
            )
        
        if import_batch.status not in [ImportBatchStatus.PROCESSING, ImportBatchStatus.UPLOADING]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel import in status: {import_batch.status}"
            )
        
        # Update status
        import_batch.status = ImportBatchStatus.CANCELLED
        import_batch.processing_completed_at = datetime.utcnow()
        import_batch.updated_by = current_user.id
        
        db.commit()
        
        # Signal cancellation via Redis
        redis_service = RedisService()
        await redis_service.set(f"cancel_import:{batch_id}", "true", expire=3600)
        
        return {"message": "Import cancelled successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling import: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel import"
        )


@router.get("/{batch_id}/errors")
async def get_import_errors(
    batch_id: UUID,
    skip: int = 0,
    limit: int = 100,
    error_type: Optional[str] = None,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get paginated list of import errors for a batch.
    
    Supports filtering by error type and pagination for large error sets.
    """
    try:
        import_batch = db.query(ImportBatch).filter(
            ImportBatch.id == batch_id,
            ImportBatch.tenant_id == tenant_id
        ).first()
        
        if not import_batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Import batch not found"
            )
        
        # Build query
        query = db.query(ImportError).filter(
            ImportError.import_batch_id == batch_id,
            ImportError.tenant_id == tenant_id
        )
        
        if error_type:
            query = query.filter(ImportError.error_type == error_type)
        
        # Get total count
        total_count = query.count()
        
        # Get paginated results
        errors = query.offset(skip).limit(limit).all()
        
        # Convert to response format
        error_list = []
        for error in errors:
            error_list.append({
                "id": error.id,
                "row_number": error.row_number,
                "column_name": error.column_name,
                "error_type": error.error_type,
                "error_code": error.error_code,
                "error_message": error.error_message,
                "severity": error.severity,
                "raw_value": error.raw_value,
                "expected_format": error.expected_format,
                "suggested_fix": error.suggested_fix,
                "created_at": error.created_at
            })
        
        return {
            "batch_id": batch_id,
            "total_errors": total_count,
            "errors": error_list,
            "pagination": {
                "skip": skip,
                "limit": limit,
                "total": total_count,
                "has_more": skip + limit < total_count
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting import errors: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get import errors"
        )


@router.get("/{batch_id}/errors/download")
async def download_error_report(
    batch_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> StreamingResponse:
    """
    Download comprehensive error report as CSV file.
    
    Generates a detailed CSV report of all errors for offline analysis.
    """
    try:
        import_batch = db.query(ImportBatch).filter(
            ImportBatch.id == batch_id,
            ImportBatch.tenant_id == tenant_id
        ).first()
        
        if not import_batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Import batch not found"
            )
        
        # Generate error report
        import_service = InvoiceImportService(db, tenant_id)
        error_report_content = await import_service.generate_error_report(batch_id)
        
        # Create streaming response
        def generate_csv():
            yield error_report_content
        
        filename = f"import_errors_{batch_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating error report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate error report"
        )


# Background task functions
async def process_csv_metadata_task(file_path: str, batch_id: UUID, tenant_id: UUID):
    """Background task to process CSV metadata."""
    from app.core.database import get_db_session
    
    try:
        with get_db_session() as db:
            processor = CSVProcessor(db, tenant_id)
            metadata = processor.parse_csv_metadata(file_path)
            
            # Update import batch with metadata
            import_batch = db.query(ImportBatch).filter(
                ImportBatch.id == batch_id
            ).first()
            
            if import_batch:
                import_batch.preview_data = metadata
                import_batch.csv_delimiter = metadata['delimiter']
                import_batch.csv_encoding = metadata['encoding']
                import_batch.has_header = metadata['has_header']
                import_batch.total_records = metadata['estimated_rows']
                import_batch.updated_at = datetime.utcnow()
                
                db.commit()
                
                # Cache metadata in Redis
                redis_service = RedisService()
                await redis_service.set_json(
                    f"csv_metadata:{batch_id}",
                    metadata,
                    expire=3600  # 1 hour
                )
                
                logger.info(f"CSV metadata processed for batch {batch_id}")
    
    except Exception as e:
        logger.error(f"Error processing CSV metadata: {e}")
        # Update batch status to failed
        try:
            with get_db_session() as db:
                import_batch = db.query(ImportBatch).filter(
                    ImportBatch.id == batch_id
                ).first()
                
                if import_batch:
                    import_batch.status = ImportBatchStatus.FAILED
                    import_batch.error_summary = {"metadata_error": str(e)}
                    db.commit()
        except Exception as update_error:
            logger.error(f"Error updating batch status: {update_error}")


async def process_invoice_import_task(batch_id: UUID, tenant_id: UUID, user_id: UUID):
    """Background task to process invoice import."""
    from app.core.database import get_db_session
    
    try:
        with get_db_session() as db:
            import_service = InvoiceImportService(db, tenant_id)
            await import_service.process_import_batch(batch_id, user_id)
            
    except Exception as e:
        logger.error(f"Error processing import batch {batch_id}: {e}")
        # Error handling is done within the import service