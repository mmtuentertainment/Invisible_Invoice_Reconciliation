"""
Unit tests for CSV processor service.

Tests cover:
- CSV parsing and metadata extraction
- Encoding detection and handling
- Delimiter auto-detection
- Header detection
- Data type analysis
- Column mapping suggestions
- Error handling and edge cases
"""

import io
import pytest
from decimal import Decimal
from datetime import date
from unittest.mock import Mock, patch

from app.services.csv_processor import CSVProcessor, CSVProcessingError, CSVProcessorConfig
from app.models.financial import ImportBatch, ImportBatchStatus


@pytest.fixture
def mock_db():
    """Mock database session."""
    return Mock()


@pytest.fixture
def tenant_id():
    """Mock tenant ID."""
    from uuid import uuid4
    return uuid4()


@pytest.fixture
def csv_processor(mock_db, tenant_id):
    """CSV processor instance."""
    return CSVProcessor(mock_db, tenant_id)


class TestCSVProcessor:
    """Test CSV processor functionality."""
    
    def test_detect_encoding_utf8(self, csv_processor):
        """Test UTF-8 encoding detection."""
        content = "invoice_number,vendor,amount\nINV001,Test Vendor,100.50".encode('utf-8')
        
        encoding = csv_processor.detect_encoding(content)
        assert encoding == 'utf-8'
    
    def test_detect_encoding_fallback(self, csv_processor):
        """Test encoding fallback for unknown encoding."""
        # Binary content that won't match any encoding
        content = b'\x80\x81\x82\x83' * 100
        
        encoding = csv_processor.detect_encoding(content)
        assert encoding == 'utf-8'  # Should fallback to utf-8
    
    def test_detect_delimiter_comma(self, csv_processor):
        """Test comma delimiter detection."""
        sample = "invoice_number,vendor,amount\nINV001,Test Vendor,100.50"
        
        delimiter = csv_processor.detect_delimiter(sample)
        assert delimiter == ','
    
    def test_detect_delimiter_tab(self, csv_processor):
        """Test tab delimiter detection."""
        sample = "invoice_number\tvendor\tamount\nINV001\tTest Vendor\t100.50"
        
        delimiter = csv_processor.detect_delimiter(sample)
        assert delimiter == '\t'
    
    def test_detect_delimiter_pipe(self, csv_processor):
        """Test pipe delimiter detection."""
        sample = "invoice_number|vendor|amount\nINV001|Test Vendor|100.50"
        
        delimiter = csv_processor.detect_delimiter(sample)
        assert delimiter == '|'
    
    def test_detect_has_header_true(self, csv_processor):
        """Test header detection when header is present."""
        lines = [
            "invoice_number,vendor_name,total_amount,invoice_date",
            "INV001,ACME Corp,150.00,2023-01-15"
        ]
        
        has_header = csv_processor.detect_has_header(lines, ',')
        assert has_header is True
    
    def test_detect_has_header_false(self, csv_processor):
        """Test header detection when header is absent."""
        lines = [
            "INV001,ACME Corp,150.00,2023-01-15",
            "INV002,Beta Inc,75.50,2023-01-16"
        ]
        
        has_header = csv_processor.detect_has_header(lines, ',')
        assert has_header is False
    
    def test_is_numeric_true(self, csv_processor):
        """Test numeric value detection."""
        assert csv_processor._is_numeric("123.45") is True
        assert csv_processor._is_numeric("$1,234.56") is True
        assert csv_processor._is_numeric("€999.99") is True
    
    def test_is_numeric_false(self, csv_processor):
        """Test non-numeric value detection."""
        assert csv_processor._is_numeric("ACME Corp") is False
        assert csv_processor._is_numeric("") is False
        assert csv_processor._is_numeric("N/A") is False
    
    def test_detect_column_type_numeric(self, csv_processor):
        """Test numeric column type detection."""
        values = ["123.45", "67.89", "$1,000.00", "€500.75"]
        
        column_type = csv_processor._detect_column_type(values)
        assert column_type == 'numeric'
    
    def test_detect_column_type_date(self, csv_processor):
        """Test date column type detection."""
        values = ["2023-01-15", "2023-01-16", "2023-01-17"]
        
        column_type = csv_processor._detect_column_type(values)
        assert column_type == 'date'
    
    def test_detect_column_type_text(self, csv_processor):
        """Test text column type detection."""
        values = ["ACME Corp", "Beta Inc", "Gamma LLC"]
        
        column_type = csv_processor._detect_column_type(values)
        assert column_type == 'text'
    
    def test_suggest_column_mapping_invoice_number(self, csv_processor):
        """Test invoice number column mapping suggestion."""
        header = "Invoice Number"
        values = ["INV001", "INV002"]
        
        mapping = csv_processor._suggest_column_mapping(header, values)
        assert mapping == 'invoice_number'
    
    def test_suggest_column_mapping_vendor(self, csv_processor):
        """Test vendor column mapping suggestion."""
        header = "Vendor Name"
        values = ["ACME Corp", "Beta Inc"]
        
        mapping = csv_processor._suggest_column_mapping(header, values)
        assert mapping == 'vendor'
    
    def test_suggest_column_mapping_amount(self, csv_processor):
        """Test amount column mapping suggestion."""
        header = "Total Amount"
        values = ["100.50", "75.25"]
        
        mapping = csv_processor._suggest_column_mapping(header, values)
        assert mapping == 'amount'
    
    def test_validate_required_mapping_success(self, csv_processor):
        """Test successful required mapping validation."""
        column_mapping = {
            'Invoice Number': 'invoice_number',
            'Vendor Name': 'vendor',
            'Total': 'amount',
            'Date': 'invoice_date'
        }
        
        errors = csv_processor.validate_required_mapping(column_mapping)
        assert len(errors) == 0
    
    def test_validate_required_mapping_missing_fields(self, csv_processor):
        """Test required mapping validation with missing fields."""
        column_mapping = {
            'Invoice Number': 'invoice_number',
            'Vendor Name': 'vendor'
            # Missing amount and invoice_date
        }
        
        errors = csv_processor.validate_required_mapping(column_mapping)
        assert len(errors) == 2
        assert "Required field 'amount' is not mapped" in errors[0]
        assert "Required field 'invoice_date' is not mapped" in errors[1]
    
    def test_normalize_date_iso_format(self, csv_processor):
        """Test date normalization for ISO format."""
        date_str = "2023-01-15"
        
        result = csv_processor.normalize_date(date_str)
        assert result == date(2023, 1, 15)
    
    def test_normalize_date_us_format(self, csv_processor):
        """Test date normalization for US format."""
        date_str = "01/15/2023"
        
        result = csv_processor.normalize_date(date_str)
        assert result == date(2023, 1, 15)
    
    def test_normalize_date_invalid(self, csv_processor):
        """Test date normalization for invalid date."""
        date_str = "invalid-date"
        
        result = csv_processor.normalize_date(date_str)
        assert result is None
    
    def test_normalize_currency_simple(self, csv_processor):
        """Test currency normalization for simple amount."""
        amount_str = "123.45"
        
        result = csv_processor.normalize_currency(amount_str)
        assert result == Decimal('123.45')
    
    def test_normalize_currency_with_symbols(self, csv_processor):
        """Test currency normalization with currency symbols."""
        amount_str = "$1,234.56"
        
        result = csv_processor.normalize_currency(amount_str)
        assert result == Decimal('1234.56')
    
    def test_normalize_currency_negative(self, csv_processor):
        """Test currency normalization for negative amount."""
        amount_str = "-123.45"
        
        result = csv_processor.normalize_currency(amount_str)
        assert result == Decimal('-123.45')
    
    def test_normalize_currency_parentheses(self, csv_processor):
        """Test currency normalization with parentheses for negative."""
        amount_str = "(123.45)"
        
        result = csv_processor.normalize_currency(amount_str)
        assert result == Decimal('-123.45')
    
    def test_normalize_currency_invalid(self, csv_processor):
        """Test currency normalization for invalid amount."""
        amount_str = "not-a-number"
        
        result = csv_processor.normalize_currency(amount_str)
        assert result is None
    
    def test_normalize_vendor_name(self, csv_processor):
        """Test vendor name normalization."""
        vendor_str = "  acme corporation llc  "
        
        result = csv_processor.normalize_vendor_name(vendor_str)
        assert result == "ACME CORPORATION"  # Should remove LLC and normalize
    
    @patch('builtins.open', create=True)
    def test_parse_csv_metadata_success(self, mock_open, csv_processor):
        """Test successful CSV metadata parsing."""
        csv_content = """invoice_number,vendor_name,amount,date
INV001,ACME Corp,150.00,2023-01-15
INV002,Beta Inc,75.50,2023-01-16"""
        
        mock_file = io.StringIO(csv_content)
        mock_open.return_value.__enter__.return_value = mock_file
        
        with patch('builtins.open', mock_open):
            with patch.object(csv_processor, 'detect_encoding', return_value='utf-8'):
                metadata = csv_processor.parse_csv_metadata('test.csv')
        
        assert metadata['encoding'] == 'utf-8'
        assert metadata['delimiter'] == ','
        assert metadata['has_header'] is True
        assert metadata['column_count'] == 4
        assert 'invoice_number' in metadata['headers']
        assert len(metadata['preview_data']) >= 1
    
    def test_parse_csv_metadata_empty_file(self, csv_processor):
        """Test CSV metadata parsing for empty file."""
        with patch('builtins.open', create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = b''
            
            with pytest.raises(CSVProcessingError, match="File appears to be empty"):
                csv_processor.parse_csv_metadata('empty.csv')
    
    def test_parse_csv_metadata_file_too_large(self, csv_processor):
        """Test CSV metadata parsing for oversized file."""
        large_content = b'a' * (CSVProcessorConfig.MAX_FILE_SIZE + 1)
        
        with patch('builtins.open', create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = large_content
            
            with pytest.raises(CSVProcessingError, match="exceeds maximum allowed size"):
                csv_processor.parse_csv_metadata('large.csv')


class TestProcessSingleRow:
    """Test single row processing functionality."""
    
    @pytest.fixture
    def column_mapping(self):
        """Standard column mapping."""
        return {
            'Invoice Number': 'invoice_number',
            'Vendor': 'vendor',
            'Amount': 'amount',
            'Date': 'invoice_date'
        }
    
    def test_process_single_row_success(self, csv_processor, column_mapping):
        """Test successful single row processing."""
        row = {
            'Invoice Number': 'INV001',
            'Vendor': 'ACME Corp',
            'Amount': '150.00',
            'Date': '2023-01-15'
        }
        
        result = csv_processor._process_single_row(row, column_mapping, 1)
        
        assert result['row_number'] == 1
        assert result['normalized_data']['invoice_number'] == 'INV001'
        assert result['normalized_data']['vendor_name'] == 'ACME CORP'
        assert result['normalized_data']['total_amount'] == Decimal('150.00')
        assert result['normalized_data']['invoice_date'] == date(2023, 1, 15)
        assert len(result['errors']) == 0
    
    def test_process_single_row_missing_required_field(self, csv_processor, column_mapping):
        """Test processing row with missing required field."""
        row = {
            'Invoice Number': '',  # Missing required field
            'Vendor': 'ACME Corp',
            'Amount': '150.00',
            'Date': '2023-01-15'
        }
        
        result = csv_processor._process_single_row(row, column_mapping, 1)
        
        assert len(result['errors']) > 0
        assert any(error['code'] == 'MISSING_INVOICE_NUMBER' for error in result['errors'])
    
    def test_process_single_row_invalid_amount(self, csv_processor, column_mapping):
        """Test processing row with invalid amount."""
        row = {
            'Invoice Number': 'INV001',
            'Vendor': 'ACME Corp',
            'Amount': 'invalid-amount',
            'Date': '2023-01-15'
        }
        
        result = csv_processor._process_single_row(row, column_mapping, 1)
        
        assert len(result['errors']) > 0
        assert any(error['code'] == 'INVALID_AMOUNT' for error in result['errors'])
    
    def test_process_single_row_negative_amount(self, csv_processor, column_mapping):
        """Test processing row with negative amount."""
        row = {
            'Invoice Number': 'INV001',
            'Vendor': 'ACME Corp',
            'Amount': '-150.00',
            'Date': '2023-01-15'
        }
        
        result = csv_processor._process_single_row(row, column_mapping, 1)
        
        assert len(result['errors']) > 0
        assert any(error['code'] == 'NEGATIVE_AMOUNT' for error in result['errors'])
    
    def test_process_single_row_invalid_date(self, csv_processor, column_mapping):
        """Test processing row with invalid date."""
        row = {
            'Invoice Number': 'INV001',
            'Vendor': 'ACME Corp',
            'Amount': '150.00',
            'Date': 'invalid-date'
        }
        
        result = csv_processor._process_single_row(row, column_mapping, 1)
        
        assert len(result['errors']) > 0
        assert any(error['code'] == 'INVALID_DATE' for error in result['errors'])
    
    def test_process_single_row_future_date_warning(self, csv_processor, column_mapping):
        """Test processing row with future date generates warning."""
        from datetime import datetime, timedelta
        future_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        row = {
            'Invoice Number': 'INV001',
            'Vendor': 'ACME Corp',
            'Amount': '150.00',
            'Date': future_date
        }
        
        result = csv_processor._process_single_row(row, column_mapping, 1)
        
        assert len(result['warnings']) > 0
        assert any(warning['code'] == 'FUTURE_DATE' for warning in result['warnings'])


@pytest.mark.asyncio
class TestProcessCSVStream:
    """Test CSV streaming functionality."""
    
    async def test_process_csv_stream_success(self, csv_processor):
        """Test successful CSV stream processing."""
        # Create mock import batch
        import_batch = Mock()
        import_batch.csv_encoding = 'utf-8'
        import_batch.csv_delimiter = ','
        import_batch.has_header = True
        
        column_mapping = {
            'invoice_number': 'invoice_number',
            'vendor': 'vendor',
            'amount': 'amount',
            'date': 'invoice_date'
        }
        
        csv_content = """invoice_number,vendor,amount,date
INV001,ACME Corp,150.00,2023-01-15
INV002,Beta Inc,75.50,2023-01-16"""
        
        with patch('builtins.open', create=True) as mock_open:
            mock_open.return_value.__enter__.return_value = io.StringIO(csv_content)
            
            results = list(csv_processor.process_csv_stream('test.csv', column_mapping, import_batch))
        
        assert len(results) == 2
        assert results[0]['row_number'] == 2  # First data row after header
        assert results[0]['normalized_data']['invoice_number'] == 'INV001'
        assert results[1]['row_number'] == 3
        assert results[1]['normalized_data']['invoice_number'] == 'INV002'