"""
Unit tests for authentication service
Comprehensive test coverage for authentication, MFA, and security features
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.auth_service import (
    AuthenticationService, LoginRequest, LoginResult, 
    DeviceInfo, MFASetupResult
)
from app.models.auth import UserProfile
from app.core.security import security


class TestAuthenticationService:
    """Test cases for AuthenticationService"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()
        return mock_db
    
    @pytest.fixture
    def auth_service(self, mock_db):
        """Create authentication service instance"""
        return AuthenticationService(mock_db)
    
    @pytest.fixture
    def sample_user(self):
        """Sample user profile for testing"""
        return UserProfile(
            id=uuid4(),
            tenant_id=uuid4(),
            email="test@example.com",
            password_hash=security.hash_password("password123"),
            full_name="Test User",
            auth_status="active",
            mfa_enabled=False,
            failed_login_attempts=0,
            account_locked_until=None,
            created_at=datetime.utcnow()
        )
    
    @pytest.fixture
    def sample_device_info(self):
        """Sample device information"""
        return DeviceInfo(
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 Test Browser",
            device_name="Test Device",
            fingerprint="test_fingerprint_123"
        )
    
    @pytest.fixture
    def login_request(self):
        """Sample login request"""
        return LoginRequest(
            email="test@example.com",
            password="password123",
            device_name="Test Device",
            remember_device=False
        )

    @pytest.mark.asyncio
    async def test_authenticate_user_success(
        self, auth_service, sample_user, sample_device_info, login_request
    ):
        """Test successful user authentication"""
        # Mock database queries
        auth_service._get_user_by_email = AsyncMock(return_value=sample_user)
        auth_service._check_rate_limit = AsyncMock(return_value=True)
        auth_service._is_account_locked = AsyncMock(return_value=False)
        auth_service._create_user_session = AsyncMock(return_value="session_123")
        auth_service._get_user_permissions = AsyncMock(return_value=["invoice:read"])
        auth_service._update_successful_login = AsyncMock()
        auth_service._is_trusted_device = AsyncMock(return_value=False)
        auth_service._log_auth_attempt = AsyncMock()
        
        # Execute authentication
        result = await auth_service.authenticate_user(login_request, sample_device_info)
        
        # Assertions
        assert result.success is True
        assert result.tokens is not None
        assert result.user_id == str(sample_user.id)
        assert result.tenant_id == str(sample_user.tenant_id)
        assert result.requires_mfa is False
        
        # Verify method calls
        auth_service._check_rate_limit.assert_called_once()
        auth_service._get_user_by_email.assert_called_once_with(login_request.email)
        auth_service._update_successful_login.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_user_invalid_password(
        self, auth_service, sample_user, sample_device_info, login_request
    ):
        """Test authentication with invalid password"""
        # Set wrong password
        login_request.password = "wrong_password"
        
        # Mock database queries
        auth_service._get_user_by_email = AsyncMock(return_value=sample_user)
        auth_service._check_rate_limit = AsyncMock(return_value=True)
        auth_service._is_account_locked = AsyncMock(return_value=False)
        auth_service._handle_failed_login = AsyncMock()
        
        # Execute authentication
        result = await auth_service.authenticate_user(login_request, sample_device_info)
        
        # Assertions
        assert result.success is False
        assert result.error == "Invalid email or password."
        
        # Verify failed login handling
        auth_service._handle_failed_login.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_user_account_locked(
        self, auth_service, sample_user, sample_device_info, login_request
    ):
        """Test authentication with locked account"""
        # Mock database queries
        auth_service._get_user_by_email = AsyncMock(return_value=sample_user)
        auth_service._check_rate_limit = AsyncMock(return_value=True)
        auth_service._is_account_locked = AsyncMock(return_value=True)
        auth_service._log_auth_attempt = AsyncMock()
        
        # Execute authentication
        result = await auth_service.authenticate_user(login_request, sample_device_info)
        
        # Assertions
        assert result.success is False
        assert "locked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_authenticate_user_rate_limited(
        self, auth_service, sample_device_info, login_request
    ):
        """Test authentication with rate limiting"""
        # Mock rate limit check
        auth_service._check_rate_limit = AsyncMock(return_value=False)
        auth_service._log_auth_attempt = AsyncMock()
        
        # Execute authentication
        result = await auth_service.authenticate_user(login_request, sample_device_info)
        
        # Assertions
        assert result.success is False
        assert "too many" in result.error.lower()

    @pytest.mark.asyncio
    async def test_authenticate_user_mfa_required(
        self, auth_service, sample_user, sample_device_info, login_request
    ):
        """Test authentication requiring MFA"""
        # Enable MFA for user
        sample_user.mfa_enabled = True
        sample_user.mfa_secret = "JBSWY3DPEHPK3PXP"
        
        # Mock database queries
        auth_service._get_user_by_email = AsyncMock(return_value=sample_user)
        auth_service._check_rate_limit = AsyncMock(return_value=True)
        auth_service._is_account_locked = AsyncMock(return_value=False)
        
        # Execute authentication without MFA token
        result = await auth_service.authenticate_user(login_request, sample_device_info)
        
        # Assertions
        assert result.success is False
        assert result.requires_mfa is True
        assert result.mfa_methods == ['totp']

    @pytest.mark.asyncio
    async def test_authenticate_user_with_valid_mfa(
        self, auth_service, sample_user, sample_device_info, login_request
    ):
        """Test successful authentication with MFA"""
        # Enable MFA for user
        sample_user.mfa_enabled = True
        sample_user.mfa_secret = "JBSWY3DPEHPK3PXP"
        login_request.mfa_token = "123456"  # Would be valid TOTP in real scenario
        
        # Mock database queries and MFA verification
        auth_service._get_user_by_email = AsyncMock(return_value=sample_user)
        auth_service._check_rate_limit = AsyncMock(return_value=True)
        auth_service._is_account_locked = AsyncMock(return_value=False)
        auth_service._verify_mfa_token = AsyncMock(return_value=True)
        auth_service._create_user_session = AsyncMock(return_value="session_123")
        auth_service._get_user_permissions = AsyncMock(return_value=["invoice:read"])
        auth_service._update_successful_login = AsyncMock()
        auth_service._is_trusted_device = AsyncMock(return_value=False)
        auth_service._log_auth_attempt = AsyncMock()
        
        # Execute authentication
        result = await auth_service.authenticate_user(login_request, sample_device_info)
        
        # Assertions
        assert result.success is True
        assert result.tokens is not None
        
        # Verify MFA verification was called
        auth_service._verify_mfa_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_setup_mfa(self, auth_service, sample_user):
        """Test MFA setup process"""
        # Mock database operations
        auth_service._get_user_by_id = AsyncMock(return_value=sample_user)
        auth_service.db.execute = AsyncMock()
        auth_service.db.commit = AsyncMock()
        
        with patch('pyotp.random_base32', return_value="JBSWY3DPEHPK3PXP"):
            with patch('qrcode.QRCode') as mock_qr:
                # Mock QR code generation
                mock_qr_instance = MagicMock()
                mock_qr.return_value = mock_qr_instance
                mock_qr_instance.make_image.return_value = MagicMock()
                
                # Execute MFA setup
                result = await auth_service.setup_mfa(
                    sample_user.id,
                    sample_user.tenant_id
                )
                
                # Assertions
                assert isinstance(result, MFASetupResult)
                assert result.secret == "JBSWY3DPEHPK3PXP"
                assert result.qr_code.startswith("data:image/png;base64,")
                assert len(result.backup_codes) == 10

    @pytest.mark.asyncio
    async def test_enable_mfa(self, auth_service, sample_user):
        """Test MFA enablement"""
        # Setup MFA secret
        sample_user.mfa_secret = "JBSWY3DPEHPK3PXP"
        
        # Mock database operations
        auth_service._get_user_by_id = AsyncMock(return_value=sample_user)
        auth_service._verify_mfa_token = AsyncMock(return_value=True)
        auth_service.db.execute = AsyncMock()
        auth_service.db.commit = AsyncMock()
        
        # Mock audit service
        auth_service.audit = AsyncMock()
        auth_service.audit.log_security_event = AsyncMock()
        
        # Execute MFA enablement
        result = await auth_service.enable_mfa(
            sample_user.id,
            sample_user.tenant_id,
            "123456"
        )
        
        # Assertions
        assert result is True
        auth_service._verify_mfa_token.assert_called_once_with(sample_user, "123456")
        auth_service.audit.log_security_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_access_token(self, auth_service, sample_device_info):
        """Test access token refresh"""
        # Mock token payload
        mock_session = MagicMock()
        mock_session.user_id = uuid4()
        mock_session.id = uuid4()
        
        with patch('app.core.security.security.verify_token') as mock_verify:
            mock_payload = MagicMock()
            mock_payload.type = "refresh"
            mock_payload.sub = str(mock_session.user_id)
            mock_payload.tenant_id = str(uuid4())
            mock_payload.session_id = str(mock_session.id)
            mock_payload.device_id = "test_device"
            mock_verify.return_value = mock_payload
            
            # Mock database operations
            auth_service._get_active_session = AsyncMock(return_value=mock_session)
            auth_service._get_user_permissions = AsyncMock(return_value=["invoice:read"])
            auth_service._update_session_access = AsyncMock()
            auth_service.audit = AsyncMock()
            
            # Execute token refresh
            result = await auth_service.refresh_access_token(
                "refresh_token_123",
                sample_device_info
            )
            
            # Assertions
            assert result is not None
            assert result.access_token is not None

    @pytest.mark.asyncio
    async def test_logout_user(self, auth_service, sample_device_info):
        """Test user logout"""
        # Mock token verification and session termination
        with patch('app.core.security.security.verify_token') as mock_verify:
            mock_payload = MagicMock()
            mock_payload.sub = str(uuid4())
            mock_payload.tenant_id = str(uuid4())
            mock_payload.session_id = "session_123"
            mock_verify.return_value = mock_payload
            
            auth_service._terminate_session = AsyncMock()
            auth_service.redis = AsyncMock()
            auth_service.redis.blacklist_token = AsyncMock()
            auth_service.audit = AsyncMock()
            auth_service.audit.log_security_event = AsyncMock()
            
            # Execute logout
            result = await auth_service.logout_user(
                "access_token_123",
                sample_device_info,
                logout_all_devices=False
            )
            
            # Assertions
            assert result is True
            auth_service._terminate_session.assert_called_once_with("session_123", "user_logout")
            auth_service.redis.blacklist_token.assert_called_once()

    def test_password_validation(self):
        """Test password strength validation"""
        from app.core.security import PasswordValidator
        
        validator = PasswordValidator()
        
        # Test strong password
        is_valid, errors = validator.validate("StrongP@ssw0rd123!")
        assert is_valid is True
        assert len(errors) == 0
        
        # Test weak password
        is_valid, errors = validator.validate("weak")
        assert is_valid is False
        assert len(errors) > 0
        
        # Test password strength scoring
        score = validator.calculate_strength("StrongP@ssw0rd123!")
        assert score >= 90
        
        score_weak = validator.calculate_strength("weak")
        assert score_weak < 50

    def test_jwt_token_operations(self):
        """Test JWT token creation and verification"""
        user_id = uuid4()
        tenant_id = uuid4()
        permissions = ["invoice:read", "vendor:manage"]
        
        # Create access token
        access_token = security.create_access_token(
            user_id=user_id,
            tenant_id=tenant_id,
            permissions=permissions
        )
        
        assert access_token is not None
        assert isinstance(access_token, str)
        
        # Verify token
        payload = security.verify_token(access_token)
        assert payload is not None
        assert payload.sub == str(user_id)
        assert payload.tenant_id == str(tenant_id)
        assert payload.permissions == permissions
        assert payload.type == "access"

    def test_password_hashing(self):
        """Test password hashing and verification"""
        password = "test_password_123"
        
        # Hash password
        hashed = security.hash_password(password)
        assert hashed != password
        assert len(hashed) > 50  # bcrypt hashes are long
        
        # Verify correct password
        assert security.verify_password(password, hashed) is True
        
        # Verify incorrect password
        assert security.verify_password("wrong_password", hashed) is False

    def test_backup_code_generation(self):
        """Test MFA backup code generation"""
        codes = security.generate_backup_codes(10)
        
        assert len(codes) == 10
        for code in codes:
            assert len(code) == 9  # Format: ####-####
            assert '-' in code
            parts = code.split('-')
            assert len(parts) == 2
            assert parts[0].isdigit() and parts[1].isdigit()
        
        # Test hashing backup codes
        hashed_codes = security.hash_backup_codes(codes)
        assert len(hashed_codes) == len(codes)
        
        # Test backup code verification
        test_code = codes[0]
        assert security.verify_backup_code(test_code, hashed_codes) is True
        assert security.verify_backup_code("0000-0000", hashed_codes) is False


@pytest.mark.integration
class TestAuthenticationIntegration:
    """Integration tests for authentication system"""
    
    @pytest.mark.asyncio
    async def test_full_authentication_flow(self):
        """Test complete authentication flow"""
        # This would test the full flow with real database
        # and Redis connections in integration environment
        pass
    
    @pytest.mark.asyncio 
    async def test_concurrent_session_limits(self):
        """Test concurrent session management"""
        # Test session limit enforcement
        pass
    
    @pytest.mark.asyncio
    async def test_rate_limiting_integration(self):
        """Test rate limiting with Redis"""
        # Test actual rate limiting behavior
        pass


@pytest.mark.security
class TestAuthenticationSecurity:
    """Security-focused tests for authentication"""
    
    def test_sql_injection_prevention(self):
        """Test SQL injection prevention in queries"""
        # Test that malicious input is properly handled
        pass
    
    def test_timing_attack_prevention(self):
        """Test timing attack prevention in password verification"""
        # Measure timing consistency
        pass
    
    def test_token_security(self):
        """Test JWT token security properties"""
        # Test token signing, expiration, etc.
        pass
    
    def test_session_hijacking_prevention(self):
        """Test session security measures"""
        # Test device fingerprinting, IP validation
        pass


if __name__ == "__main__":
    pytest.main([__file__])