"""
Authentication endpoints for login, logout, MFA, and token management.
Implements comprehensive authentication API with security features.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.middleware import get_current_user, get_current_active_user, get_device_info
from app.services.auth_service import AuthenticationService, LoginRequest as ServiceLoginRequest, DeviceInfo
from app.services.redis_service import redis_service
from app.services.audit_service import get_audit_service
from app.schemas.auth import (
    LoginRequest, LoginResponse, RefreshTokenRequest, RefreshTokenResponse,
    ChangePasswordRequest, ResetPasswordRequest, ResetPasswordConfirmRequest,
    MFASetupRequest, MFASetupResponse, MFAEnableRequest, MFADisableRequest,
    UserProfileResponse, UpdateProfileRequest, SessionResponse, TerminateSessionRequest,
    PasswordStrengthResponse, ErrorResponse
)
from app.models.auth import UserProfile, UserSession


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="User authentication",
    description="Authenticate user with email/password and optional MFA"
)
async def login(
    request: Request,
    login_data: LoginRequest,
    device_info: dict = Depends(get_device_info),
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user with comprehensive security checks.
    
    Features:
    - Rate limiting (5 attempts per minute)
    - Account lockout protection
    - MFA support
    - Device fingerprinting
    - Session management
    - Audit logging
    """
    auth_service = AuthenticationService(db)
    audit_service = await get_audit_service(db)
    
    # Convert to service model
    service_login = ServiceLoginRequest(
        email=login_data.email,
        password=login_data.password,
        mfa_token=login_data.mfa_token,
        device_name=login_data.device_name,
        remember_device=login_data.remember_device
    )
    
    service_device_info = DeviceInfo(
        ip_address=device_info["ip_address"],
        user_agent=device_info["user_agent"],
        device_name=login_data.device_name,
        fingerprint=device_info["device_fingerprint"]
    )
    
    # Perform authentication
    result = await auth_service.authenticate_user(service_login, service_device_info)
    
    if not result.success:
        if result.requires_mfa:
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "requires_mfa": True,
                    "mfa_methods": result.mfa_methods,
                    "user_id": result.user_id,
                    "tenant_id": result.tenant_id
                }
            )
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result.error or "Authentication failed"
        )
    
    # Get user profile for response
    user_profile = await db.get(UserProfile, UUID(result.user_id))
    
    return LoginResponse(
        access_token=result.tokens.access_token,
        refresh_token=result.tokens.refresh_token,
        token_type="bearer",
        expires_in=result.tokens.expires_in,
        user=UserProfileResponse.from_orm(user_profile),
        requires_mfa=False,
        mfa_methods=user_profile.mfa_methods or []
    )


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    summary="Refresh access token",
    description="Refresh access token using refresh token"
)
async def refresh_token(
    request: Request,
    refresh_data: RefreshTokenRequest,
    device_info: dict = Depends(get_device_info),
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token with security validation.
    
    Features:
    - Device consistency checking
    - Session validation
    - Token rotation
    """
    auth_service = AuthenticationService(db)
    
    service_device_info = DeviceInfo(
        ip_address=device_info["ip_address"],
        user_agent=device_info["user_agent"],
        fingerprint=device_info["device_fingerprint"]
    )
    
    tokens = await auth_service.refresh_access_token(
        refresh_data.refresh_token,
        service_device_info
    )
    
    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
    
    return RefreshTokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="User logout",
    description="Logout user and invalidate session"
)
async def logout(
    request: Request,
    logout_data: Optional[TerminateSessionRequest] = None,
    device_info: dict = Depends(get_device_info),
    user_context: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Logout user with session termination options.
    
    Features:
    - Single session logout
    - All devices logout
    - Token blacklisting
    """
    auth_service = AuthenticationService(db)
    
    # Get access token from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header"
        )
    
    access_token = auth_header.split(" ")[1]
    
    service_device_info = DeviceInfo(
        ip_address=device_info["ip_address"],
        user_agent=device_info["user_agent"],
        fingerprint=device_info["device_fingerprint"]
    )
    
    logout_all = logout_data.all_sessions if logout_data else False
    
    success = await auth_service.logout_user(
        access_token,
        service_device_info,
        logout_all_devices=logout_all
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Logout failed"
        )


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get current user profile",
    description="Get current authenticated user profile"
)
async def get_current_user_profile(
    user_context: dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's profile information."""
    user_profile = await db.get(UserProfile, user_context["user_id"])
    
    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found"
        )
    
    return UserProfileResponse.from_orm(user_profile)


@router.put(
    "/me",
    response_model=UserProfileResponse,
    summary="Update current user profile",
    description="Update current user's profile information"
)
async def update_current_user_profile(
    update_data: UpdateProfileRequest,
    user_context: dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update current user's profile information."""
    user_profile = await db.get(UserProfile, user_context["user_id"])
    
    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found"
        )
    
    # Update profile fields
    if update_data.full_name is not None:
        user_profile.full_name = update_data.full_name
    if update_data.display_name is not None:
        user_profile.display_name = update_data.display_name
    if update_data.phone is not None:
        user_profile.phone = update_data.phone
    
    user_profile.updated_at = datetime.utcnow()
    user_profile.updated_by = user_context["user_id"]
    
    await db.commit()
    await db.refresh(user_profile)
    
    return UserProfileResponse.from_orm(user_profile)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change user password",
    description="Change current user's password"
)
async def change_password(
    password_data: ChangePasswordRequest,
    user_context: dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Change user password with validation.
    
    Features:
    - Current password verification
    - Password strength validation
    - Password history checking
    """
    from app.core.security import security
    
    user_profile = await db.get(UserProfile, user_context["user_id"])
    
    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found"
        )
    
    # Verify current password
    if not security.verify_password(password_data.current_password, user_profile.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Validate new password
    is_valid, errors = security.validate_password(password_data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"errors": errors}
        )
    
    # Check password history (simplified - would need proper implementation)
    password_history = user_profile.password_history or []
    for old_hash in password_history:
        if security.verify_password(password_data.new_password, old_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password cannot be one of the last 5 passwords used"
            )
    
    # Update password
    new_hash = security.hash_password(password_data.new_password)
    
    # Update password history
    password_history.append(user_profile.password_hash)
    if len(password_history) > settings.PASSWORD_HISTORY_COUNT:
        password_history = password_history[-settings.PASSWORD_HISTORY_COUNT:]
    
    user_profile.password_hash = new_hash
    user_profile.password_history = password_history
    user_profile.password_changed_at = datetime.utcnow()
    user_profile.updated_at = datetime.utcnow()
    user_profile.updated_by = user_context["user_id"]
    
    await db.commit()
    
    # Log password change
    audit_service = await get_audit_service(db)
    await audit_service.log_security_event(
        event_type="password_changed",
        description="User changed password",
        tenant_id=user_context["tenant_id"],
        user_id=user_context["user_id"],
        risk_level="low"
    )


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Request password reset",
    description="Request password reset via email"
)
async def request_password_reset(
    reset_data: ResetPasswordRequest,
    device_info: dict = Depends(get_device_info),
    db: AsyncSession = Depends(get_db)
):
    """
    Request password reset via email.
    
    Features:
    - Email-based reset tokens
    - Rate limiting
    - Audit logging
    """
    from app.services.email_service import get_email_service
    from app.core.security import security
    from app.models.auth import PasswordResetToken
    from sqlalchemy import select, update
    
    # Rate limiting: 3 requests per 15 minutes per IP
    rate_limit_key = f"password_reset_ip:{device_info['ip_address']}"
    if not await redis_service.check_rate_limit(rate_limit_key, limit=3, window=900):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Please try again later."
        )
    
    # Rate limiting: 5 requests per hour per email
    email_rate_limit_key = f"password_reset_email:{reset_data.email.lower()}"
    if not await redis_service.check_rate_limit(email_rate_limit_key, limit=5, window=3600):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests for this email. Please try again later."
        )
    
    # Check if user exists
    result = await db.execute(
        select(UserProfile).where(UserProfile.email == reset_data.email.lower())
    )
    user_profile = result.scalar_one_or_none()
    
    audit_service = await get_audit_service(db)
    
    if user_profile:
        # Invalidate any existing reset tokens for this user
        await db.execute(
            update(PasswordResetToken)
            .where(
                and_(
                    PasswordResetToken.user_id == user_profile.id,
                    PasswordResetToken.used_at == None,
                    PasswordResetToken.expires_at > datetime.utcnow()
                )
            )
            .values(
                used_at=datetime.utcnow(),
                invalidated_reason="new_request"
            )
        )
        
        # Generate secure reset token
        reset_token = security.generate_secure_token(32)
        token_hash = security.hash_password(reset_token)  # Hash the token for storage
        
        # Create reset token record
        token_record = PasswordResetToken(
            user_id=user_profile.id,
            tenant_id=user_profile.tenant_id,
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
            requested_ip=device_info["ip_address"],
            requested_user_agent=device_info["user_agent"],
            created_at=datetime.utcnow()
        )
        
        db.add(token_record)
        await db.commit()
        
        # Send reset email
        email_service = await get_email_service()
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
        
        await email_service.send_password_reset_email(
            to_email=user_profile.email,
            user_name=user_profile.full_name or user_profile.email,
            reset_url=reset_url,
            expires_minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES
        )
        
        # Log audit event
        await audit_service.log_security_event(
            tenant_id=user_profile.tenant_id,
            user_id=user_profile.id,
            event_type="password_reset_requested",
            description="Password reset requested via email",
            ip_address=device_info["ip_address"],
            user_agent=device_info["user_agent"],
            risk_level="low"
        )
    else:
        # Log audit event for non-existent email (security monitoring)
        await audit_service.log_security_event(
            event_type="password_reset_invalid_email",
            description=f"Password reset requested for non-existent email: {reset_data.email}",
            ip_address=device_info["ip_address"],
            user_agent=device_info["user_agent"],
            risk_level="low"
        )
    
    # Always return success for security (don't reveal if email exists)


@router.post(
    "/reset-password/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Confirm password reset",
    description="Confirm password reset with token"
)
async def confirm_password_reset(
    reset_data: ResetPasswordConfirmRequest,
    device_info: dict = Depends(get_device_info),
    db: AsyncSession = Depends(get_db)
):
    """
    Confirm password reset with token validation.
    
    Features:
    - Token validation
    - Password strength checking
    - Account unlock
    """
    from app.core.security import security
    from app.models.auth import PasswordResetToken
    from sqlalchemy import select, update, and_
    
    # Rate limiting: 5 attempts per 10 minutes per IP
    rate_limit_key = f"password_reset_confirm:{device_info['ip_address']}"
    if not await redis_service.check_rate_limit(rate_limit_key, limit=5, window=600):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset attempts. Please try again later."
        )
    
    # Find valid reset token
    result = await db.execute(
        select(PasswordResetToken, UserProfile)
        .join(UserProfile, PasswordResetToken.user_id == UserProfile.id)
        .where(
            and_(
                PasswordResetToken.used_at == None,
                PasswordResetToken.expires_at > datetime.utcnow(),
                PasswordResetToken.invalidated_reason == None
            )
        )
    )
    
    token_found = None
    user_profile = None
    
    # Check all unused tokens for this token value (constant-time comparison)
    for token_record, user_record in result.all():
        if security.verify_password(reset_data.token, token_record.token_hash):
            token_found = token_record
            user_profile = user_record
            break
    
    if not token_found or not user_profile:
        # Log invalid token attempt
        audit_service = await get_audit_service(db)
        await audit_service.log_security_event(
            event_type="password_reset_invalid_token",
            description="Invalid or expired password reset token used",
            ip_address=device_info["ip_address"],
            user_agent=device_info["user_agent"],
            risk_level="medium"
        )
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Validate new password
    is_valid, errors = security.validate_password(reset_data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Password does not meet requirements", "errors": errors}
        )
    
    # Check password history
    password_history = user_profile.password_history or []
    for old_hash in password_history:
        if security.verify_password(reset_data.new_password, old_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password cannot be one of the last 5 passwords used"
            )
    
    # Also check current password
    if security.verify_password(reset_data.new_password, user_profile.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as current password"
        )
    
    # Update password and clear lockout
    new_password_hash = security.hash_password(reset_data.new_password)
    
    # Update password history
    password_history.append(user_profile.password_hash)
    if len(password_history) > settings.PASSWORD_HISTORY_COUNT:
        password_history = password_history[-settings.PASSWORD_HISTORY_COUNT:]
    
    await db.execute(
        update(UserProfile)
        .where(UserProfile.id == user_profile.id)
        .values(
            password_hash=new_password_hash,
            password_history=password_history,
            password_changed_at=datetime.utcnow(),
            failed_login_attempts=0,
            account_locked_until=None,
            updated_at=datetime.utcnow()
        )
    )
    
    # Mark token as used
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.id == token_found.id)
        .values(
            used_at=datetime.utcnow(),
            used_ip=device_info["ip_address"],
            used_user_agent=device_info["user_agent"]
        )
    )
    
    # Invalidate all user sessions (force re-login)
    auth_service = AuthenticationService(db)
    await auth_service._terminate_all_user_sessions(user_profile.id, "password_reset")
    
    await db.commit()
    
    # Log successful password reset
    audit_service = await get_audit_service(db)
    await audit_service.log_security_event(
        tenant_id=user_profile.tenant_id,
        user_id=user_profile.id,
        event_type="password_reset_completed",
        description="Password successfully reset via email token",
        ip_address=device_info["ip_address"],
        user_agent=device_info["user_agent"],
        risk_level="medium"
    )


@router.post(
    "/mfa/setup",
    response_model=MFASetupResponse,
    summary="Setup MFA",
    description="Setup multi-factor authentication"
)
async def setup_mfa(
    setup_data: MFASetupRequest,
    user_context: dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Setup MFA with TOTP and backup codes.
    
    Features:
    - TOTP secret generation
    - QR code generation
    - Backup codes generation
    """
    auth_service = AuthenticationService(db)
    
    mfa_result = await auth_service.setup_mfa(
        user_context["user_id"],
        user_context["tenant_id"]
    )
    
    return MFASetupResponse(
        secret=mfa_result.secret,
        qr_code=mfa_result.qr_code,
        backup_codes=mfa_result.backup_codes
    )


@router.post(
    "/mfa/enable",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Enable MFA",
    description="Enable MFA after verification"
)
async def enable_mfa(
    enable_data: MFAEnableRequest,
    user_context: dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Enable MFA after code verification.
    
    Features:
    - Code verification
    - MFA activation
    - Audit logging
    """
    auth_service = AuthenticationService(db)
    
    success = await auth_service.enable_mfa(
        user_context["user_id"],
        user_context["tenant_id"],
        enable_data.verification_code
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code"
        )


@router.post(
    "/mfa/disable",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable MFA",
    description="Disable MFA with password and code verification"
)
async def disable_mfa(
    disable_data: MFADisableRequest,
    user_context: dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Disable MFA with comprehensive verification.
    
    Features:
    - Password verification
    - MFA code verification
    - Security audit logging
    """
    auth_service = AuthenticationService(db)
    
    success = await auth_service.disable_mfa(
        user_context["user_id"],
        user_context["tenant_id"],
        disable_data.password,
        disable_data.verification_code
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid password or verification code"
        )


@router.get(
    "/sessions",
    response_model=List[SessionResponse],
    summary="Get user sessions",
    description="Get all active sessions for current user"
)
async def get_user_sessions(
    user_context: dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all active sessions for current user."""
    from sqlalchemy import select, and_
    
    query = select(UserSession).where(
        and_(
            UserSession.user_id == user_context["user_id"],
            UserSession.status == 'active',
            UserSession.expires_at > datetime.utcnow()
        )
    ).order_by(UserSession.last_accessed.desc())
    
    result = await db.execute(query)
    sessions = result.scalars().all()
    
    return [SessionResponse.from_orm(session) for session in sessions]


@router.post(
    "/sessions/terminate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Terminate sessions",
    description="Terminate specific session or all sessions"
)
async def terminate_sessions(
    terminate_data: TerminateSessionRequest,
    user_context: dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Terminate user sessions.
    
    Features:
    - Single session termination
    - All sessions termination
    - Audit logging
    """
    auth_service = AuthenticationService(db)
    
    if terminate_data.all_sessions:
        # Terminate all sessions for user
        await auth_service._terminate_all_user_sessions(
            user_context["user_id"],
            "user_requested"
        )
    elif terminate_data.session_id:
        # Terminate specific session
        await auth_service._terminate_session(
            str(terminate_data.session_id),
            "user_requested"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify session_id or all_sessions=true"
        )


@router.post(
    "/password/strength",
    response_model=PasswordStrengthResponse,
    summary="Check password strength",
    description="Check password strength and policy compliance"
)
async def check_password_strength(
    password: str
):
    """
    Check password strength and policy compliance.
    
    Features:
    - Strength scoring
    - Policy validation
    - Improvement suggestions
    """
    from app.core.security import security
    
    # Calculate strength score
    strength_score = security.get_password_strength(password)
    
    # Validate against policy
    is_valid, errors = security.validate_password(password)
    
    # Generate suggestions (simplified)
    suggestions = []
    if strength_score < 50:
        suggestions.append("Consider using a longer password")
    if strength_score < 75:
        suggestions.append("Add more character variety (uppercase, lowercase, numbers, symbols)")
    
    return PasswordStrengthResponse(
        score=strength_score,
        is_valid=is_valid,
        errors=errors,
        suggestions=suggestions
    )