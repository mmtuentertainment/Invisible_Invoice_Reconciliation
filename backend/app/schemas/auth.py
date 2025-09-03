"""
Pydantic schemas for authentication and authorization API endpoints.
Defines request/response models with validation and documentation.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr, validator


class LoginRequest(BaseModel):
    """User login request."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password")
    mfa_token: Optional[str] = Field(None, description="MFA verification code")
    device_name: Optional[str] = Field(None, max_length=100, description="Device name for tracking")
    remember_device: bool = Field(False, description="Mark device as trusted for MFA")


class LoginResponse(BaseModel):
    """User login response."""
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field("bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration time in seconds")
    user: "UserProfileResponse"
    requires_mfa: bool = Field(False, description="Whether MFA is required")
    mfa_methods: List[str] = Field([], description="Available MFA methods")


class RefreshTokenRequest(BaseModel):
    """Token refresh request."""
    refresh_token: str = Field(..., description="JWT refresh token")


class RefreshTokenResponse(BaseModel):
    """Token refresh response."""
    access_token: str = Field(..., description="New JWT access token")
    expires_in: int = Field(..., description="Token expiration time in seconds")


class ChangePasswordRequest(BaseModel):
    """Change password request."""
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=12, description="New password")
    
    @validator("new_password")
    def validate_password(cls, v):
        """Validate password strength."""
        # This is a basic validation, more comprehensive validation
        # would be done in the service layer
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters long")
        
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v)
        
        if not all([has_upper, has_lower, has_digit, has_special]):
            raise ValueError(
                "Password must contain uppercase, lowercase, digit, and special character"
            )
        
        return v


class ResetPasswordRequest(BaseModel):
    """Password reset request."""
    email: EmailStr = Field(..., description="User email address")


class ResetPasswordConfirmRequest(BaseModel):
    """Password reset confirmation request."""
    token: str = Field(..., description="Password reset token")
    new_password: str = Field(..., min_length=12, description="New password")
    
    @validator("new_password")
    def validate_password(cls, v):
        """Validate password strength."""
        return ChangePasswordRequest.validate_password(v)


class MFASetupRequest(BaseModel):
    """MFA setup request."""
    pass  # No additional data needed for setup


class MFASetupResponse(BaseModel):
    """MFA setup response."""
    secret: str = Field(..., description="TOTP secret key")
    qr_code: str = Field(..., description="QR code image data URL")
    backup_codes: List[str] = Field(..., description="One-time backup codes")


class MFAEnableRequest(BaseModel):
    """MFA enable request."""
    verification_code: str = Field(..., min_length=6, max_length=6, description="TOTP verification code")


class MFADisableRequest(BaseModel):
    """MFA disable request."""
    password: str = Field(..., description="Current password")
    verification_code: str = Field(..., min_length=6, max_length=6, description="TOTP verification code")


class UserProfileResponse(BaseModel):
    """User profile response."""
    id: UUID
    tenant_id: UUID
    email: str
    full_name: Optional[str]
    display_name: Optional[str]
    avatar_url: Optional[str]
    phone: Optional[str]
    auth_status: str
    last_login: Optional[datetime]
    mfa_enabled: bool
    mfa_methods: List[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    """Update user profile request."""
    full_name: Optional[str] = Field(None, max_length=255, description="Full name")
    display_name: Optional[str] = Field(None, max_length=100, description="Display name")
    phone: Optional[str] = Field(None, max_length=20, description="Phone number")


class RoleResponse(BaseModel):
    """Role response."""
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    permissions: dict
    level: int
    is_system_role: bool
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class CreateRoleRequest(BaseModel):
    """Create role request."""
    name: str = Field(..., min_length=1, max_length=50, description="Role name")
    display_name: str = Field(..., min_length=1, max_length=100, description="Display name")
    description: Optional[str] = Field(None, description="Role description")
    permissions: dict = Field(..., description="Permissions dictionary")
    parent_role_id: Optional[UUID] = Field(None, description="Parent role for inheritance")
    level: int = Field(0, ge=0, le=10, description="Role level in hierarchy")
    
    @validator("name")
    def validate_name(cls, v):
        """Validate role name format."""
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Role name must contain only letters, numbers, underscores, and hyphens")
        return v.lower()


class UpdateRoleRequest(BaseModel):
    """Update role request."""
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None)
    permissions: Optional[dict] = Field(None)


class AssignRoleRequest(BaseModel):
    """Assign role to user request."""
    user_id: UUID = Field(..., description="User ID")
    role_id: UUID = Field(..., description="Role ID")
    expires_at: Optional[datetime] = Field(None, description="Optional expiration date")


class UserRoleResponse(BaseModel):
    """User role assignment response."""
    id: UUID
    user_id: UUID
    role_id: UUID
    role: RoleResponse
    granted_at: datetime
    granted_by: UUID
    expires_at: Optional[datetime]
    is_active: bool
    
    class Config:
        from_attributes = True


class SessionResponse(BaseModel):
    """User session response."""
    id: UUID
    device_name: Optional[str]
    ip_address: str
    created_at: datetime
    last_accessed: datetime
    expires_at: datetime
    is_trusted_device: bool
    status: str
    
    class Config:
        from_attributes = True


class TerminateSessionRequest(BaseModel):
    """Terminate session request."""
    session_id: Optional[UUID] = Field(None, description="Specific session to terminate")
    all_sessions: bool = Field(False, description="Terminate all sessions")


class SecurityMetricsResponse(BaseModel):
    """Security metrics response."""
    total_events: int
    events_by_type: dict
    events_by_risk_level: dict
    failed_logins_24h: int
    locked_accounts: int
    suspicious_activities: int
    top_risk_ips: List[dict]


class AuditLogResponse(BaseModel):
    """Audit log entry response."""
    id: UUID
    event_type: str
    event_description: str
    ip_address: Optional[str]
    resource_type: Optional[str]
    resource_id: Optional[str]
    risk_level: str
    occurred_at: datetime
    event_data: dict
    metadata: dict
    
    class Config:
        from_attributes = True


class AuditLogQueryRequest(BaseModel):
    """Audit log query request."""
    event_type: Optional[str] = Field(None, description="Filter by event type")
    resource_type: Optional[str] = Field(None, description="Filter by resource type")
    risk_level: Optional[str] = Field(None, description="Filter by risk level")
    hours: int = Field(24, ge=1, le=8760, description="Time window in hours")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results")
    offset: int = Field(0, ge=0, description="Pagination offset")


class PermissionCheckRequest(BaseModel):
    """Permission check request."""
    resource: str = Field(..., description="Resource type")
    action: str = Field(..., description="Action to perform")


class PermissionCheckResponse(BaseModel):
    """Permission check response."""
    allowed: bool
    reason: Optional[str] = None
    required_permissions: List[str]
    user_permissions: List[str]


class PasswordStrengthResponse(BaseModel):
    """Password strength response."""
    score: int = Field(..., ge=0, le=100, description="Password strength score")
    is_valid: bool = Field(..., description="Whether password meets policy")
    errors: List[str] = Field(..., description="List of policy violations")
    suggestions: List[str] = Field(..., description="Suggestions for improvement")


class ErrorResponse(BaseModel):
    """Standard error response."""
    type: str = Field(..., description="Error type URI")
    title: str = Field(..., description="Error title")
    status: int = Field(..., description="HTTP status code")
    detail: str = Field(..., description="Error detail message")
    instance: str = Field(..., description="Request instance URI")
    errors: Optional[List[dict]] = Field(None, description="Validation errors")


# Update forward references
LoginResponse.model_rebuild()
UserRoleResponse.model_rebuild()