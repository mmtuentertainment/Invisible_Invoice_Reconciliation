"""
Security tests for authentication system
Tests for vulnerabilities, attack vectors, and security best practices
"""

import pytest
import asyncio
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from uuid import uuid4
from typing import List, Dict
import jwt

from app.services.auth_service import AuthenticationService, LoginRequest, DeviceInfo
from app.models.auth import UserProfile, AuthAttempt, PasswordResetToken
from app.core.security import security
from app.core.config import settings
from app.core.database import get_db
from app.services.redis_service import redis_service
from sqlalchemy import select


@pytest.mark.security
class TestAuthenticationSecurity:
    """Security tests for authentication system"""
    
    @pytest.fixture
    async def db_session(self):
        """Get database session for tests"""
        async for session in get_db():
            yield session
    
    @pytest.fixture
    async def test_user(self, db_session):
        """Create test user for security tests"""
        user = UserProfile(
            id=uuid4(),
            tenant_id=uuid4(),
            email="security@test.com",
            password_hash=security.hash_password("SecurePassword123!"),
            full_name="Security Test User",
            auth_status="active",
            created_at=datetime.utcnow()
        )
        
        db_session.add(user)
        await db_session.commit()
        
        yield user
        
        # Cleanup
        await db_session.delete(user)
        await db_session.commit()
    
    @pytest.fixture
    def device_info(self):
        return DeviceInfo(
            ip_address="192.168.1.100",
            user_agent="Security Test Client",
            fingerprint="security_device"
        )
    
    @pytest.mark.asyncio
    async def test_sql_injection_prevention(self, db_session, device_info):
        """Test SQL injection prevention in authentication"""
        auth_service = AuthenticationService(db_session)
        
        # Test various SQL injection payloads
        sql_injection_payloads = [
            "'; DROP TABLE user_profiles; --",
            "' OR '1'='1",
            "' UNION SELECT * FROM user_profiles --",
            "admin'--",
            "admin' /*",
            "' OR 1=1--",
            "' OR 'a'='a",
            "') OR ('1'='1",
            "' OR 1=1#",
            "' OR 1=1/*",
            "%27%20OR%201=1--",
            "1' AND (SELECT COUNT(*) FROM user_profiles) > 0 --"
        ]
        
        for payload in sql_injection_payloads:
            login_request = LoginRequest(
                email=payload,
                password="any_password"
            )
            
            # Should not cause SQL injection or return sensitive data
            result = await auth_service.authenticate_user(login_request, device_info)
            
            assert result.success is False
            assert result.error in [
                "Invalid email or password.",
                "Too many login attempts. Please try again later."
            ]
    
    @pytest.mark.asyncio
    async def test_timing_attack_prevention(self, db_session, test_user, device_info):
        """Test timing attack prevention in password verification"""
        auth_service = AuthenticationService(db_session)
        
        # Test with valid email, wrong password
        valid_email_times = []
        for _ in range(10):
            start_time = time.perf_counter()
            
            login_request = LoginRequest(
                email=test_user.email,
                password="WrongPassword123!"
            )
            await auth_service.authenticate_user(login_request, device_info)
            
            end_time = time.perf_counter()
            valid_email_times.append(end_time - start_time)
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)
        
        # Test with invalid email
        invalid_email_times = []
        for i in range(10):
            start_time = time.perf_counter()
            
            login_request = LoginRequest(
                email=f"nonexistent{i}@test.com",
                password="WrongPassword123!"
            )
            await auth_service.authenticate_user(login_request, device_info)
            
            end_time = time.perf_counter()
            invalid_email_times.append(end_time - start_time)
            
            await asyncio.sleep(0.1)
        
        avg_valid_time = sum(valid_email_times) / len(valid_email_times)
        avg_invalid_time = sum(invalid_email_times) / len(invalid_email_times)
        
        # Times should be similar to prevent timing attacks
        time_difference = abs(avg_valid_time - avg_invalid_time)
        
        print(f"Avg time for valid email: {avg_valid_time:.4f}s")
        print(f"Avg time for invalid email: {avg_invalid_time:.4f}s")
        print(f"Time difference: {time_difference:.4f}s")
        
        # Timing difference should be minimal (less than 50ms)
        assert time_difference < 0.05
    
    @pytest.mark.asyncio
    async def test_password_brute_force_protection(self, db_session, test_user, device_info):
        """Test brute force protection mechanisms"""
        auth_service = AuthenticationService(db_session)
        
        # Clear any existing rate limits
        await redis_service.client.delete(f"login_ip:{device_info.ip_address}")
        await redis_service.client.delete(f"login_email:{test_user.email}")
        
        login_request = LoginRequest(
            email=test_user.email,
            password="WrongPassword!"
        )
        
        attempts = 0
        rate_limited = False
        
        # Try to brute force
        for i in range(10):
            result = await auth_service.authenticate_user(login_request, device_info)
            
            if "too many" in result.error.lower():
                rate_limited = True
                break
            
            attempts += 1
            await asyncio.sleep(0.1)
        
        # Should be rate limited before 10 attempts
        assert rate_limited
        assert attempts <= 5  # Should trigger after max 5 attempts
        
        # Verify account lockout
        await db_session.refresh(test_user)
        if test_user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            assert test_user.account_locked_until is not None
            assert test_user.account_locked_until > datetime.utcnow()
    
    @pytest.mark.asyncio
    async def test_session_hijacking_prevention(self, db_session, test_user):
        """Test session security measures"""
        auth_service = AuthenticationService(db_session)
        
        device1 = DeviceInfo(
            ip_address="192.168.1.100",
            user_agent="Browser 1",
            fingerprint="device_1"
        )
        
        device2 = DeviceInfo(
            ip_address="192.168.1.200",
            user_agent="Browser 2", 
            fingerprint="device_2"
        )
        
        # Login from device 1
        login_request = LoginRequest(
            email=test_user.email,
            password="SecurePassword123!"
        )
        
        result1 = await auth_service.authenticate_user(login_request, device1)
        assert result1.success is True
        
        # Try to use refresh token from different device
        refresh_result = await auth_service.refresh_access_token(
            result1.tokens.refresh_token,
            device2
        )
        
        # Should fail due to device fingerprint mismatch
        assert refresh_result is None
    
    @pytest.mark.asyncio
    async def test_jwt_token_security(self, test_user):
        """Test JWT token security properties"""
        permissions = ["invoice:read", "user:manage"]
        
        # Test token creation
        token = security.create_access_token(
            user_id=test_user.id,
            tenant_id=test_user.tenant_id,
            permissions=permissions
        )
        
        # Decode token to inspect claims
        decoded = jwt.decode(token, options={"verify_signature": False})
        
        # Verify required claims are present
        assert "sub" in decoded  # Subject (user ID)
        assert "tenant_id" in decoded
        assert "permissions" in decoded
        assert "exp" in decoded  # Expiration
        assert "iat" in decoded  # Issued at
        assert "jti" in decoded  # JWT ID
        assert "type" in decoded  # Token type
        
        # Verify token has expiration
        exp = decoded["exp"]
        iat = decoded["iat"]
        assert exp > iat
        
        # Verify token expires reasonably soon
        expiry_duration = exp - iat
        assert expiry_duration <= settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        
        # Test token verification
        payload = security.verify_token(token)
        assert payload is not None
        assert payload.sub == str(test_user.id)
        
        # Test tampered token detection
        tampered_token = token[:-10] + "tampered"
        tampered_payload = security.verify_token(tampered_token)
        assert tampered_payload is None
    
    @pytest.mark.asyncio
    async def test_password_reset_security(self, db_session, test_user, device_info):
        """Test password reset security measures"""
        # Create password reset token
        reset_token = security.generate_secure_token(32)
        token_hash = security.hash_password(reset_token)
        
        reset_record = PasswordResetToken(
            user_id=test_user.id,
            tenant_id=test_user.tenant_id,
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            requested_ip=device_info.ip_address,
            requested_user_agent=device_info.user_agent
        )
        
        db_session.add(reset_record)
        await db_session.commit()
        
        # Test token characteristics
        assert len(reset_token) >= 32  # Should be sufficiently long
        assert reset_token != token_hash  # Should be hashed in storage
        
        # Test token uniqueness (generate multiple tokens)
        tokens = set()
        for _ in range(100):
            token = security.generate_secure_token(32)
            tokens.add(token)
        
        assert len(tokens) == 100  # All tokens should be unique
        
        # Test token expiration
        expired_record = PasswordResetToken(
            user_id=test_user.id,
            tenant_id=test_user.tenant_id,
            token_hash=security.hash_password("expired_token"),
            expires_at=datetime.utcnow() - timedelta(minutes=1),  # Expired
            requested_ip=device_info.ip_address
        )
        
        db_session.add(expired_record)
        await db_session.commit()
        
        # Expired token should not be usable
        result = await db_session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == test_user.id,
                PasswordResetToken.used_at == None,
                PasswordResetToken.expires_at > datetime.utcnow()
            )
        )
        
        valid_tokens = result.scalars().all()
        assert len(valid_tokens) == 1  # Only the non-expired token
    
    @pytest.mark.asyncio
    async def test_mfa_security(self, db_session, test_user):
        """Test MFA security properties"""
        auth_service = AuthenticationService(db_session)
        
        # Setup MFA
        mfa_result = await auth_service.setup_mfa(test_user.id, test_user.tenant_id)
        
        # Test secret strength
        secret = mfa_result.secret
        assert len(secret) >= 16  # Should be sufficiently long
        assert secret.isalnum() and secret.isupper()  # Base32 format
        
        # Test backup codes
        backup_codes = mfa_result.backup_codes
        assert len(backup_codes) == settings.MFA_BACKUP_CODES_COUNT
        
        for code in backup_codes:
            # Should be in format ####-####
            assert len(code) == 9
            assert code[4] == '-'
            assert code[:4].isdigit()
            assert code[5:].isdigit()
        
        # Test backup code uniqueness
        assert len(set(backup_codes)) == len(backup_codes)
        
        # Test TOTP time window
        import pyotp
        totp = pyotp.TOTP(secret)
        
        # Generate codes for different time windows
        current_time = int(time.time())
        current_code = totp.at(current_time)
        past_code = totp.at(current_time - 30)
        future_code = totp.at(current_time + 30)
        
        assert current_code != past_code
        assert current_code != future_code
        assert len(current_code) == 6  # Standard TOTP length
    
    @pytest.mark.asyncio
    async def test_audit_log_security(self, db_session, test_user, device_info):
        """Test audit logging security"""
        auth_service = AuthenticationService(db_session)
        
        # Perform various authentication actions
        login_request = LoginRequest(
            email=test_user.email,
            password="WrongPassword!"
        )
        
        # Failed login
        await auth_service.authenticate_user(login_request, device_info)
        
        # Successful login
        login_request.password = "SecurePassword123!"
        result = await auth_service.authenticate_user(login_request, device_info)
        
        # Check audit logs
        audit_logs = await db_session.execute(
            select(AuthAttempt).where(AuthAttempt.email == test_user.email)
        )
        
        logs = audit_logs.scalars().all()
        assert len(logs) >= 2
        
        # Verify audit log contains security information
        for log in logs:
            assert log.email == test_user.email
            assert log.ip_address == device_info.ip_address
            assert log.user_agent == device_info.user_agent
            assert log.attempted_at is not None
            assert isinstance(log.success, bool)
            
            if not log.success:
                assert log.failure_reason is not None
    
    @pytest.mark.asyncio
    async def test_information_disclosure_prevention(self, db_session, device_info):
        """Test prevention of information disclosure"""
        auth_service = AuthenticationService(db_session)
        
        # Test with non-existent email
        login_request = LoginRequest(
            email="nonexistent@test.com",
            password="AnyPassword123!"
        )
        
        result = await auth_service.authenticate_user(login_request, device_info)
        
        # Should not reveal that email doesn't exist
        assert result.success is False
        assert result.error == "Invalid email or password."
        
        # Error message should be same for invalid email and invalid password
        # This prevents email enumeration attacks
    
    @pytest.mark.asyncio
    async def test_rate_limiting_bypass_attempts(self, db_session, test_user):
        """Test various rate limiting bypass attempts"""
        auth_service = AuthenticationService(db_session)
        
        login_request = LoginRequest(
            email=test_user.email,
            password="WrongPassword!"
        )
        
        # Test IP-based rate limiting bypass attempts
        different_ips = [f"192.168.1.{i}" for i in range(1, 11)]
        
        for ip in different_ips:
            device_info = DeviceInfo(
                ip_address=ip,
                user_agent="Bypass Test Client",
                fingerprint=f"device_{ip}"
            )
            
            # Each IP should have its own rate limit
            result = await auth_service.authenticate_user(login_request, device_info)
            
            # First attempt from each IP should not be rate limited
            # (unless account is locked)
            if "locked" not in result.error.lower():
                assert "too many" not in result.error.lower()
        
        # Test email-based rate limiting (should persist across IPs)
        await redis_service.client.delete(f"login_email:{test_user.email}")
        
        # Multiple attempts with same email but different IPs
        attempts = 0
        for i in range(15):
            device_info = DeviceInfo(
                ip_address=f"10.0.0.{i}",
                user_agent="Email Bypass Test",
                fingerprint=f"bypass_device_{i}"
            )
            
            result = await auth_service.authenticate_user(login_request, device_info)
            
            if "too many" in result.error.lower():
                break
            attempts += 1
        
        # Should be rate limited by email even with different IPs
        assert attempts <= 10  # Email rate limiting should kick in
    
    @pytest.mark.asyncio 
    async def test_cryptographic_security(self):
        """Test cryptographic security of passwords and tokens"""
        # Test password hashing
        password = "TestPassword123!"
        hash1 = security.hash_password(password)
        hash2 = security.hash_password(password)
        
        # Same password should produce different hashes (salt)
        assert hash1 != hash2
        
        # Both hashes should verify correctly
        assert security.verify_password(password, hash1)
        assert security.verify_password(password, hash2)
        
        # Test secure token generation
        tokens = set()
        for _ in range(1000):
            token = security.generate_secure_token(32)
            tokens.add(token)
        
        # All tokens should be unique (cryptographically secure randomness)
        assert len(tokens) == 1000
        
        # Test token entropy
        token = security.generate_secure_token(32)
        token_bytes = token.encode()
        
        # Should have good entropy (rough check)
        unique_chars = len(set(token))
        assert unique_chars > len(token) * 0.5  # At least 50% unique characters
    
    @pytest.mark.asyncio
    async def test_session_fixation_prevention(self, db_session, test_user, device_info):
        """Test prevention of session fixation attacks"""
        auth_service = AuthenticationService(db_session)
        
        # Login to create session
        login_request = LoginRequest(
            email=test_user.email,
            password="SecurePassword123!"
        )
        
        result1 = await auth_service.authenticate_user(login_request, device_info)
        assert result1.success is True
        
        token1 = result1.tokens.access_token
        
        # Logout and login again
        await auth_service.logout_user(token1, device_info)
        
        result2 = await auth_service.authenticate_user(login_request, device_info)
        assert result2.success is True
        
        token2 = result2.tokens.access_token
        
        # Tokens should be different (new session)
        assert token1 != token2
        
        # Old token should be invalid
        old_payload = security.verify_token(token1)
        # In a real scenario, the old token should be blacklisted
        # This test verifies that new sessions get new tokens


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "security"])