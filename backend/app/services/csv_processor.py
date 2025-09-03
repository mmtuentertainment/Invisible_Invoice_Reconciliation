"""
CSV processing engine for invoice imports with RFC 4180 compliance.

This module provides comprehensive CSV parsing, validation, and normalization 
capabilities for financial data import with security and performance considerations.
"""

import csv
import io
import logging
import re
import chardet
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple, Union, Any, Generator
from uuid import UUID
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.models.financial import ImportBatch, ImportError, ImportErrorType, Vendor
from app.core.config import settings

logger = logging.getLogger(__name__)


class CSVProcessingError(Exception):
    """Base exception for CSV processing errors."""
    pass


class CSVValidationError(CSVProcessingError):
    """Exception for CSV validation failures."""
    pass


class CSVParsingError(CSVProcessingError):
    """Exception for CSV parsing failures."""
    pass


class CSVProcessorConfig:
    """Configuration for CSV processing operations."""
    
    # File constraints
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    MAX_ROWS = 10000
    PREVIEW_ROWS = 10
    
    # Supported encodings in order of preference
    SUPPORTED_ENCODINGS = ['utf-8', 'utf-16', 'ascii', 'iso-8859-1', 'windows-1252']
    
    # Supported delimiters with auto-detection
    SUPPORTED_DELIMITERS = [',', '\t', '|', ';']
    
    # Required columns for invoice import
    REQUIRED_COLUMNS = ['invoice_number', 'vendor', 'amount', 'invoice_date']
    
    # Optional columns that can be mapped
    OPTIONAL_COLUMNS = [
        'po_reference', 'description', 'tax_amount', 'subtotal',
        'due_date', 'vendor_code', 'currency'
    ]
    
    # Date formats to try (in order)
    DATE_FORMATS = [
        '%Y-%m-%d',      # ISO 8601: 2023-12-25
        '%m/%d/%Y',      # US format: 12/25/2023
        '%d/%m/%Y',      # EU format: 25/12/2023
        '%Y/%m/%d',      # ISO variant: 2023/12/25
        '%m-%d-%Y',      # US variant: 12-25-2023
        '%d-%m-%Y',      # EU variant: 25-12-2023
        '%Y%m%d',        # Compact: 20231225
        '%m/%d/%y',      # US short: 12/25/23
        '%d/%m/%y',      # EU short: 25/12/23
    ]
    
    # Currency symbols to clean
    CURRENCY_SYMBOLS = ['$', '€', '£', '¥', '₹', 'USD', 'EUR', 'GBP', 'JPY', 'INR']


class CSVProcessor:
    """RFC 4180 compliant CSV processor for invoice data."""
    
    def __init__(self, db: Session, tenant_id: UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.config = CSVProcessorConfig()
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        
    def detect_encoding(self, file_content: bytes) -> str:
        """
        Detect file encoding using chardet with fallback options.
        
        Args:
            file_content: Raw file content as bytes
            
        Returns:
            Detected encoding string
            
        Raises:
            CSVProcessingError: If no supported encoding can be determined
        """
        try:
            # Use chardet for initial detection
            result = chardet.detect(file_content[:10000])  # Check first 10KB
            detected_encoding = result['encoding']
            confidence = result['confidence']
            
            logger.info(f"Chardet detected encoding: {detected_encoding} (confidence: {confidence})")
            
            # If confidence is high and encoding is supported, use it
            if confidence > 0.8 and detected_encoding.lower() in [enc.lower() for enc in self.config.SUPPORTED_ENCODINGS]:
                return detected_encoding.lower()
            
            # Try each supported encoding
            for encoding in self.config.SUPPORTED_ENCODINGS:
                try:
                    file_content.decode(encoding)
                    logger.info(f"Successfully decoded with {encoding}")
                    return encoding
                except UnicodeDecodeError:
                    continue
            
            # If all else fails, use utf-8 with error handling
            logger.warning("Could not detect encoding, defaulting to utf-8 with error replacement")
            return 'utf-8'
            
        except Exception as e:
            logger.error(f"Error detecting encoding: {e}")
            return 'utf-8'
    
    def detect_delimiter(self, sample_text: str) -> str:
        """
        Auto-detect CSV delimiter from sample text.
        
        Args:
            sample_text: Sample text from the CSV file
            
        Returns:
            Detected delimiter character
        """
        try:
            sniffer = csv.Sniffer()
            delimiter = sniffer.sniff(sample_text, delimiters=''.join(self.config.SUPPORTED_DELIMITERS)).delimiter
            
            if delimiter in self.config.SUPPORTED_DELIMITERS:
                logger.info(f"Detected delimiter: '{delimiter}'")
                return delimiter
        except Exception as e:
            logger.warning(f"Delimiter detection failed: {e}")
        
        # Fallback: count occurrences of each delimiter
        delimiter_counts = {}
        for delimiter in self.config.SUPPORTED_DELIMITERS:
            delimiter_counts[delimiter] = sample_text.count(delimiter)
        
        # Return delimiter with highest count
        best_delimiter = max(delimiter_counts, key=delimiter_counts.get)
        logger.info(f"Using delimiter with highest count: '{best_delimiter}' ({delimiter_counts[best_delimiter]} occurrences)")
        return best_delimiter
    
    def detect_has_header(self, lines: List[str], delimiter: str) -> bool:
        """
        Detect if CSV has header row by analyzing first few rows.
        
        Args:
            lines: First few lines of the CSV
            delimiter: Detected delimiter
            
        Returns:
            True if header row is detected
        """
        if len(lines) < 2:
            return True  # Assume header if only one line
        
        try:
            # Parse first two rows
            reader = csv.reader(lines[:2], delimiter=delimiter)
            first_row = next(reader)
            second_row = next(reader)
            
            # Check if first row contains non-numeric values while second row contains numbers
            first_row_numeric = sum(1 for cell in first_row if self._is_numeric(cell.strip()))
            second_row_numeric = sum(1 for cell in second_row if self._is_numeric(cell.strip()))
            
            # If first row has fewer numeric values, it's likely a header
            if len(first_row) > 0 and first_row_numeric / len(first_row) < 0.5:
                if len(second_row) > 0 and second_row_numeric / len(second_row) > 0.3:
                    return True
            
            # Check for common header keywords
            header_keywords = ['invoice', 'vendor', 'amount', 'date', 'number', 'total', 'tax']
            first_row_text = ' '.join(first_row).lower()
            header_keyword_matches = sum(1 for keyword in header_keywords if keyword in first_row_text)
            
            return header_keyword_matches >= 2
            
        except Exception as e:
            logger.warning(f"Header detection failed: {e}")
            return True  # Default to header
    
    def _is_numeric(self, value: str) -> bool:
        """Check if a string represents a numeric value."""
        try:
            # Remove common currency symbols and whitespace
            cleaned = re.sub(r'[$€£¥₹,\s]', '', value)
            if not cleaned:
                return False
            float(cleaned)
            return True
        except ValueError:
            return False
    
    def parse_csv_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        Parse CSV file and extract metadata including structure and preview.
        
        Args:
            file_path: Path to the CSV file
            
        Returns:
            Dictionary containing CSV metadata
            
        Raises:
            CSVProcessingError: If file cannot be parsed
        """
        try:
            # Read file content
            with open(file_path, 'rb') as f:
                raw_content = f.read()
            
            # Validate file size
            if len(raw_content) > self.config.MAX_FILE_SIZE:
                raise CSVProcessingError(f"File size {len(raw_content)} exceeds maximum allowed size {self.config.MAX_FILE_SIZE}")
            
            # Detect encoding
            encoding = self.detect_encoding(raw_content)
            
            # Decode content
            try:
                text_content = raw_content.decode(encoding, errors='replace')
            except Exception as e:
                raise CSVProcessingError(f"Failed to decode file with encoding {encoding}: {e}")
            
            # Get first few lines for analysis
            lines = text_content.split('\n')[:50]  # Analyze first 50 lines
            non_empty_lines = [line for line in lines if line.strip()]
            
            if not non_empty_lines:
                raise CSVProcessingError("File appears to be empty")
            
            # Detect delimiter
            delimiter = self.detect_delimiter('\n'.join(non_empty_lines[:10]))
            
            # Detect header
            has_header = self.detect_has_header(non_empty_lines, delimiter)
            
            # Parse with detected parameters
            csv_reader = csv.reader(non_empty_lines, delimiter=delimiter)
            rows = list(csv_reader)
            
            if not rows:
                raise CSVProcessingError("No data rows found in file")
            
            # Determine column names
            if has_header:
                headers = [col.strip() for col in rows[0]]
                data_rows = rows[1:]
            else:
                headers = [f"column_{i+1}" for i in range(len(rows[0]))]
                data_rows = rows
            
            # Get row count estimate
            total_lines = len(lines)
            estimated_rows = max(0, total_lines - (1 if has_header else 0))
            
            # Validate structure
            if len(headers) == 0:
                raise CSVProcessingError("No columns detected in CSV file")
            
            # Create preview data
            preview_rows = data_rows[:self.config.PREVIEW_ROWS]
            preview_data = []
            
            for i, row in enumerate(preview_rows, 1):
                # Pad row if needed
                padded_row = row + [''] * (len(headers) - len(row))
                row_dict = {headers[j]: padded_row[j] if j < len(padded_row) else '' 
                           for j in range(len(headers))}
                row_dict['__row_number__'] = i + (1 if has_header else 0)
                preview_data.append(row_dict)
            
            # Column analysis
            column_analysis = self._analyze_columns(headers, data_rows[:100])  # Analyze first 100 rows
            
            metadata = {
                'encoding': encoding,
                'delimiter': delimiter,
                'has_header': has_header,
                'headers': headers,
                'column_count': len(headers),
                'estimated_rows': estimated_rows,
                'preview_data': preview_data,
                'column_analysis': column_analysis,
                'file_size': len(raw_content)
            }
            
            logger.info(f"CSV metadata parsed: {len(headers)} columns, ~{estimated_rows} rows")
            return metadata
            
        except CSVProcessingError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error parsing CSV metadata: {e}")
            raise CSVProcessingError(f"Failed to parse CSV file: {str(e)}")
    
    def _analyze_columns(self, headers: List[str], data_rows: List[List[str]]) -> Dict[str, Dict[str, Any]]:
        """Analyze column types and content patterns."""
        analysis = {}
        
        for i, header in enumerate(headers):
            column_values = []
            for row in data_rows:
                if i < len(row):
                    value = row[i].strip()
                    if value:  # Only analyze non-empty values
                        column_values.append(value)
            
            if not column_values:
                analysis[header] = {
                    'type': 'unknown',
                    'non_empty_count': 0,
                    'sample_values': []
                }
                continue
            
            # Determine column type
            column_type = self._detect_column_type(column_values)
            
            analysis[header] = {
                'type': column_type,
                'non_empty_count': len(column_values),
                'sample_values': column_values[:5],  # First 5 non-empty values
                'potential_mapping': self._suggest_column_mapping(header, column_values)
            }
        
        return analysis
    
    def _detect_column_type(self, values: List[str]) -> str:
        """Detect the type of data in a column."""
        if not values:
            return 'unknown'
        
        numeric_count = 0
        date_count = 0
        
        for value in values[:20]:  # Check first 20 values
            # Check if numeric (amount)
            if self._is_numeric(value):
                numeric_count += 1
            # Check if date
            elif self._is_date_string(value):
                date_count += 1
        
        total_checked = min(20, len(values))
        
        if numeric_count / total_checked > 0.8:
            return 'numeric'
        elif date_count / total_checked > 0.6:
            return 'date'
        else:
            return 'text'
    
    def _is_date_string(self, value: str) -> bool:
        """Check if string could be a date."""
        # Common date patterns
        date_patterns = [
            r'\d{4}-\d{1,2}-\d{1,2}',  # ISO format
            r'\d{1,2}/\d{1,2}/\d{2,4}',  # US/EU format
            r'\d{1,2}-\d{1,2}-\d{2,4}',  # Dash format
        ]
        
        for pattern in date_patterns:
            if re.match(pattern, value.strip()):
                return True
        
        return False
    
    def _suggest_column_mapping(self, header: str, values: List[str]) -> Optional[str]:
        """Suggest mapping for column based on header name and content."""
        header_lower = header.lower().strip()
        
        # Direct mapping based on header name
        mapping_rules = {
            'invoice_number': ['invoice', 'inv_no', 'invoice_no', 'invoice_number', 'number'],
            'vendor': ['vendor', 'supplier', 'vendor_name', 'supplier_name', 'company'],
            'amount': ['amount', 'total', 'total_amount', 'invoice_amount', 'sum'],
            'invoice_date': ['date', 'invoice_date', 'inv_date', 'bill_date'],
            'po_reference': ['po', 'po_number', 'purchase_order', 'po_ref'],
            'description': ['description', 'desc', 'note', 'memo'],
            'tax_amount': ['tax', 'vat', 'gst', 'tax_amount'],
            'due_date': ['due_date', 'payment_due', 'due'],
        }
        
        for field, keywords in mapping_rules.items():
            if any(keyword in header_lower for keyword in keywords):
                return field
        
        return None
    
    def validate_required_mapping(self, column_mapping: Dict[str, str]) -> List[str]:
        """
        Validate that all required columns are mapped.
        
        Args:
            column_mapping: Dictionary mapping CSV columns to field names
            
        Returns:
            List of validation errors
        """
        errors = []
        mapped_fields = set(column_mapping.values())
        
        for required_field in self.config.REQUIRED_COLUMNS:
            if required_field not in mapped_fields:
                errors.append(f"Required field '{required_field}' is not mapped to any column")
        
        return errors
    
    def normalize_date(self, date_str: str) -> Optional[date]:
        """
        Normalize date string to date object.
        
        Args:
            date_str: Date string in various formats
            
        Returns:
            Normalized date object or None if parsing fails
        """
        if not date_str or not date_str.strip():
            return None
        
        cleaned_date = date_str.strip()
        
        for date_format in self.config.DATE_FORMATS:
            try:
                parsed_date = datetime.strptime(cleaned_date, date_format).date()
                # Validate reasonable date range (1900 to current year + 10)
                current_year = datetime.now().year
                if 1900 <= parsed_date.year <= current_year + 10:
                    return parsed_date
            except ValueError:
                continue
        
        return None
    
    def normalize_currency(self, amount_str: str) -> Optional[Decimal]:
        """
        Normalize currency string to Decimal with 2 decimal places.
        
        Args:
            amount_str: Currency string with various formats
            
        Returns:
            Normalized Decimal amount or None if parsing fails
        """
        if not amount_str or not amount_str.strip():
            return None
        
        # Clean the string
        cleaned = amount_str.strip()
        
        # Remove currency symbols and common formatting
        for symbol in self.config.CURRENCY_SYMBOLS:
            cleaned = cleaned.replace(symbol, '')
        
        # Remove parentheses (sometimes used for negative amounts)
        is_negative = '(' in amount_str and ')' in amount_str
        cleaned = cleaned.replace('(', '').replace(')', '')
        
        # Remove spaces and commas
        cleaned = cleaned.replace(' ', '').replace(',', '')
        
        # Handle negative signs
        if cleaned.startswith('-') or is_negative:
            is_negative = True
            cleaned = cleaned.lstrip('-')
        
        try:
            amount = Decimal(cleaned)
            if is_negative:
                amount = -amount
            
            # Round to 2 decimal places
            return amount.quantize(Decimal('0.01'))
            
        except (InvalidOperation, ValueError):
            return None
    
    def normalize_vendor_name(self, vendor_str: str) -> str:
        """
        Normalize vendor name for consistent matching.
        
        Args:
            vendor_str: Raw vendor name string
            
        Returns:
            Normalized vendor name
        """
        if not vendor_str:
            return ""
        
        # Basic normalization
        normalized = vendor_str.strip().upper()
        
        # Remove extra whitespace
        normalized = ' '.join(normalized.split())
        
        # Remove common business suffixes for matching
        business_suffixes = [
            'LLC', 'INC', 'CORP', 'LTD', 'LIMITED', 'CORPORATION',
            'COMPANY', 'CO', 'ASSOCIATES', 'ASSOC', '&', 'AND'
        ]
        
        words = normalized.split()
        filtered_words = [word for word in words if word not in business_suffixes]
        
        if filtered_words:  # Only use filtered if it's not empty
            normalized = ' '.join(filtered_words)
        
        return normalized[:255]  # Truncate to field limit
    
    def process_csv_stream(self, file_path: str, column_mapping: Dict[str, str],
                          import_batch: ImportBatch) -> Generator[Dict[str, Any], None, None]:
        """
        Stream process CSV file with validation and normalization.
        
        Args:
            file_path: Path to CSV file
            column_mapping: Column mapping configuration
            import_batch: Import batch record for tracking
            
        Yields:
            Dictionaries containing processed row data and validation results
        """
        try:
            # Read file with detected encoding
            encoding = import_batch.csv_encoding or 'utf-8'
            delimiter = import_batch.csv_delimiter or ','
            has_header = import_batch.has_header
            
            with open(file_path, 'r', encoding=encoding, errors='replace') as file:
                reader = csv.DictReader(file, delimiter=delimiter) if has_header else csv.reader(file, delimiter=delimiter)
                
                if not has_header:
                    # Create field names for reader
                    first_row = next(reader)
                    headers = [f"column_{i+1}" for i in range(len(first_row))]
                    reader = csv.DictReader([','.join(first_row)] + [line for line in file], 
                                          fieldnames=headers, delimiter=delimiter)
                
                row_number = 1 if has_header else 0
                
                for row in reader:
                    row_number += 1
                    
                    # Validate and normalize row
                    processed_row = self._process_single_row(row, column_mapping, row_number)
                    
                    yield processed_row
                    
                    # Check for maximum rows limit
                    if row_number > self.config.MAX_ROWS:
                        raise CSVProcessingError(f"File exceeds maximum row limit of {self.config.MAX_ROWS}")
        
        except CSVProcessingError:
            raise
        except Exception as e:
            logger.error(f"Error processing CSV stream: {e}")
            raise CSVProcessingError(f"Failed to process CSV file: {str(e)}")
    
    def _process_single_row(self, row: Dict[str, str], column_mapping: Dict[str, str], 
                           row_number: int) -> Dict[str, Any]:
        """Process and validate a single CSV row."""
        processed_row = {
            'row_number': row_number,
            'raw_data': dict(row),
            'normalized_data': {},
            'errors': [],
            'warnings': []
        }
        
        # Process each mapped field
        for csv_column, field_name in column_mapping.items():
            raw_value = row.get(csv_column, '').strip()
            
            try:
                if field_name == 'invoice_number':
                    normalized_value = raw_value[:100] if raw_value else None
                    if not normalized_value:
                        processed_row['errors'].append({
                            'type': ImportErrorType.VALIDATION,
                            'code': 'MISSING_INVOICE_NUMBER',
                            'message': 'Invoice number is required',
                            'column': csv_column,
                            'raw_value': raw_value
                        })
                    else:
                        processed_row['normalized_data']['invoice_number'] = normalized_value
                
                elif field_name == 'vendor':
                    normalized_value = self.normalize_vendor_name(raw_value)
                    if not normalized_value:
                        processed_row['errors'].append({
                            'type': ImportErrorType.VALIDATION,
                            'code': 'MISSING_VENDOR',
                            'message': 'Vendor name is required',
                            'column': csv_column,
                            'raw_value': raw_value
                        })
                    else:
                        processed_row['normalized_data']['vendor_name'] = normalized_value
                
                elif field_name == 'amount':
                    normalized_value = self.normalize_currency(raw_value)
                    if normalized_value is None:
                        processed_row['errors'].append({
                            'type': ImportErrorType.VALIDATION,
                            'code': 'INVALID_AMOUNT',
                            'message': 'Invalid amount format',
                            'column': csv_column,
                            'raw_value': raw_value,
                            'expected_format': 'Numeric value (e.g., 1234.56)'
                        })
                    elif normalized_value <= 0:
                        processed_row['errors'].append({
                            'type': ImportErrorType.BUSINESS_RULE,
                            'code': 'NEGATIVE_AMOUNT',
                            'message': 'Amount must be positive',
                            'column': csv_column,
                            'raw_value': raw_value
                        })
                    else:
                        processed_row['normalized_data']['total_amount'] = normalized_value
                
                elif field_name == 'invoice_date':
                    normalized_value = self.normalize_date(raw_value)
                    if normalized_value is None:
                        processed_row['errors'].append({
                            'type': ImportErrorType.VALIDATION,
                            'code': 'INVALID_DATE',
                            'message': 'Invalid date format',
                            'column': csv_column,
                            'raw_value': raw_value,
                            'expected_format': 'YYYY-MM-DD or MM/DD/YYYY'
                        })
                    else:
                        # Validate date range
                        current_date = date.today()
                        if normalized_value > current_date:
                            processed_row['warnings'].append({
                                'type': ImportErrorType.BUSINESS_RULE,
                                'code': 'FUTURE_DATE',
                                'message': 'Invoice date is in the future',
                                'column': csv_column,
                                'raw_value': raw_value
                            })
                        processed_row['normalized_data']['invoice_date'] = normalized_value
                
                # Handle optional fields
                elif field_name == 'po_reference' and raw_value:
                    processed_row['normalized_data']['po_reference'] = raw_value[:50]
                
                elif field_name == 'description' and raw_value:
                    processed_row['normalized_data']['description'] = raw_value[:500]
                
                elif field_name == 'tax_amount' and raw_value:
                    normalized_tax = self.normalize_currency(raw_value)
                    if normalized_tax is not None:
                        processed_row['normalized_data']['tax_amount'] = normalized_tax
                
                elif field_name == 'due_date' and raw_value:
                    normalized_due_date = self.normalize_date(raw_value)
                    if normalized_due_date is not None:
                        processed_row['normalized_data']['due_date'] = normalized_due_date
            
            except Exception as e:
                logger.error(f"Error processing field {field_name} at row {row_number}: {e}")
                processed_row['errors'].append({
                    'type': ImportErrorType.SYSTEM,
                    'code': 'PROCESSING_ERROR',
                    'message': f'System error processing field: {str(e)}',
                    'column': csv_column,
                    'raw_value': raw_value
                })
        
        return processed_row