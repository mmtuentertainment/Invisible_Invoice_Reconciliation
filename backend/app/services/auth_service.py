"""
Authentication service handling user login, MFA, session management, and security policies.
Implements comprehensive authentication flow with tenant isolation and audit logging.
"""

import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import pyotp
import qrcode
from io import BytesIO
import base64
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_, func
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.security import security, AuthTokens, TokenPayload
from app.services.redis_service import redis_service
from app.services.audit_service import audit_service
from app.models.auth import (
    UserProfile, Role, UserRole, UserSession, AuthAttempt,
    PasswordResetToken, SecurityAuditLog
)


class LoginRequest(BaseModel):
    """Login request model."""
    email: str
    password: str
    mfa_token: Optional[str] = None
    device_name: Optional[str] = None
    remember_device: bool = False


class LoginResult(BaseModel):
    """Login result model."""
    success: bool
    tokens: Optional[AuthTokens] = None
    requires_mfa: bool = False
    mfa_methods: List[str] = []
    error: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None


class MFASetupResult(BaseModel):
    """MFA setup result model."""
    secret: str
    qr_code: str
    backup_codes: List[str]


class DeviceInfo(BaseModel):
    """Device information for session tracking."""
    ip_address: str
    user_agent: str
    device_name: Optional[str] = None
    fingerprint: Optional[str] = None


class AuthenticationService:
    """Core authentication service with comprehensive security features."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.redis = redis_service
        self.audit = audit_service
    
    async def authenticate_user(
        self,
        login_request: LoginRequest,
        device_info: DeviceInfo
    ) -> LoginResult:
        """
        Authenticate user with comprehensive security checks.
        
        Args:
            login_request: Login credentials and options
            device_info: Device information for tracking
            
        Returns:
            LoginResult with authentication outcome
        """
        # Step 1: Rate limiting check
        if not await self._check_rate_limit(device_info.ip_address, login_request.email):
            await self._log_auth_attempt(
                email=login_request.email,
                ip_address=device_info.ip_address,
                user_agent=device_info.user_agent,
                success=False,
                failure_reason="rate_limited"
            )
            return LoginResult(
                success=False,
                error="Too many login attempts. Please try again later."
            )
        
        # Step 2: Get user profile
        user_profile = await self._get_user_by_email(login_request.email)
        if not user_profile:
            await self._log_auth_attempt(
                email=login_request.email,
                ip_address=device_info.ip_address,
                user_agent=device_info.user_agent,
                success=False,
                failure_reason="user_not_found"
            )
            # Don't reveal that user doesn't exist
            await self._add_delay_for_failed_attempt(device_info.ip_address)
            return LoginResult(
                success=False,
                error="Invalid email or password."
            )
        
        # Step 3: Check account status
        if user_profile.auth_status != 'active':
            await self._log_auth_attempt(
                user_id=user_profile.id,
                email=login_request.email,
                ip_address=device_info.ip_address,
                user_agent=device_info.user_agent,
                success=False,
                failure_reason=f"account_{user_profile.auth_status}"
            )
            return LoginResult(
                success=False,
                error=f"Account is {user_profile.auth_status}. Please contact support."
            )
        
        # Step 4: Check account lockout
        if await self._is_account_locked(user_profile.id):
            await self._log_auth_attempt(
                user_id=user_profile.id,
                email=login_request.email,
                ip_address=device_info.ip_address,
                user_agent=device_info.user_agent,
                success=False,
                failure_reason="account_locked"
            )
            return LoginResult(
                success=False,
                error="Account is temporarily locked due to multiple failed attempts."
            )
        
        # Step 5: Verify password
        if not security.verify_password(login_request.password, user_profile.password_hash):
            await self._handle_failed_login(user_profile, device_info, login_request.email)
            return LoginResult(
                success=False,
                error="Invalid email or password."
            )
        
        # Step 6: Check MFA requirement
        if user_profile.mfa_enabled:
            if not login_request.mfa_token:
                return LoginResult(
                    success=False,
                    requires_mfa=True,
                    mfa_methods=user_profile.mfa_methods or ['totp'],
                    user_id=str(user_profile.id),
                    tenant_id=str(user_profile.tenant_id)
                )
            
            # Verify MFA token
            if not await self._verify_mfa_token(user_profile, login_request.mfa_token):
                await self._handle_failed_login(user_profile, device_info, login_request.email)
                return LoginResult(
                    success=False,
                    error="Invalid MFA code."
                )
        
        # Step 7: Check device trust
        is_trusted_device = await self._is_trusted_device(user_profile.id, device_info.fingerprint)
        
        # Step 8: Create session and tokens
        session_id = await self._create_user_session(
            user_profile,
            device_info,
            is_trusted_device
        )
        
        # Step 9: Get user permissions
        permissions = await self._get_user_permissions(user_profile.id, user_profile.tenant_id)
        
        # Step 10: Generate tokens
        tokens = AuthTokens(
            access_token=security.create_access_token(
                user_id=user_profile.id,
                tenant_id=user_profile.tenant_id,
                permissions=permissions,
                session_id=session_id,
                device_id=device_info.fingerprint
            ),
            refresh_token=security.create_refresh_token(
                user_id=user_profile.id,
                tenant_id=user_profile.tenant_id,
                session_id=session_id,
                device_id=device_info.fingerprint
            ),
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            tenant_id=str(user_profile.tenant_id),
            permissions=permissions
        )
        
        # Step 11: Update user profile
        await self._update_successful_login(user_profile)
        
        # Step 12: Add trusted device if requested
        if login_request.remember_device and not is_trusted_device:
            await self._add_trusted_device(user_profile.id, device_info)
        
        # Step 13: Log successful authentication
        await self._log_auth_attempt(
            user_id=user_profile.id,
            email=login_request.email,
            ip_address=device_info.ip_address,
            user_agent=device_info.user_agent,
            success=True,
            mfa_required=user_profile.mfa_enabled,
            mfa_success=user_profile.mfa_enabled
        )
        
        return LoginResult(
            success=True,
            tokens=tokens,
            user_id=str(user_profile.id),
            tenant_id=str(user_profile.tenant_id)
        )
    
    async def refresh_access_token(
        self,
        refresh_token: str,
        device_info: DeviceInfo
    ) -> Optional[AuthTokens]:
        """
        Refresh access token using refresh token.
        
        Args:
            refresh_token: JWT refresh token
            device_info: Device information
            
        Returns:
            New AuthTokens if refresh is valid
        """
        # Verify refresh token
        payload = security.verify_token(refresh_token)
        if not payload or payload.type != "refresh":
            return None
        
        # Check if session exists and is active
        session = await self._get_active_session(payload.session_id)
        if not session or session.user_id != UUID(payload.sub):
            return None
        
        # Check device consistency
        if payload.device_id and payload.device_id != device_info.fingerprint:
            await self.audit.log_security_event(
                tenant_id=UUID(payload.tenant_id),
                user_id=UUID(payload.sub),
                event_type="suspicious_activity",
                description="Device fingerprint mismatch during token refresh",
                ip_address=device_info.ip_address,
                risk_level="medium"
            )
            return None
        
        # Get fresh permissions
        permissions = await self._get_user_permissions(
            UUID(payload.sub), 
            UUID(payload.tenant_id)
        )
        
        # Generate new access token
        new_access_token = security.create_access_token(
            user_id=payload.sub,
            tenant_id=payload.tenant_id,
            permissions=permissions,
            session_id=payload.session_id,
            device_id=payload.device_id
        )
        
        # Update session last accessed
        await self._update_session_access(session.id)
        
        return AuthTokens(
            access_token=new_access_token,
            refresh_token=refresh_token,  # Keep same refresh token
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            tenant_id=payload.tenant_id,
            permissions=permissions
        )
    
    async def logout_user(
        self,
        access_token: str,
        device_info: DeviceInfo,
        logout_all_devices: bool = False
    ) -> bool:
        """
        Logout user and invalidate session(s).
        
        Args:
            access_token: JWT access token
            device_info: Device information
            logout_all_devices: Whether to logout from all devices
            
        Returns:
            True if logout successful
        """
        payload = security.verify_token(access_token)
        if not payload:
            return False
        
        user_id = UUID(payload.sub)
        tenant_id = UUID(payload.tenant_id)
        
        if logout_all_devices:
            # Terminate all user sessions
            await self._terminate_all_user_sessions(user_id, "user_logout_all")
        else:
            # Terminate specific session
            if payload.session_id:
                await self._terminate_session(payload.session_id, "user_logout")
        
        # Add token to blacklist (Redis)
        await self.redis.blacklist_token(access_token)
        
        # Log logout event
        await self.audit.log_security_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="logout",
            description="User logged out successfully",
            ip_address=device_info.ip_address
        )
        
        return True
    
    async def setup_mfa(
        self,
        user_id: UUID,
        tenant_id: UUID
    ) -> MFASetupResult:
        """
        Setup MFA for user account.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            
        Returns:
            MFASetupResult with secret and QR code
        """
        # Generate TOTP secret
        secret = pyotp.random_base32()
        
        # Get user profile
        user_profile = await self._get_user_by_id(user_id)
        if not user_profile:
            raise ValueError("User not found")
        
        # Generate QR code
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=user_profile.email,
            issuer_name=settings.MFA_ISSUER_NAME
        )
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        qr_img.save(buffer, format='PNG')
        qr_code_data = base64.b64encode(buffer.getvalue()).decode()
        qr_code = f"data:image/png;base64,{qr_code_data}"
        
        # Generate backup codes
        backup_codes = security.generate_backup_codes(settings.MFA_BACKUP_CODES_COUNT)
        hashed_backup_codes = security.hash_backup_codes(backup_codes)
        
        # Update user profile with MFA settings (but don't enable yet)
        await self.db.execute(
            update(UserProfile)
            .where(UserProfile.id == user_id)
            .values(
                mfa_secret=secret,
                mfa_backup_codes=hashed_backup_codes,
                updated_at=datetime.utcnow(),
                updated_by=user_id
            )
        )
        await self.db.commit()
        
        return MFASetupResult(
            secret=secret,
            qr_code=qr_code,
            backup_codes=backup_codes
        )
    
    async def enable_mfa(
        self,
        user_id: UUID,
        tenant_id: UUID,
        verification_code: str
    ) -> bool:
        """
        Enable MFA after verifying setup code.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            verification_code: TOTP verification code
            
        Returns:
            True if MFA enabled successfully
        """
        user_profile = await self._get_user_by_id(user_id)
        if not user_profile or not user_profile.mfa_secret:
            return False
        
        # Verify code
        if not await self._verify_mfa_token(user_profile, verification_code):
            return False
        
        # Enable MFA
        await self.db.execute(
            update(UserProfile)
            .where(UserProfile.id == user_id)
            .values(
                mfa_enabled=True,
                mfa_methods=['totp'],
                mfa_verified_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                updated_by=user_id
            )
        )
        await self.db.commit()
        
        # Log MFA enablement
        await self.audit.log_security_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="mfa_enabled",
            description="Multi-factor authentication enabled",
            risk_level="low"
        )
        
        return True
    
    async def disable_mfa(
        self,
        user_id: UUID,
        tenant_id: UUID,
        password: str,
        verification_code: str
    ) -> bool:
        """
        Disable MFA with password and code verification.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            password: User's current password
            verification_code: TOTP verification code
            
        Returns:
            True if MFA disabled successfully
        """
        user_profile = await self._get_user_by_id(user_id)
        if not user_profile:
            return False
        
        # Verify password
        if not security.verify_password(password, user_profile.password_hash):
            return False
        
        # Verify MFA code
        if not await self._verify_mfa_token(user_profile, verification_code):
            return False
        
        # Disable MFA
        await self.db.execute(
            update(UserProfile)
            .where(UserProfile.id == user_id)
            .values(
                mfa_enabled=False,
                mfa_secret=None,
                mfa_backup_codes=[],
                mfa_methods=[],
                updated_at=datetime.utcnow(),
                updated_by=user_id
            )
        )
        await self.db.commit()
        
        # Log MFA disablement
        await self.audit.log_security_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="mfa_disabled",
            description="Multi-factor authentication disabled",
            risk_level="medium"
        )
        
        return True
    
    # Private helper methods
    
    async def _get_user_by_email(self, email: str) -> Optional[UserProfile]:
        """Get user profile by email."""
        result = await self.db.execute(
            select(UserProfile).where(UserProfile.email == email)
        )
        return result.scalar_one_or_none()
    
    async def _get_user_by_id(self, user_id: UUID) -> Optional[UserProfile]:
        """Get user profile by ID."""
        result = await self.db.execute(
            select(UserProfile).where(UserProfile.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def _check_rate_limit(self, ip_address: str, email: str) -> bool:
        """Check if IP or email is rate limited."""
        return await self.redis.check_rate_limit(
            f"login_ip:{ip_address}", 
            limit=5, 
            window=60
        ) and await self.redis.check_rate_limit(
            f"login_email:{email}",
            limit=10,
            window=300
        )
    
    async def _is_account_locked(self, user_id: UUID) -> bool:
        """Check if account is locked."""
        user_profile = await self._get_user_by_id(user_id)
        if not user_profile:
            return True
        
        return (
            user_profile.account_locked_until and
            user_profile.account_locked_until > datetime.utcnow()
        )
    
    async def _handle_failed_login(
        self,
        user_profile: UserProfile,
        device_info: DeviceInfo,
        email: str
    ):
        """Handle failed login attempt with progressive lockout."""
        # Increment failed attempts
        new_count = user_profile.failed_login_attempts + 1
        
        # Check if account should be locked
        locked_until = None
        if new_count >= settings.MAX_LOGIN_ATTEMPTS:
            lockout_minutes = settings.LOCKOUT_DURATION_MINUTES * (2 ** (new_count - settings.MAX_LOGIN_ATTEMPTS))
            locked_until = datetime.utcnow() + timedelta(minutes=min(lockout_minutes, 1440))  # Max 24 hours
        
        # Update user profile
        await self.db.execute(
            update(UserProfile)
            .where(UserProfile.id == user_profile.id)
            .values(
                failed_login_attempts=new_count,
                account_locked_until=locked_until,
                updated_at=datetime.utcnow()
            )
        )
        await self.db.commit()
        
        # Log failed attempt
        await self._log_auth_attempt(
            user_id=user_profile.id,
            email=email,
            ip_address=device_info.ip_address,
            user_agent=device_info.user_agent,
            success=False,
            failure_reason="invalid_password"
        )
        
        # Add progressive delay
        await self._add_delay_for_failed_attempt(device_info.ip_address)
    
    async def _add_delay_for_failed_attempt(self, ip_address: str):
        """Add progressive delay for failed attempts."""
        if not settings.PROGRESSIVE_DELAY_ENABLED:
            return
        
        # Get recent failed attempts for this IP
        delay_seconds = await self.redis.get_progressive_delay(f"delay:{ip_address}")
        if delay_seconds > 0:
            await asyncio.sleep(min(delay_seconds, 30))  # Max 30 seconds delay
    
    async def _verify_mfa_token(self, user_profile: UserProfile, token: str) -> bool:
        """Verify MFA token (TOTP or backup code)."""
        if not user_profile.mfa_enabled or not user_profile.mfa_secret:
            return False
        
        # Check if it's a backup code format (####-####)
        if '-' in token and len(token) == 9:
            if user_profile.mfa_backup_codes:
                is_valid = security.verify_backup_code(token, user_profile.mfa_backup_codes)
                if is_valid:
                    # Remove used backup code
                    remaining_codes = [
                        code for code in user_profile.mfa_backup_codes
                        if not security.verify_password(token, code)
                    ]
                    await self.db.execute(
                        update(UserProfile)
                        .where(UserProfile.id == user_profile.id)
                        .values(
                            mfa_backup_codes=remaining_codes,
                            updated_at=datetime.utcnow()
                        )
                    )
                    await self.db.commit()
                return is_valid
        
        # Verify TOTP
        totp = pyotp.TOTP(user_profile.mfa_secret)
        return totp.verify(token, valid_window=1)
    
    async def _create_user_session(
        self,
        user_profile: UserProfile,
        device_info: DeviceInfo,
        is_trusted_device: bool
    ) -> str:
        """Create new user session."""
        session_id = str(uuid4())
        session_token = security.generate_secure_token()
        
        # Check concurrent session limit
        await self._enforce_session_limit(user_profile.id)
        
        # Create session record
        session = UserSession(
            id=UUID(session_id),
            tenant_id=user_profile.tenant_id,
            user_id=user_profile.id,
            session_token=session_token,
            ip_address=device_info.ip_address,
            user_agent=device_info.user_agent,
            device_name=device_info.device_name,
            device_fingerprint=device_info.fingerprint,
            expires_at=datetime.utcnow() + timedelta(hours=settings.SESSION_EXPIRE_HOURS),
            is_trusted_device=is_trusted_device,
            requires_mfa=user_profile.mfa_enabled,
            mfa_verified=True  # Already verified during login
        )
        
        self.db.add(session)
        await self.db.commit()
        
        return session_id
    
    async def _enforce_session_limit(self, user_id: UUID):
        """Enforce maximum concurrent sessions."""
        # Get active sessions count
        result = await self.db.execute(
            select(func.count(UserSession.id))
            .where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.status == 'active',
                    UserSession.expires_at > datetime.utcnow()
                )
            )
        )
        active_count = result.scalar()
        
        if active_count >= settings.MAX_CONCURRENT_SESSIONS:
            # Terminate oldest sessions
            oldest_sessions = await self.db.execute(
                select(UserSession)
                .where(
                    and_(
                        UserSession.user_id == user_id,
                        UserSession.status == 'active',
                        UserSession.expires_at > datetime.utcnow()
                    )
                )
                .order_by(UserSession.last_accessed.asc())
                .limit(active_count - settings.MAX_CONCURRENT_SESSIONS + 1)
            )
            
            for session in oldest_sessions.scalars():
                await self._terminate_session(str(session.id), "session_limit_exceeded")
    
    async def _get_user_permissions(self, user_id: UUID, tenant_id: UUID) -> List[str]:
        """Get user permissions from roles."""
        result = await self.db.execute(
            select(Role.permissions)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.is_active == True,
                    Role.is_active == True,
                    or_(
                        UserRole.expires_at == None,
                        UserRole.expires_at > datetime.utcnow()
                    )
                )
            )
        )
        
        permissions = set()
        for role_permissions in result.scalars():
            for resource, actions in role_permissions.items():
                if isinstance(actions, list):
                    for action in actions:
                        permissions.add(f"{resource}:{action}")
                elif actions == "*":
                    permissions.add(f"{resource}:*")
        
        return list(permissions)
    
    async def _update_successful_login(self, user_profile: UserProfile):
        """Update user profile after successful login."""
        await self.db.execute(
            update(UserProfile)
            .where(UserProfile.id == user_profile.id)
            .values(
                last_login=datetime.utcnow(),
                failed_login_attempts=0,
                account_locked_until=None,
                updated_at=datetime.utcnow()
            )
        )
        await self.db.commit()
    
    async def _log_auth_attempt(
        self,
        email: str,
        ip_address: str,
        user_agent: str,
        success: bool,
        user_id: Optional[UUID] = None,
        failure_reason: Optional[str] = None,
        mfa_required: bool = False,
        mfa_success: Optional[bool] = None
    ):
        """Log authentication attempt."""
        attempt = AuthAttempt(
            user_id=user_id,
            email=email,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            failure_reason=failure_reason,
            mfa_required=mfa_required,
            mfa_success=mfa_success,
            attempted_at=datetime.utcnow()
        )
        
        self.db.add(attempt)
        await self.db.commit()
    
    async def _is_trusted_device(self, user_id: UUID, fingerprint: Optional[str]) -> bool:
        """Check if device is in trusted devices list."""
        if not fingerprint:
            return False
        
        user_profile = await self._get_user_by_id(user_id)
        if not user_profile or not user_profile.trusted_devices:
            return False
        
        # Check if fingerprint exists and hasn't expired
        for device in user_profile.trusted_devices:
            if (device.get('fingerprint') == fingerprint and 
                datetime.fromisoformat(device.get('expires_at', '1970-01-01')) > datetime.utcnow()):
                return True
        
        return False
    
    async def _add_trusted_device(self, user_id: UUID, device_info: DeviceInfo):
        """Add device to trusted devices list."""
        if not device_info.fingerprint:
            return
        
        user_profile = await self._get_user_by_id(user_id)
        if not user_profile:
            return
        
        trusted_devices = user_profile.trusted_devices or []
        
        # Remove any existing device with same fingerprint
        trusted_devices = [
            device for device in trusted_devices
            if device.get('fingerprint') != device_info.fingerprint
        ]
        
        # Add new trusted device
        trusted_devices.append({
            'fingerprint': device_info.fingerprint,
            'device_name': device_info.device_name,
            'added_at': datetime.utcnow().isoformat(),
            'expires_at': (datetime.utcnow() + timedelta(days=settings.TRUSTED_DEVICE_EXPIRE_DAYS)).isoformat(),
            'ip_address': device_info.ip_address
        })
        
        # Keep only last 5 trusted devices
        trusted_devices = trusted_devices[-5:]
        
        await self.db.execute(
            update(UserProfile)
            .where(UserProfile.id == user_id)
            .values(
                trusted_devices=trusted_devices,
                updated_at=datetime.utcnow()
            )
        )
        await self.db.commit()
    
    async def _get_active_session(self, session_id: str) -> Optional[UserSession]:
        """Get active user session by ID."""
        result = await self.db.execute(
            select(UserSession)
            .where(
                and_(
                    UserSession.id == UUID(session_id),
                    UserSession.status == 'active',
                    UserSession.expires_at > datetime.utcnow()
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def _update_session_access(self, session_id: UUID):
        """Update session last accessed time."""
        await self.db.execute(
            update(UserSession)
            .where(UserSession.id == session_id)
            .values(last_accessed=datetime.utcnow())
        )
        await self.db.commit()
    
    async def _terminate_session(self, session_id: str, reason: str):
        """Terminate specific session."""
        await self.db.execute(
            update(UserSession)
            .where(UserSession.id == UUID(session_id))
            .values(
                status='revoked',
                terminated_at=datetime.utcnow(),
                termination_reason=reason
            )
        )
        await self.db.commit()
    
    async def _terminate_all_user_sessions(self, user_id: UUID, reason: str):
        """Terminate all sessions for a user."""
        await self.db.execute(
            update(UserSession)
            .where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.status == 'active'
                )
            )
            .values(
                status='revoked',
                terminated_at=datetime.utcnow(),
                termination_reason=reason
            )
        )
        await self.db.commit()