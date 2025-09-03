"""
Security utilities for file validation, virus scanning, and threat detection.

This module provides comprehensive security validation for uploaded files including:
- File type validation
- Content-based threat detection
- Size and structure validation
- Malicious pattern detection
- Sanitization and cleanup
"""

import hashlib
import logging
import magic
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)


class SecurityValidationError(Exception):
    """Exception raised for security validation failures."""
    pass


class FileSecurityValidator:
    """Comprehensive file security validation."""
    
    def __init__(self):
        # Allowed MIME types for CSV files
        self.allowed_mime_types = {
            'text/csv',
            'text/plain',
            'application/csv',
            'text/comma-separated-values'
        }
        
        # Allowed file extensions
        self.allowed_extensions = {'.csv', '.txt'}
        
        # Maximum file sizes (in bytes)
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        self.max_line_length = 100000  # 100KB per line
        self.max_lines = 50000  # 50K lines
        
        # Suspicious patterns that might indicate malicious content
        self.malicious_patterns = [
            # Script injection patterns
            rb'<script[^>]*>',
            rb'javascript:',
            rb'vbscript:',
            rb'onload\s*=',
            rb'onclick\s*=',
            rb'onerror\s*=',
            
            # SQL injection patterns
            rb'(union|select|insert|update|delete|drop|create|alter)\s+',
            rb'(exec|execute)\s*\(',
            rb'(script|javascript|vbscript)',
            
            # Command injection patterns
            rb'(\||;|&|\$\(|\`)',
            rb'(cmd\.exe|powershell\.exe|bash|sh)',
            rb'(rm\s+-rf|del\s+/|format\s+)',
            
            # Path traversal patterns
            rb'\.\./',
            rb'\.\.\\',
            rb'/etc/passwd',
            rb'/etc/shadow',
            rb'windows/system32',
            
            # Executable signatures
            rb'^MZ',  # DOS/Windows executable
            rb'^PK',  # ZIP archive (could contain executables)
            rb'^\x7fELF',  # Linux ELF executable
            rb'^\xca\xfe\xba\xbe',  # Mach-O executable (macOS)
        ]
        
        # File size limits for different validation levels
        self.validation_limits = {
            'basic': 1024 * 1024,  # 1MB for basic validation
            'thorough': 10 * 1024 * 1024,  # 10MB for thorough validation
        }
    
    async def validate_file(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Perform comprehensive security validation on uploaded file.
        
        Args:
            file_content: Raw file content as bytes
            filename: Original filename
            
        Returns:
            Dictionary containing validation results
            
        Raises:
            SecurityValidationError: If file fails security validation
        """
        validation_results = {
            'filename': filename,
            'file_size': len(file_content),
            'file_hash': hashlib.sha256(file_content).hexdigest(),
            'mime_type': None,
            'encoding': None,
            'is_safe': False,
            'warnings': [],
            'security_checks': {}
        }
        
        try:
            # 1. Basic file validation
            await self._validate_basic_properties(file_content, filename, validation_results)
            
            # 2. MIME type detection and validation
            await self._validate_mime_type(file_content, validation_results)
            
            # 3. Content-based security scanning
            await self._scan_content_security(file_content, validation_results)
            
            # 4. Structure validation
            await self._validate_file_structure(file_content, validation_results)
            
            # 5. Encoding and character validation
            await self._validate_encoding(file_content, validation_results)
            
            # Mark as safe if all checks passed
            validation_results['is_safe'] = True
            
        except SecurityValidationError as e:
            validation_results['is_safe'] = False
            validation_results['security_error'] = str(e)
            logger.warning(f"Security validation failed for {filename}: {e}")
            raise
        
        except Exception as e:
            validation_results['is_safe'] = False
            validation_results['system_error'] = str(e)
            logger.error(f"Unexpected error during security validation: {e}")
            raise SecurityValidationError(f"Security validation failed: {str(e)}")
        
        return validation_results
    
    async def _validate_basic_properties(self, file_content: bytes, filename: str, 
                                       results: Dict[str, Any]) -> None:
        """Validate basic file properties."""
        # File size validation
        if len(file_content) == 0:
            raise SecurityValidationError("File is empty")
        
        if len(file_content) > self.max_file_size:
            raise SecurityValidationError(
                f"File size {len(file_content)} exceeds maximum allowed size {self.max_file_size}"
            )
        
        # Filename validation
        if not filename or len(filename) > 255:
            raise SecurityValidationError("Invalid filename")
        
        # Extension validation
        file_ext = Path(filename).suffix.lower()
        if file_ext not in self.allowed_extensions:
            raise SecurityValidationError(f"File extension {file_ext} not allowed")
        
        # Filename security patterns
        suspicious_filename_patterns = [
            r'\.{2,}',  # Multiple dots
            r'[<>:"|?*]',  # Illegal filename characters
            r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)',  # Windows reserved names
        ]
        
        for pattern in suspicious_filename_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                raise SecurityValidationError(f"Suspicious filename pattern detected: {filename}")
        
        results['security_checks']['basic_properties'] = 'passed'
    
    async def _validate_mime_type(self, file_content: bytes, results: Dict[str, Any]) -> None:
        """Validate MIME type using content analysis."""
        try:
            # Use python-magic for MIME type detection
            mime_type = magic.from_buffer(file_content, mime=True)
            results['mime_type'] = mime_type
            
            if mime_type not in self.allowed_mime_types:
                # For text files, be a bit more lenient
                if not mime_type.startswith('text/'):
                    raise SecurityValidationError(f"MIME type {mime_type} not allowed")
                else:
                    results['warnings'].append(f"Unusual MIME type {mime_type} detected but allowed")
            
        except Exception as e:
            logger.warning(f"MIME type detection failed: {e}")
            results['warnings'].append("MIME type detection failed, proceeding with caution")
        
        results['security_checks']['mime_type'] = 'passed'
    
    async def _scan_content_security(self, file_content: bytes, results: Dict[str, Any]) -> None:
        """Scan file content for malicious patterns."""
        # Check file size for thorough scanning
        validation_level = 'basic' if len(file_content) > self.validation_limits['thorough'] else 'thorough'
        
        # Sample content for large files
        content_to_scan = file_content
        if validation_level == 'basic':
            # Scan first 1MB and last 1MB
            scan_size = self.validation_limits['basic']
            content_to_scan = file_content[:scan_size] + file_content[-scan_size:]
        
        # Scan for malicious patterns
        detected_threats = []
        for i, pattern in enumerate(self.malicious_patterns):
            if re.search(pattern, content_to_scan, re.IGNORECASE | re.MULTILINE):
                detected_threats.append(f"Malicious pattern {i+1} detected")
        
        if detected_threats:
            raise SecurityValidationError(f"Malicious content detected: {', '.join(detected_threats)}")
        
        # Check for binary content in what should be a text file
        if b'\x00' in content_to_scan[:1024]:  # Check first 1KB for null bytes
            raise SecurityValidationError("Binary content detected in text file")
        
        # Check for unusually high entropy (possible encrypted/compressed content)
        entropy = self._calculate_entropy(content_to_scan[:10000])  # First 10KB
        if entropy > 7.5:  # High entropy threshold
            results['warnings'].append(f"High entropy content detected (entropy: {entropy:.2f})")
        
        results['security_checks']['content_scanning'] = 'passed'
        results['security_checks']['validation_level'] = validation_level
    
    async def _validate_file_structure(self, file_content: bytes, results: Dict[str, Any]) -> None:
        """Validate CSV file structure."""
        try:
            # Decode content for structure analysis
            text_content = self._decode_content(file_content)
            lines = text_content.split('\n')
            
            # Check line count
            if len(lines) > self.max_lines:
                raise SecurityValidationError(f"File has {len(lines)} lines, exceeding limit of {self.max_lines}")
            
            # Check for extremely long lines (possible attack vector)
            for i, line in enumerate(lines[:100]):  # Check first 100 lines
                if len(line) > self.max_line_length:
                    raise SecurityValidationError(f"Line {i+1} exceeds maximum length of {self.max_line_length}")
            
            # Basic CSV structure validation
            if lines:
                first_line = lines[0].strip()
                if first_line:
                    # Count potential CSV delimiters
                    delimiters = [',', '\t', '|', ';']
                    delimiter_counts = {d: first_line.count(d) for d in delimiters}
                    max_delimiters = max(delimiter_counts.values())
                    
                    if max_delimiters == 0:
                        results['warnings'].append("No CSV delimiters detected in first line")
                    elif max_delimiters > 1000:  # Extremely high delimiter count
                        raise SecurityValidationError("Suspicious delimiter count detected")
            
        except UnicodeDecodeError:
            raise SecurityValidationError("File contains invalid character encoding")
        except Exception as e:
            logger.warning(f"Structure validation error: {e}")
            results['warnings'].append(f"Structure validation warning: {str(e)}")
        
        results['security_checks']['structure_validation'] = 'passed'
    
    async def _validate_encoding(self, file_content: bytes, results: Dict[str, Any]) -> None:
        """Validate file encoding and character content."""
        # Try to detect encoding
        import chardet
        encoding_result = chardet.detect(file_content[:10000])  # First 10KB
        detected_encoding = encoding_result.get('encoding', 'unknown')
        confidence = encoding_result.get('confidence', 0)
        
        results['encoding'] = {
            'detected': detected_encoding,
            'confidence': confidence
        }
        
        # Validate encoding is reasonable
        safe_encodings = ['ascii', 'utf-8', 'utf-16', 'iso-8859-1', 'windows-1252']
        if detected_encoding and detected_encoding.lower() not in safe_encodings:
            results['warnings'].append(f"Unusual encoding detected: {detected_encoding}")
        
        if confidence < 0.7:
            results['warnings'].append(f"Low encoding confidence: {confidence:.2f}")
        
        results['security_checks']['encoding_validation'] = 'passed'
    
    def _decode_content(self, file_content: bytes) -> str:
        """Safely decode file content with multiple encoding attempts."""
        encodings_to_try = ['utf-8', 'utf-16', 'ascii', 'iso-8859-1', 'windows-1252']
        
        for encoding in encodings_to_try:
            try:
                return file_content.decode(encoding, errors='strict')
            except UnicodeDecodeError:
                continue
        
        # Last resort with error replacement
        return file_content.decode('utf-8', errors='replace')
    
    def _calculate_entropy(self, data: bytes) -> float:
        """Calculate Shannon entropy of data."""
        if not data:
            return 0
        
        # Count frequency of each byte value
        frequency = {}
        for byte in data:
            frequency[byte] = frequency.get(byte, 0) + 1
        
        # Calculate entropy
        entropy = 0
        data_len = len(data)
        for count in frequency.values():
            probability = count / data_len
            if probability > 0:
                entropy -= probability * (probability.bit_length() - 1)
        
        return entropy
    
    async def quarantine_file(self, file_content: bytes, filename: str, reason: str) -> str:
        """Quarantine a suspicious file for analysis."""
        try:
            quarantine_dir = Path(tempfile.gettempdir()) / "quarantine"
            quarantine_dir.mkdir(exist_ok=True)
            
            # Generate safe filename
            file_hash = hashlib.sha256(file_content).hexdigest()[:16]
            quarantine_filename = f"quarantine_{file_hash}_{Path(filename).stem}.danger"
            quarantine_path = quarantine_dir / quarantine_filename
            
            # Write quarantined file
            with open(quarantine_path, 'wb') as f:
                f.write(file_content)
            
            # Write metadata
            metadata_path = quarantine_path.with_suffix('.meta')
            with open(metadata_path, 'w') as f:
                f.write(f"Original filename: {filename}\n")
                f.write(f"Quarantine reason: {reason}\n")
                f.write(f"File hash: {hashlib.sha256(file_content).hexdigest()}\n")
                f.write(f"File size: {len(file_content)}\n")
                f.write(f"Timestamp: {os.time()}\n")
            
            logger.warning(f"File quarantined: {filename} -> {quarantine_path}")
            return str(quarantine_path)
            
        except Exception as e:
            logger.error(f"Failed to quarantine file: {e}")
            return ""


# Global validator instance
file_security_validator = FileSecurityValidator()


async def check_file_security(file_content: bytes, filename: str) -> Dict[str, Any]:
    """
    Perform comprehensive security check on uploaded file.
    
    Args:
        file_content: Raw file content as bytes
        filename: Original filename
        
    Returns:
        Dictionary containing validation results
        
    Raises:
        SecurityValidationError: If file fails security validation
    """
    return await file_security_validator.validate_file(file_content, filename)


def validate_request_security(request: Any) -> None:
    """Validate request for security concerns."""
    # This is a placeholder for additional request-level security validation
    # Can be extended to check headers, request size, rate limiting, etc.
    pass


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage."""
    # Remove dangerous characters
    sanitized = re.sub(r'[<>:"|?*]', '_', filename)
    
    # Limit length
    if len(sanitized) > 200:
        name, ext = os.path.splitext(sanitized)
        sanitized = name[:200-len(ext)] + ext
    
    return sanitized


def generate_secure_filename(original_filename: str) -> str:
    """Generate a secure filename for storage."""
    # Extract extension
    ext = Path(original_filename).suffix.lower()
    
    # Generate unique identifier
    unique_id = hashlib.md5(f"{original_filename}{os.time()}".encode()).hexdigest()[:16]
    
    return f"upload_{unique_id}{ext}"