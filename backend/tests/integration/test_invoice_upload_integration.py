"""
Integration tests for invoice upload functionality.

Tests the complete upload flow including:
- File upload endpoints
- CSV processing
- WebSocket notifications
- Error handling
- Database persistence
"""

import asyncio
import io
import json
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import get_db
from app.models.financial import Base, ImportBatch, ImportError
from app.services.websocket_service import connection_manager


# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_invoice_upload.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture
def test_csv_content():
    """Sample CSV content for testing."""
    return """invoice_number,vendor_name,total_amount,invoice_date
INV001,ACME Corporation,150.00,2023-01-15
INV002,Beta Industries,75.50,2023-01-16
INV003,Gamma LLC,225.75,2023-01-17"""


@pytest.fixture
def invalid_csv_content():
    """Invalid CSV content for testing error handling."""
    return """invoice_number,vendor_name,total_amount,invoice_date
INV001,ACME Corporation,invalid_amount,2023-01-15
INV002,,75.50,invalid_date
INV003,Gamma LLC,-100.00,2023-01-17"""


@pytest.fixture
def mock_user_token():
    """Mock authentication token."""
    # In a real test, you'd generate a proper JWT token
    return "mock_jwt_token"


@pytest.fixture
def mock_tenant_id():
    """Mock tenant ID."""
    return str(uuid4())


class TestFileUpload:
    """Test file upload functionality."""
    
    def test_upload_valid_csv_file(self, test_csv_content, mock_user_token):
        """Test uploading a valid CSV file."""
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp_file:
            tmp_file.write(test_csv_content)
            tmp_file_path = tmp_file.name
        
        try:
            # Upload file
            with open(tmp_file_path, 'rb') as f:
                response = client.post(
                    "/api/v1/invoices/upload",
                    files={"file": ("test_invoices.csv", f, "text/csv")},
                    headers={"Authorization": f"Bearer {mock_user_token}"}
                )
            
            assert response.status_code == 200
            data = response.json()
            
            assert "batch_id" in data
            assert data["filename"] == "test_invoices.csv"
            assert data["status"] == "pending"
            assert "file_size" in data
            
        finally:
            # Clean up
            Path(tmp_file_path).unlink(missing_ok=True)
    
    def test_upload_invalid_file_type(self, mock_user_token):
        """Test uploading an invalid file type."""
        # Create a fake image file
        fake_image_content = b'\x89PNG\r\n\x1a\n' + b'fake image data'
        
        response = client.post(
            "/api/v1/invoices/upload",
            files={"file": ("image.png", fake_image_content, "image/png")},
            headers={"Authorization": f"Bearer {mock_user_token}"}
        )
        
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]
    
    def test_upload_oversized_file(self, mock_user_token):
        """Test uploading a file that exceeds size limit."""
        # Create oversized content (simulate 60MB file)
        oversized_content = b'a' * (60 * 1024 * 1024)
        
        response = client.post(
            "/api/v1/invoices/upload",
            files={"file": ("huge_file.csv", oversized_content, "text/csv")},
            headers={"Authorization": f"Bearer {mock_user_token}"}
        )
        
        assert response.status_code == 413
        assert "exceeds maximum allowed size" in response.json()["detail"]
    
    def test_upload_empty_file(self, mock_user_token):
        """Test uploading an empty file."""
        empty_content = b''
        
        response = client.post(
            "/api/v1/invoices/upload",
            files={"file": ("empty.csv", empty_content, "text/csv")},
            headers={"Authorization": f"Bearer {mock_user_token}"}
        )
        
        assert response.status_code == 400
        assert "File is empty" in response.json()["detail"]


class TestChunkedUpload:
    """Test chunked file upload functionality."""
    
    def test_chunked_upload_single_chunk(self, test_csv_content, mock_user_token):
        """Test chunked upload with a single chunk."""
        chunk_content = test_csv_content.encode('utf-8')
        chunk_info = {
            "chunk_number": 0,
            "total_chunks": 1,
            "chunk_size": len(chunk_content),
            "total_size": len(chunk_content),
            "filename": "test_chunked.csv"
        }
        
        response = client.post(
            "/api/v1/invoices/upload/chunked",
            files={"chunk": ("chunk_0", chunk_content, "application/octet-stream")},
            data={"chunk_info": json.dumps(chunk_info)},
            headers={"Authorization": f"Bearer {mock_user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "batch_id" in data
        assert data["filename"] == "test_chunked.csv"
    
    def test_chunked_upload_multiple_chunks(self, test_csv_content, mock_user_token):
        """Test chunked upload with multiple chunks."""
        content = test_csv_content.encode('utf-8')
        chunk_size = len(content) // 2
        total_chunks = 2
        
        # Upload first chunk
        chunk1 = content[:chunk_size]
        chunk_info1 = {
            "chunk_number": 0,
            "total_chunks": total_chunks,
            "chunk_size": len(chunk1),
            "total_size": len(content),
            "filename": "test_multi_chunk.csv"
        }
        
        response1 = client.post(
            "/api/v1/invoices/upload/chunked",
            files={"chunk": ("chunk_0", chunk1, "application/octet-stream")},
            data={"chunk_info": json.dumps(chunk_info1)},
            headers={"Authorization": f"Bearer {mock_user_token}"}
        )
        
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["status"] == "uploading"
        
        # Upload second chunk
        chunk2 = content[chunk_size:]
        chunk_info2 = {
            "chunk_number": 1,
            "total_chunks": total_chunks,
            "chunk_size": len(chunk2),
            "total_size": len(content),
            "filename": "test_multi_chunk.csv"
        }
        
        response2 = client.post(
            "/api/v1/invoices/upload/chunked",
            files={"chunk": ("chunk_1", chunk2, "application/octet-stream")},
            data={"chunk_info": json.dumps(chunk_info2)},
            headers={"Authorization": f"Bearer {mock_user_token}"}
        )
        
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["status"] != "uploading"  # Should be complete


class TestMetadataExtraction:
    """Test CSV metadata extraction."""
    
    def test_get_csv_metadata(self, test_csv_content, mock_user_token):
        """Test getting CSV metadata after upload."""
        # First upload a file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp_file:
            tmp_file.write(test_csv_content)
            tmp_file_path = tmp_file.name
        
        try:
            # Upload file
            with open(tmp_file_path, 'rb') as f:
                upload_response = client.post(
                    "/api/v1/invoices/upload",
                    files={"file": ("test_metadata.csv", f, "text/csv")},
                    headers={"Authorization": f"Bearer {mock_user_token}"}
                )
            
            batch_id = upload_response.json()["batch_id"]
            
            # Wait a bit for metadata processing
            import time
            time.sleep(1)
            
            # Get metadata
            metadata_response = client.get(
                f"/api/v1/invoices/upload/{batch_id}/metadata",
                headers={"Authorization": f"Bearer {mock_user_token}"}
            )
            
            assert metadata_response.status_code == 200
            metadata = metadata_response.json()
            
            assert metadata["encoding"] in ["utf-8", "ascii"]
            assert metadata["delimiter"] == ","
            assert metadata["has_header"] is True
            assert metadata["column_count"] == 4
            assert "invoice_number" in metadata["headers"]
            assert "preview_data" in metadata
            assert len(metadata["preview_data"]) >= 1
            
        finally:
            Path(tmp_file_path).unlink(missing_ok=True)


class TestImportProcessing:
    """Test import processing functionality."""
    
    def test_start_processing_with_valid_mapping(self, test_csv_content, mock_user_token):
        """Test starting processing with valid column mapping."""
        # Upload and get metadata first
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp_file:
            tmp_file.write(test_csv_content)
            tmp_file_path = tmp_file.name
        
        try:
            # Upload
            with open(tmp_file_path, 'rb') as f:
                upload_response = client.post(
                    "/api/v1/invoices/upload",
                    files={"file": ("test_process.csv", f, "text/csv")},
                    headers={"Authorization": f"Bearer {mock_user_token}"}
                )
            
            batch_id = upload_response.json()["batch_id"]
            
            # Start processing
            column_mapping = {
                "invoice_number": "invoice_number",
                "vendor_name": "vendor", 
                "total_amount": "amount",
                "invoice_date": "invoice_date"
            }
            
            process_response = client.post(
                f"/api/v1/invoices/upload/{batch_id}/process",
                json={"column_mapping": column_mapping},
                headers={"Authorization": f"Bearer {mock_user_token}"}
            )
            
            assert process_response.status_code == 200
            data = process_response.json()
            
            assert data["batch_id"] == batch_id
            assert data["status"] == "processing"
            
        finally:
            Path(tmp_file_path).unlink(missing_ok=True)
    
    def test_start_processing_with_invalid_mapping(self, test_csv_content, mock_user_token):
        """Test starting processing with invalid column mapping."""
        # Upload file first
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp_file:
            tmp_file.write(test_csv_content)
            tmp_file_path = tmp_file.name
        
        try:
            with open(tmp_file_path, 'rb') as f:
                upload_response = client.post(
                    "/api/v1/invoices/upload",
                    files={"file": ("test_invalid_mapping.csv", f, "text/csv")},
                    headers={"Authorization": f"Bearer {mock_user_token}"}
                )
            
            batch_id = upload_response.json()["batch_id"]
            
            # Start processing with incomplete mapping
            incomplete_mapping = {
                "invoice_number": "invoice_number"
                # Missing required fields
            }
            
            process_response = client.post(
                f"/api/v1/invoices/upload/{batch_id}/process",
                json={"column_mapping": incomplete_mapping},
                headers={"Authorization": f"Bearer {mock_user_token}"}
            )
            
            # Should fail validation
            assert process_response.status_code == 400
            
        finally:
            Path(tmp_file_path).unlink(missing_ok=True)


class TestImportStatus:
    """Test import status tracking."""
    
    def test_get_import_status(self, test_csv_content, mock_user_token):
        """Test getting import status."""
        # Upload file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp_file:
            tmp_file.write(test_csv_content)
            tmp_file_path = tmp_file.name
        
        try:
            with open(tmp_file_path, 'rb') as f:
                upload_response = client.post(
                    "/api/v1/invoices/upload",
                    files={"file": ("test_status.csv", f, "text/csv")},
                    headers={"Authorization": f"Bearer {mock_user_token}"}
                )
            
            batch_id = upload_response.json()["batch_id"]
            
            # Get status
            status_response = client.get(
                f"/api/v1/invoices/upload/{batch_id}/status",
                headers={"Authorization": f"Bearer {mock_user_token}"}
            )
            
            assert status_response.status_code == 200
            data = status_response.json()
            
            assert data["batch_id"] == batch_id
            assert "status" in data
            assert "progress_percentage" in data
            assert "total_records" in data
            
        finally:
            Path(tmp_file_path).unlink(missing_ok=True)


class TestErrorHandling:
    """Test error handling and reporting."""
    
    def test_get_import_errors(self, invalid_csv_content, mock_user_token):
        """Test getting import errors after processing invalid data."""
        # Upload invalid CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp_file:
            tmp_file.write(invalid_csv_content)
            tmp_file_path = tmp_file.name
        
        try:
            with open(tmp_file_path, 'rb') as f:
                upload_response = client.post(
                    "/api/v1/invoices/upload",
                    files={"file": ("test_errors.csv", f, "text/csv")},
                    headers={"Authorization": f"Bearer {mock_user_token}"}
                )
            
            batch_id = upload_response.json()["batch_id"]
            
            # Start processing to generate errors
            column_mapping = {
                "invoice_number": "invoice_number",
                "vendor_name": "vendor", 
                "total_amount": "amount",
                "invoice_date": "invoice_date"
            }
            
            client.post(
                f"/api/v1/invoices/upload/{batch_id}/process",
                json={"column_mapping": column_mapping},
                headers={"Authorization": f"Bearer {mock_user_token}"}
            )
            
            # Wait for processing to complete
            import time
            time.sleep(2)
            
            # Get errors
            errors_response = client.get(
                f"/api/v1/invoices/upload/{batch_id}/errors",
                headers={"Authorization": f"Bearer {mock_user_token}"}
            )
            
            assert errors_response.status_code == 200
            data = errors_response.json()
            
            assert "total_errors" in data
            assert "errors" in data
            assert isinstance(data["errors"], list)
            
        finally:
            Path(tmp_file_path).unlink(missing_ok=True)
    
    def test_download_error_report(self, invalid_csv_content, mock_user_token):
        """Test downloading error report."""
        # Upload and process invalid CSV first
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp_file:
            tmp_file.write(invalid_csv_content)
            tmp_file_path = tmp_file.name
        
        try:
            with open(tmp_file_path, 'rb') as f:
                upload_response = client.post(
                    "/api/v1/invoices/upload",
                    files={"file": ("test_error_report.csv", f, "text/csv")},
                    headers={"Authorization": f"Bearer {mock_user_token}"}
                )
            
            batch_id = upload_response.json()["batch_id"]
            
            # Try to download error report
            download_response = client.get(
                f"/api/v1/invoices/upload/{batch_id}/errors/download",
                headers={"Authorization": f"Bearer {mock_user_token}"}
            )
            
            # Should return CSV content
            assert download_response.status_code == 200
            assert download_response.headers["content-type"] == "text/csv; charset=utf-8"
            
        finally:
            Path(tmp_file_path).unlink(missing_ok=True)


class TestImportCancellation:
    """Test import cancellation functionality."""
    
    def test_cancel_import(self, test_csv_content, mock_user_token):
        """Test cancelling an import."""
        # Upload file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp_file:
            tmp_file.write(test_csv_content)
            tmp_file_path = tmp_file.name
        
        try:
            with open(tmp_file_path, 'rb') as f:
                upload_response = client.post(
                    "/api/v1/invoices/upload",
                    files={"file": ("test_cancel.csv", f, "text/csv")},
                    headers={"Authorization": f"Bearer {mock_user_token}"}
                )
            
            batch_id = upload_response.json()["batch_id"]
            
            # Start processing
            column_mapping = {
                "invoice_number": "invoice_number",
                "vendor_name": "vendor", 
                "total_amount": "amount",
                "invoice_date": "invoice_date"
            }
            
            client.post(
                f"/api/v1/invoices/upload/{batch_id}/process",
                json={"column_mapping": column_mapping},
                headers={"Authorization": f"Bearer {mock_user_token}"}
            )
            
            # Cancel import
            cancel_response = client.delete(
                f"/api/v1/invoices/upload/{batch_id}/cancel",
                headers={"Authorization": f"Bearer {mock_user_token}"}
            )
            
            assert cancel_response.status_code == 200
            assert "cancelled successfully" in cancel_response.json()["message"]
            
        finally:
            Path(tmp_file_path).unlink(missing_ok=True)


@pytest.mark.asyncio
class TestWebSocketIntegration:
    """Test WebSocket integration for real-time updates."""
    
    async def test_websocket_connection(self, mock_tenant_id):
        """Test WebSocket connection establishment."""
        # This is a simplified test - in practice you'd use a WebSocket test client
        # For now, test the connection manager directly
        
        from unittest.mock import Mock
        
        mock_websocket = Mock()
        user_id = uuid4()
        
        await connection_manager.connect(mock_websocket, mock_tenant_id, user_id)
        
        assert mock_tenant_id in connection_manager.active_connections
        assert user_id in connection_manager.active_connections[mock_tenant_id]
        
        # Clean up
        connection_manager.disconnect(mock_tenant_id, user_id)
    
    async def test_websocket_subscription(self, mock_tenant_id):
        """Test WebSocket subscription to import progress."""
        from unittest.mock import Mock
        
        mock_websocket = Mock()
        user_id = uuid4()
        batch_id = uuid4()
        
        await connection_manager.connect(mock_websocket, mock_tenant_id, user_id)
        await connection_manager.subscribe_to_import(mock_tenant_id, user_id, batch_id)
        
        assert batch_id in connection_manager.import_subscriptions
        assert (mock_tenant_id, user_id) in connection_manager.import_subscriptions[batch_id]
        
        # Clean up
        connection_manager.disconnect(mock_tenant_id, user_id)


# Cleanup after all tests
def teardown_module():
    """Clean up test database."""
    import os
    if os.path.exists("test_invoice_upload.db"):
        os.remove("test_invoice_upload.db")