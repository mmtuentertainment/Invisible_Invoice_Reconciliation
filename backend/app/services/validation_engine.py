"""
Data validation framework with configurable business rules for invoice import.

This module provides comprehensive validation capabilities including:
- Field-level validation
- Business rule validation  
- Duplicate detection
- Cross-field validation
- Tenant-specific rule configuration
"""

import logging
import re
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.financial import (
    Invoice, Vendor, ImportBatch, ImportError, ImportErrorType, Tenant
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class ValidationError:
    """Represents a validation error with detailed context."""
    
    def __init__(
        self,
        error_type: ImportErrorType,
        code: str,
        message: str,
        field: Optional[str] = None,
        raw_value: Optional[str] = None,
        expected_format: Optional[str] = None,
        suggested_fix: Optional[str] = None,
        severity: str = "error"
    ):
        self.error_type = error_type
        self.code = code
        self.message = message
        self.field = field
        self.raw_value = raw_value
        self.expected_format = expected_format
        self.suggested_fix = suggested_fix
        self.severity = severity  # 'error' or 'warning'
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'error_type': self.error_type.value,
            'code': self.code,
            'message': self.message,
            'field': self.field,
            'raw_value': self.raw_value,
            'expected_format': self.expected_format,
            'suggested_fix': self.suggested_fix,
            'severity': self.severity
        }


class ValidationRule(ABC):
    """Abstract base class for validation rules."""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
    
    @abstractmethod
    def validate(self, data: Dict[str, Any], context: Dict[str, Any]) -> List[ValidationError]:
        """
        Validate data according to this rule.
        
        Args:
            data: Normalized data to validate
            context: Additional context (row_number, tenant_id, etc.)
            
        Returns:
            List of validation errors
        """
        pass


class RequiredFieldRule(ValidationRule):
    """Validates that required fields are present and not empty."""
    
    def __init__(self, required_fields: List[str]):
        super().__init__("required_fields", "Validates required field presence")
        self.required_fields = required_fields
    
    def validate(self, data: Dict[str, Any], context: Dict[str, Any]) -> List[ValidationError]:
        errors = []
        
        for field in self.required_fields:
            value = data.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(ValidationError(
                    error_type=ImportErrorType.VALIDATION,
                    code=f"MISSING_{field.upper()}",
                    message=f"Required field '{field}' is missing or empty",
                    field=field,
                    raw_value=str(value) if value is not None else None
                ))
        
        return errors


class DataTypeRule(ValidationRule):
    """Validates data types for specific fields."""
    
    def __init__(self):
        super().__init__("data_types", "Validates field data types")
        self.type_validators = {
            'invoice_number': self._validate_string,
            'vendor_name': self._validate_string,
            'total_amount': self._validate_decimal,
            'tax_amount': self._validate_decimal,
            'invoice_date': self._validate_date,
            'due_date': self._validate_date,
        }
    
    def validate(self, data: Dict[str, Any], context: Dict[str, Any]) -> List[ValidationError]:
        errors = []
        
        for field, validator in self.type_validators.items():
            if field in data:
                value = data[field]
                error = validator(field, value)
                if error:
                    errors.append(error)
        
        return errors
    
    def _validate_string(self, field: str, value: Any) -> Optional[ValidationError]:
        if not isinstance(value, str):
            return ValidationError(
                error_type=ImportErrorType.VALIDATION,
                code=f"INVALID_{field.upper()}_TYPE",
                message=f"Field '{field}' must be a string",
                field=field,
                raw_value=str(value),
                expected_format="Text string"
            )
        return None
    
    def _validate_decimal(self, field: str, value: Any) -> Optional[ValidationError]:
        if not isinstance(value, Decimal):
            return ValidationError(
                error_type=ImportErrorType.VALIDATION,
                code=f"INVALID_{field.upper()}_TYPE",
                message=f"Field '{field}' must be a decimal number",
                field=field,
                raw_value=str(value),
                expected_format="Decimal number (e.g., 1234.56)"
            )
        return None
    
    def _validate_date(self, field: str, value: Any) -> Optional[ValidationError]:
        if not isinstance(value, date):
            return ValidationError(
                error_type=ImportErrorType.VALIDATION,
                code=f"INVALID_{field.upper()}_TYPE",
                message=f"Field '{field}' must be a date",
                field=field,
                raw_value=str(value),
                expected_format="Date (YYYY-MM-DD)"
            )
        return None


class BusinessRule(ValidationRule):
    """Validates business logic rules."""
    
    def __init__(self, db: Session):
        super().__init__("business_rules", "Validates business logic constraints")
        self.db = db
    
    def validate(self, data: Dict[str, Any], context: Dict[str, Any]) -> List[ValidationError]:
        errors = []
        
        # Amount validations
        if 'total_amount' in data:
            errors.extend(self._validate_amount_rules(data, context))
        
        # Date validations
        if 'invoice_date' in data:
            errors.extend(self._validate_date_rules(data, context))
        
        # Cross-field validations
        errors.extend(self._validate_cross_field_rules(data, context))
        
        return errors
    
    def _validate_amount_rules(self, data: Dict[str, Any], context: Dict[str, Any]) -> List[ValidationError]:
        errors = []
        total_amount = data['total_amount']
        
        # Amount must be positive
        if total_amount <= 0:
            errors.append(ValidationError(
                error_type=ImportErrorType.BUSINESS_RULE,
                code="NEGATIVE_AMOUNT",
                message="Invoice amount must be positive",
                field="total_amount",
                raw_value=str(total_amount),
                suggested_fix="Ensure amount is a positive number"
            ))
        
        # Amount should be reasonable (configurable limits)
        max_amount = Decimal('1000000.00')  # $1M limit
        if total_amount > max_amount:
            errors.append(ValidationError(
                error_type=ImportErrorType.BUSINESS_RULE,
                code="AMOUNT_TOO_LARGE",
                message=f"Invoice amount exceeds maximum limit of ${max_amount:,.2f}",
                field="total_amount",
                raw_value=str(total_amount),
                severity="warning"
            ))
        
        # Validate tax amount relationship
        if 'tax_amount' in data and data['tax_amount'] is not None:
            tax_amount = data['tax_amount']
            if tax_amount < 0:
                errors.append(ValidationError(
                    error_type=ImportErrorType.BUSINESS_RULE,
                    code="NEGATIVE_TAX",
                    message="Tax amount cannot be negative",
                    field="tax_amount",
                    raw_value=str(tax_amount)
                ))
            
            # Tax shouldn't exceed total amount
            if tax_amount > total_amount:
                errors.append(ValidationError(
                    error_type=ImportErrorType.BUSINESS_RULE,
                    code="TAX_EXCEEDS_TOTAL",
                    message="Tax amount cannot exceed total amount",
                    field="tax_amount",
                    raw_value=str(tax_amount),
                    suggested_fix="Verify tax and total amounts are correct"
                ))
            
            # Tax rate reasonableness check (assume max 50% tax rate)
            tax_rate = tax_amount / total_amount
            if tax_rate > Decimal('0.5'):
                errors.append(ValidationError(
                    error_type=ImportErrorType.BUSINESS_RULE,
                    code="HIGH_TAX_RATE",
                    message=f"Tax rate appears high ({tax_rate:.1%})",
                    field="tax_amount",
                    raw_value=str(tax_amount),
                    severity="warning"
                ))
        
        return errors
    
    def _validate_date_rules(self, data: Dict[str, Any], context: Dict[str, Any]) -> List[ValidationError]:
        errors = []
        invoice_date = data['invoice_date']
        today = date.today()
        
        # Date shouldn't be too far in the past
        max_past_days = 1095  # 3 years
        if invoice_date < today - timedelta(days=max_past_days):
            errors.append(ValidationError(
                error_type=ImportErrorType.BUSINESS_RULE,
                code="DATE_TOO_OLD",
                message=f"Invoice date is more than {max_past_days} days old",
                field="invoice_date",
                raw_value=str(invoice_date),
                severity="warning"
            ))
        
        # Date shouldn't be in the future
        if invoice_date > today:
            errors.append(ValidationError(
                error_type=ImportErrorType.BUSINESS_RULE,
                code="FUTURE_DATE",
                message="Invoice date cannot be in the future",
                field="invoice_date",
                raw_value=str(invoice_date),
                severity="warning"
            ))
        
        # Validate due date relationship
        if 'due_date' in data and data['due_date'] is not None:
            due_date = data['due_date']
            
            if due_date < invoice_date:
                errors.append(ValidationError(
                    error_type=ImportErrorType.BUSINESS_RULE,
                    code="DUE_BEFORE_INVOICE",
                    message="Due date cannot be before invoice date",
                    field="due_date",
                    raw_value=str(due_date),
                    suggested_fix="Ensure due date is after invoice date"
                ))
            
            # Check payment terms reasonableness
            payment_days = (due_date - invoice_date).days
            if payment_days > 365:
                errors.append(ValidationError(
                    error_type=ImportErrorType.BUSINESS_RULE,
                    code="LONG_PAYMENT_TERMS",
                    message=f"Payment terms are unusually long ({payment_days} days)",
                    field="due_date",
                    raw_value=str(due_date),
                    severity="warning"
                ))
        
        return errors
    
    def _validate_cross_field_rules(self, data: Dict[str, Any], context: Dict[str, Any]) -> List[ValidationError]:
        errors = []
        
        # Validate subtotal + tax = total relationship
        if all(field in data for field in ['total_amount', 'tax_amount']) and data['tax_amount'] is not None:
            total_amount = data['total_amount']
            tax_amount = data['tax_amount']
            
            # If we have subtotal, validate the calculation
            if 'subtotal' in data and data['subtotal'] is not None:
                subtotal = data['subtotal']
                expected_total = subtotal + tax_amount
                
                # Allow small rounding differences
                if abs(total_amount - expected_total) > Decimal('0.02'):
                    errors.append(ValidationError(
                        error_type=ImportErrorType.BUSINESS_RULE,
                        code="AMOUNT_CALCULATION_ERROR",
                        message=f"Total amount ({total_amount}) doesn't match subtotal + tax ({expected_total})",
                        field="total_amount",
                        raw_value=str(total_amount),
                        suggested_fix="Verify subtotal, tax, and total amounts are correct"
                    ))
        
        return errors


class DuplicateDetectionRule(ValidationRule):
    """Detects duplicate invoices within batch and against existing data."""
    
    def __init__(self, db: Session, tenant_id: UUID, import_batch_id: UUID):
        super().__init__("duplicate_detection", "Detects duplicate invoices")
        self.db = db
        self.tenant_id = tenant_id
        self.import_batch_id = import_batch_id
        self.batch_invoices: Set[Tuple[str, str]] = set()  # (vendor_name, invoice_number)
    
    def validate(self, data: Dict[str, Any], context: Dict[str, Any]) -> List[ValidationError]:
        errors = []
        
        if not all(field in data for field in ['vendor_name', 'invoice_number']):
            return errors  # Skip if required fields missing
        
        vendor_name = data['vendor_name']
        invoice_number = data['invoice_number']
        invoice_key = (vendor_name, invoice_number)
        
        # Check for duplicates within current batch
        if invoice_key in self.batch_invoices:
            errors.append(ValidationError(
                error_type=ImportErrorType.DUPLICATE,
                code="DUPLICATE_IN_BATCH",
                message=f"Duplicate invoice found in batch: {vendor_name} - {invoice_number}",
                field="invoice_number",
                raw_value=invoice_number,
                suggested_fix="Remove duplicate entry or verify invoice details"
            ))
        else:
            self.batch_invoices.add(invoice_key)
        
        # Check for duplicates against existing data
        try:
            # First try to find vendor by normalized name
            existing_vendor = self.db.query(Vendor).filter(
                and_(
                    Vendor.tenant_id == self.tenant_id,
                    func.upper(Vendor.name) == vendor_name.upper()
                )
            ).first()
            
            if existing_vendor:
                # Check for existing invoice
                existing_invoice = self.db.query(Invoice).filter(
                    and_(
                        Invoice.tenant_id == self.tenant_id,
                        Invoice.vendor_id == existing_vendor.id,
                        Invoice.invoice_number == invoice_number
                    )
                ).first()
                
                if existing_invoice:
                    errors.append(ValidationError(
                        error_type=ImportErrorType.DUPLICATE,
                        code="DUPLICATE_IN_SYSTEM",
                        message=f"Invoice already exists in system: {vendor_name} - {invoice_number}",
                        field="invoice_number",
                        raw_value=invoice_number,
                        suggested_fix="Verify this is a new invoice or update existing record"
                    ))
        
        except Exception as e:
            logger.error(f"Error checking for duplicate invoice: {e}")
            # Don't fail validation due to database error
        
        return errors


class VendorValidationRule(ValidationRule):
    """Validates vendor information and suggests matches."""
    
    def __init__(self, db: Session, tenant_id: UUID):
        super().__init__("vendor_validation", "Validates vendor information")
        self.db = db
        self.tenant_id = tenant_id
        self._vendor_cache: Dict[str, Vendor] = {}
    
    def validate(self, data: Dict[str, Any], context: Dict[str, Any]) -> List[ValidationError]:
        errors = []
        
        if 'vendor_name' not in data:
            return errors
        
        vendor_name = data['vendor_name']
        
        # Validate vendor name format
        if not self._is_valid_vendor_name(vendor_name):
            errors.append(ValidationError(
                error_type=ImportErrorType.VALIDATION,
                code="INVALID_VENDOR_FORMAT",
                message="Vendor name contains invalid characters or format",
                field="vendor_name",
                raw_value=vendor_name,
                expected_format="Alphanumeric characters, spaces, and common punctuation"
            ))
        
        # Check if vendor exists or suggest matches
        vendor_match = self._find_vendor_match(vendor_name)
        if not vendor_match:
            # This is a warning, not an error - new vendors are allowed
            errors.append(ValidationError(
                error_type=ImportErrorType.VALIDATION,
                code="NEW_VENDOR",
                message=f"Vendor '{vendor_name}' not found in system - will be created",
                field="vendor_name",
                raw_value=vendor_name,
                severity="warning"
            ))
        else:
            # Store matched vendor for later use
            data['_matched_vendor_id'] = vendor_match.id
        
        return errors
    
    def _is_valid_vendor_name(self, vendor_name: str) -> bool:
        """Validate vendor name format."""
        if not vendor_name or len(vendor_name) < 2:
            return False
        
        # Check for suspicious patterns
        suspicious_patterns = [
            r'^[0-9]+$',  # Only numbers
            r'^[^a-zA-Z]*$',  # No letters
            r'^\s*$',  # Only whitespace
        ]
        
        for pattern in suspicious_patterns:
            if re.match(pattern, vendor_name):
                return False
        
        return True
    
    def _find_vendor_match(self, vendor_name: str) -> Optional[Vendor]:
        """Find matching vendor in database."""
        normalized_name = vendor_name.upper().strip()
        
        # Check cache first
        if normalized_name in self._vendor_cache:
            return self._vendor_cache[normalized_name]
        
        try:
            # Exact match first
            vendor = self.db.query(Vendor).filter(
                and_(
                    Vendor.tenant_id == self.tenant_id,
                    func.upper(Vendor.name) == normalized_name
                )
            ).first()
            
            if vendor:
                self._vendor_cache[normalized_name] = vendor
                return vendor
            
            # TODO: Implement fuzzy matching for similar vendor names
            # This would involve similarity scoring using techniques like:
            # - Levenshtein distance
            # - Jaro-Winkler distance  
            # - Phonetic matching (Soundex, Metaphone)
            
        except Exception as e:
            logger.error(f"Error finding vendor match: {e}")
        
        return None


class ValidationEngine:
    """Main validation engine that orchestrates all validation rules."""
    
    def __init__(self, db: Session, tenant_id: UUID, import_batch_id: UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.import_batch_id = import_batch_id
        
        # Initialize validation rules
        self.rules: List[ValidationRule] = [
            RequiredFieldRule(['invoice_number', 'vendor_name', 'total_amount', 'invoice_date']),
            DataTypeRule(),
            BusinessRule(db),
            VendorValidationRule(db, tenant_id),
            DuplicateDetectionRule(db, tenant_id, import_batch_id)
        ]
        
        # Validation statistics
        self.stats = {
            'total_rows': 0,
            'valid_rows': 0,
            'rows_with_errors': 0,
            'rows_with_warnings': 0,
            'total_errors': 0,
            'total_warnings': 0,
            'error_breakdown': {},
            'warning_breakdown': {}
        }
    
    def validate_row(self, data: Dict[str, Any], row_number: int) -> Tuple[Dict[str, Any], List[ValidationError]]:
        """
        Validate a single row of data against all rules.
        
        Args:
            data: Normalized row data
            row_number: Row number for context
            
        Returns:
            Tuple of (enhanced_data, validation_errors)
        """
        context = {
            'row_number': row_number,
            'tenant_id': self.tenant_id,
            'import_batch_id': self.import_batch_id
        }
        
        all_errors = []
        enhanced_data = data.copy()
        
        # Run all validation rules
        for rule in self.rules:
            try:
                rule_errors = rule.validate(enhanced_data, context)
                all_errors.extend(rule_errors)
            except Exception as e:
                logger.error(f"Error running validation rule {rule.name}: {e}")
                all_errors.append(ValidationError(
                    error_type=ImportErrorType.SYSTEM,
                    code="VALIDATION_SYSTEM_ERROR",
                    message=f"System error during validation: {str(e)}",
                    severity="error"
                ))
        
        # Update statistics
        self._update_stats(all_errors)
        
        return enhanced_data, all_errors
    
    def _update_stats(self, errors: List[ValidationError]) -> None:
        """Update validation statistics."""
        self.stats['total_rows'] += 1
        
        error_count = sum(1 for e in errors if e.severity == 'error')
        warning_count = sum(1 for e in errors if e.severity == 'warning')
        
        if error_count > 0:
            self.stats['rows_with_errors'] += 1
        elif warning_count > 0:
            self.stats['rows_with_warnings'] += 1
        else:
            self.stats['valid_rows'] += 1
        
        self.stats['total_errors'] += error_count
        self.stats['total_warnings'] += warning_count
        
        # Track error breakdown
        for error in errors:
            category = error.severity + 's'
            breakdown = self.stats[f'{error.severity}_breakdown']
            breakdown[error.code] = breakdown.get(error.code, 0) + 1
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get comprehensive validation summary."""
        return {
            'statistics': self.stats.copy(),
            'validation_rate': (self.stats['valid_rows'] / max(1, self.stats['total_rows'])) * 100,
            'error_rate': (self.stats['rows_with_errors'] / max(1, self.stats['total_rows'])) * 100,
            'warning_rate': (self.stats['rows_with_warnings'] / max(1, self.stats['total_rows'])) * 100,
        }
    
    def reset_stats(self) -> None:
        """Reset validation statistics for new batch."""
        self.stats = {
            'total_rows': 0,
            'valid_rows': 0,
            'rows_with_errors': 0,
            'rows_with_warnings': 0,
            'total_errors': 0,
            'total_warnings': 0,
            'error_breakdown': {},
            'warning_breakdown': {}
        }