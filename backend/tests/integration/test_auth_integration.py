"""
Integration tests for authentication system
Tests full authentication flows with real database and Redis connections
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from uuid import uuid4
import pyotp
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.main import app
from app.core.config import settings
from app.core.database import get_db
from app.models.auth import UserProfile, Role, UserRole, UserSession, AuthAttempt, PasswordResetToken
from app.services.auth_service import AuthenticationService, LoginRequest, DeviceInfo
from app.services.redis_service import redis_service
from app.core.security import security


@pytest.mark.integration
class TestAuthenticationIntegration:
    """Integration tests for authentication system"""
    
    @pytest.fixture
    async def db_session(self):
        """Get database session for tests"""
        async for session in get_db():
            yield session
    
    @pytest.fixture
    async def test_client(self):
        """Get test client"""
        async with AsyncClient(app=app, base_url="http://testserver") as client:
            yield client
    
    @pytest.fixture
    async def test_user(self, db_session: AsyncSession):
        """Create test user for integration tests"""
        # Create tenant first (simplified - would need proper tenant creation)
        tenant_id = uuid4()
        
        user = UserProfile(
            id=uuid4(),
            tenant_id=tenant_id,
            email="test@integration.com",
            password_hash=security.hash_password("TestPassword123!"),
            full_name="Integration Test User",
            auth_status="active",
            mfa_enabled=False,
            created_at=datetime.utcnow()
        )
        
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        
        # Create basic role
        role = Role(
            id=uuid4(),
            tenant_id=tenant_id,
            name="test_user",
            description="Test user role",
            permissions={
                "invoices": ["read", "create"],
                "vendors": ["read"]
            },
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        db_session.add(role)
        
        # Assign role to user
        user_role = UserRole(
            user_id=user.id,
            role_id=role.id,
            tenant_id=tenant_id,
            assigned_by=user.id,
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        db_session.add(user_role)
        await db_session.commit()
        
        yield user
        
        # Cleanup
        await db_session.execute(delete(UserRole).where(UserRole.user_id == user.id))
        await db_session.execute(delete(Role).where(Role.id == role.id))
        await db_session.execute(delete(UserProfile).where(UserProfile.id == user.id))
        await db_session.commit()
    
    @pytest.fixture
    def device_info(self):
        """Sample device information"""
        return DeviceInfo(
            ip_address="127.0.0.1",
            user_agent="Test Client/1.0",
            device_name="Test Device",
            fingerprint="test_device_123"
        )
    
    @pytest.mark.asyncio
    async def test_complete_authentication_flow(self, db_session: AsyncSession, test_user, device_info):
        """Test complete authentication flow from login to logout"""
        auth_service = AuthenticationService(db_session)
        
        # Test successful login
        login_request = LoginRequest(
            email=test_user.email,
            password="TestPassword123!",
            device_name="Test Device"
        )
        
        result = await auth_service.authenticate_user(login_request, device_info)
        
        assert result.success is True
        assert result.tokens is not None
        assert result.user_id == str(test_user.id)
        assert result.tenant_id == str(test_user.tenant_id)
        
        # Verify tokens are valid
        access_token = result.tokens.access_token
        payload = security.verify_token(access_token)
        assert payload is not None
        assert payload.sub == str(test_user.id)
        
        # Test token refresh
        refresh_token = result.tokens.refresh_token
        new_tokens = await auth_service.refresh_access_token(refresh_token, device_info)
        
        assert new_tokens is not None
        assert new_tokens.access_token != access_token  # Should be different
        
        # Test logout
        logout_success = await auth_service.logout_user(
            new_tokens.access_token, 
            device_info
        )
        
        assert logout_success is True
        
        # Verify session is terminated
        result = await db_session.execute(
            select(UserSession).where(UserSession.user_id == test_user.id)
        )
        sessions = result.scalars().all()
        for session in sessions:
            assert session.status == 'revoked'
    
    @pytest.mark.asyncio
    async def test_mfa_authentication_flow(self, db_session: AsyncSession, test_user, device_info):
        """Test complete MFA setup and authentication flow"""
        auth_service = AuthenticationService(db_session)
        
        # Setup MFA
        mfa_result = await auth_service.setup_mfa(test_user.id, test_user.tenant_id)
        
        assert mfa_result.secret is not None
        assert mfa_result.qr_code.startswith("data:image/png;base64,")
        assert len(mfa_result.backup_codes) == settings.MFA_BACKUP_CODES_COUNT
        
        # Generate valid TOTP code
        totp = pyotp.TOTP(mfa_result.secret)
        verification_code = totp.now()
        
        # Enable MFA
        enable_success = await auth_service.enable_mfa(
            test_user.id,
            test_user.tenant_id,
            verification_code
        )
        
        assert enable_success is True
        
        # Test login without MFA token (should require MFA)
        login_request = LoginRequest(
            email=test_user.email,
            password="TestPassword123!"
        )
        
        result = await auth_service.authenticate_user(login_request, device_info)
        
        assert result.success is False
        assert result.requires_mfa is True
        assert "totp" in result.mfa_methods
        
        # Test login with valid MFA token
        new_code = totp.now()
        login_request.mfa_token = new_code
        
        result = await auth_service.authenticate_user(login_request, device_info)
        
        assert result.success is True
        assert result.tokens is not None
        
        # Test login with backup code
        backup_code = mfa_result.backup_codes[0]
        login_request.mfa_token = backup_code
        
        result = await auth_service.authenticate_user(login_request, device_info)
        
        assert result.success is True
        assert result.tokens is not None
        
        # Verify backup code was consumed
        await db_session.refresh(test_user)
        remaining_codes = len(test_user.mfa_backup_codes or [])
        assert remaining_codes == settings.MFA_BACKUP_CODES_COUNT - 1
    
    @pytest.mark.asyncio
    async def test_rate_limiting_integration(self, db_session: AsyncSession, test_user, device_info):
        """Test rate limiting with Redis"""
        auth_service = AuthenticationService(db_session)
        
        # Clear any existing rate limits
        await redis_service.client.delete(f"login_ip:{device_info.ip_address}")
        
        login_request = LoginRequest(
            email=test_user.email,
            password="WrongPassword123!"  # Intentionally wrong
        )
        
        # Make multiple failed login attempts
        failed_attempts = 0
        for i in range(7):  # More than the limit of 5
            result = await auth_service.authenticate_user(login_request, device_info)
            if not result.success and "too many" in result.error.lower():
                break
            failed_attempts += 1
        
        # Should be rate limited before reaching 7 attempts
        assert failed_attempts <= 5
        
        # Verify we're rate limited
        result = await auth_service.authenticate_user(login_request, device_info)
        assert result.success is False
        assert "too many" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_concurrent_session_limits(self, db_session: AsyncSession, test_user, device_info):
        """Test concurrent session management"""
        auth_service = AuthenticationService(db_session)
        
        login_request = LoginRequest(
            email=test_user.email,
            password="TestPassword123!"
        )
        
        sessions = []
        max_sessions = settings.MAX_CONCURRENT_SESSIONS
        
        # Create maximum allowed sessions
        for i in range(max_sessions + 2):  # Create more than allowed
            device_info_copy = DeviceInfo(
                ip_address=device_info.ip_address,
                user_agent=device_info.user_agent,
                device_name=f"Device {i}",
                fingerprint=f"device_{i}"
            )
            
            result = await auth_service.authenticate_user(login_request, device_info_copy)
            if result.success:
                sessions.append(result.tokens)
        
        # Verify only max_sessions are active
        active_sessions = await db_session.execute(
            select(UserSession).where(
                UserSession.user_id == test_user.id,
                UserSession.status == 'active'
            )
        )
        
        assert len(active_sessions.scalars().all()) <= max_sessions
    
    @pytest.mark.asyncio
    async def test_password_reset_flow(self, db_session: AsyncSession, test_user, device_info):
        """Test complete password reset flow"""
        from app.services.email_service import EmailService
        
        # Create password reset token manually (simulating email flow)
        reset_token = security.generate_secure_token(32)
        token_hash = security.hash_password(reset_token)
        
        reset_token_record = PasswordResetToken(
            user_id=test_user.id,
            tenant_id=test_user.tenant_id,
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            requested_ip=device_info.ip_address,
            requested_user_agent=device_info.user_agent
        )
        
        db_session.add(reset_token_record)
        await db_session.commit()
        
        # Test password reset confirmation
        new_password = "NewTestPassword456!"
        
        # This would be done via API endpoint in real scenario
        # Simulate the password reset logic
        result = await db_session.execute(
            select(PasswordResetToken, UserProfile)
            .join(UserProfile, PasswordResetToken.user_id == UserProfile.id)
            .where(
                PasswordResetToken.user_id == test_user.id,
                PasswordResetToken.used_at == None,
                PasswordResetToken.expires_at > datetime.utcnow()
            )
        )
        
        token_record, user_profile = result.first()
        
        # Verify token
        assert security.verify_password(reset_token, token_record.token_hash)
        
        # Update password
        new_hash = security.hash_password(new_password)
        user_profile.password_hash = new_hash
        token_record.used_at = datetime.utcnow()
        
        await db_session.commit()
        
        # Test login with new password
        auth_service = AuthenticationService(db_session)
        login_request = LoginRequest(
            email=test_user.email,
            password=new_password
        )
        
        result = await auth_service.authenticate_user(login_request, device_info)
        assert result.success is True
    
    @pytest.mark.asyncio
    async def test_audit_logging_integration(self, db_session: AsyncSession, test_user, device_info):
        """Test that audit events are properly logged"""
        auth_service = AuthenticationService(db_session)
        
        initial_count = await db_session.execute(
            select(AuthAttempt).where(AuthAttempt.email == test_user.email)
        )
        initial_attempts = len(initial_count.scalars().all())
        
        # Successful login
        login_request = LoginRequest(
            email=test_user.email,
            password="TestPassword123!"
        )
        
        result = await auth_service.authenticate_user(login_request, device_info)
        assert result.success is True
        
        # Failed login
        login_request.password = "WrongPassword"
        result = await auth_service.authenticate_user(login_request, device_info)
        assert result.success is False
        
        # Check audit logs
        final_count = await db_session.execute(
            select(AuthAttempt).where(AuthAttempt.email == test_user.email)
        )
        final_attempts = final_count.scalars().all()
        
        assert len(final_attempts) == initial_attempts + 2
        
        # Verify audit log details
        success_attempt = next((a for a in final_attempts if a.success), None)
        failed_attempt = next((a for a in final_attempts if not a.success), None)
        
        assert success_attempt is not None
        assert success_attempt.ip_address == device_info.ip_address
        assert success_attempt.user_agent == device_info.user_agent
        
        assert failed_attempt is not None
        assert failed_attempt.failure_reason is not None
    
    @pytest.mark.asyncio
    async def test_multi_tenant_isolation(self, db_session: AsyncSession):
        """Test that tenant isolation works properly"""
        # Create users in different tenants
        tenant1_id = uuid4()
        tenant2_id = uuid4()
        
        user1 = UserProfile(
            id=uuid4(),
            tenant_id=tenant1_id,
            email="user1@tenant1.com",
            password_hash=security.hash_password("Password123!"),
            full_name="Tenant 1 User",
            auth_status="active"
        )
        
        user2 = UserProfile(
            id=uuid4(),
            tenant_id=tenant2_id,
            email="user2@tenant2.com",
            password_hash=security.hash_password("Password123!"),
            full_name="Tenant 2 User",
            auth_status="active"
        )
        
        db_session.add_all([user1, user2])
        await db_session.commit()
        
        auth_service = AuthenticationService(db_session)
        device_info = DeviceInfo(
            ip_address="127.0.0.1",
            user_agent="Test Client",
            fingerprint="test_device"
        )
        
        # Authenticate both users
        login1 = LoginRequest(email=user1.email, password="Password123!")
        result1 = await auth_service.authenticate_user(login1, device_info)
        
        login2 = LoginRequest(email=user2.email, password="Password123!")
        result2 = await auth_service.authenticate_user(login2, device_info)
        
        assert result1.success is True
        assert result2.success is True
        
        # Verify tokens contain correct tenant IDs
        token1_payload = security.verify_token(result1.tokens.access_token)
        token2_payload = security.verify_token(result2.tokens.access_token)
        
        assert token1_payload.tenant_id == str(tenant1_id)
        assert token2_payload.tenant_id == str(tenant2_id)
        assert token1_payload.tenant_id != token2_payload.tenant_id
        
        # Cleanup
        await db_session.execute(delete(UserProfile).where(UserProfile.id.in_([user1.id, user2.id])))
        await db_session.commit()
    
    @pytest.mark.asyncio
    async def test_session_security_features(self, db_session: AsyncSession, test_user, device_info):
        """Test session security features like device fingerprinting"""
        auth_service = AuthenticationService(db_session)
        
        login_request = LoginRequest(
            email=test_user.email,
            password="TestPassword123!",
            remember_device=True
        )
        
        # Login with device fingerprinting
        result = await auth_service.authenticate_user(login_request, device_info)
        assert result.success is True
        
        # Verify session has device information
        session_result = await db_session.execute(
            select(UserSession).where(UserSession.user_id == test_user.id)
        )
        session = session_result.scalar_one()
        
        assert session.device_fingerprint == device_info.fingerprint
        assert session.ip_address == device_info.ip_address
        assert session.user_agent == device_info.user_agent
        
        # Test token refresh with different device fingerprint (should fail)
        different_device = DeviceInfo(
            ip_address=device_info.ip_address,
            user_agent=device_info.user_agent,
            fingerprint="different_device"
        )
        
        refresh_result = await auth_service.refresh_access_token(
            result.tokens.refresh_token,
            different_device
        )
        
        # Should fail due to device mismatch
        assert refresh_result is None
    
    @pytest.mark.asyncio
    async def test_performance_under_load(self, db_session: AsyncSession, test_user, device_info):
        """Test authentication performance under concurrent load"""
        auth_service = AuthenticationService(db_session)
        
        login_request = LoginRequest(
            email=test_user.email,
            password="TestPassword123!"
        )
        
        # Simulate concurrent authentication requests
        async def authenticate():
            device_copy = DeviceInfo(
                ip_address=device_info.ip_address,
                user_agent=device_info.user_agent,
                fingerprint=f"device_{uuid4()}"
            )
            return await auth_service.authenticate_user(login_request, device_copy)
        
        # Run 20 concurrent authentication requests
        tasks = [authenticate() for _ in range(20)]
        start_time = datetime.utcnow()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = datetime.utcnow()
        
        # Check that most succeeded (allowing for session limits)
        successful_logins = sum(1 for r in results if isinstance(r, type(results[0])) and r.success)
        assert successful_logins >= min(20, settings.MAX_CONCURRENT_SESSIONS)
        
        # Performance should be reasonable (less than 5 seconds for 20 requests)
        duration = (end_time - start_time).total_seconds()
        assert duration < 5.0


@pytest.mark.integration
class TestAuthenticationAPIIntegration:
    """Integration tests for authentication API endpoints"""
    
    @pytest.mark.asyncio
    async def test_login_endpoint_integration(self, test_client: AsyncClient, db_session: AsyncSession):
        """Test login endpoint with database integration"""
        # Create test user directly in database
        user = UserProfile(
            id=uuid4(),
            tenant_id=uuid4(),
            email="api@test.com",
            password_hash=security.hash_password("ApiTest123!"),
            full_name="API Test User",
            auth_status="active"
        )
        
        db_session.add(user)
        await db_session.commit()
        
        # Test login via API
        response = await test_client.post(
            "/api/v1/auth/login",
            json={
                "email": "api@test.com",
                "password": "ApiTest123!",
                "device_name": "Test Device"
            },
            headers={"User-Agent": "Test Client"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "api@test.com"
        
        # Cleanup
        await db_session.execute(delete(UserProfile).where(UserProfile.id == user.id))
        await db_session.commit()
    
    @pytest.mark.asyncio
    async def test_token_refresh_endpoint_integration(self, test_client: AsyncClient, db_session: AsyncSession):
        """Test token refresh endpoint"""
        # Create test user and get tokens
        user = UserProfile(
            id=uuid4(),
            tenant_id=uuid4(),
            email="refresh@test.com",
            password_hash=security.hash_password("RefreshTest123!"),
            full_name="Refresh Test User",
            auth_status="active"
        )
        
        db_session.add(user)
        await db_session.commit()
        
        # Login to get tokens
        login_response = await test_client.post(
            "/api/v1/auth/login",
            json={
                "email": "refresh@test.com",
                "password": "RefreshTest123!"
            }
        )
        
        login_data = login_response.json()
        refresh_token = login_data["refresh_token"]
        
        # Test token refresh
        refresh_response = await test_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token}
        )
        
        assert refresh_response.status_code == 200
        refresh_data = refresh_response.json()
        
        assert "access_token" in refresh_data
        assert refresh_data["access_token"] != login_data["access_token"]
        
        # Cleanup
        await db_session.execute(delete(UserProfile).where(UserProfile.id == user.id))
        await db_session.commit()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])