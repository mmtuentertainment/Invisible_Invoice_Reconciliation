"""
SQLAlchemy models for authentication and authorization system.
Defines database schema for users, roles, sessions, and audit logging.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, JSON, String, Text, 
    ForeignKey, Index, CheckConstraint, UniqueConstraint, ARRAY, Enum
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, INET
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


class UserProfile(Base):
    """User authentication profiles extending Supabase auth.users."""
    
    __tablename__ = "user_profiles"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    
    # Profile information
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    display_name: Mapped[Optional[str]] = mapped_column(String(100))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    
    # Authentication settings
    auth_status: Mapped[str] = mapped_column(
        String(20), 
        server_default="active",
        nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    account_locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Password history tracking
    password_history: Mapped[Optional[List[str]]] = mapped_column(JSON, server_default="[]")
    
    # MFA settings
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    mfa_secret: Mapped[Optional[str]] = mapped_column(String(255))
    mfa_backup_codes: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    mfa_methods: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    mfa_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Device trust
    trusted_devices: Mapped[Optional[List[dict]]] = mapped_column(JSON, server_default="[]")
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now()
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    updated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    user_roles: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="user")
    sessions: Mapped[List["UserSession"]] = relationship("UserSession", back_populates="user")
    auth_attempts: Mapped[List["AuthAttempt"]] = relationship("AuthAttempt", back_populates="user")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        CheckConstraint("char_length(full_name) <= 255"),
        CheckConstraint("char_length(display_name) <= 100"),
        CheckConstraint("failed_login_attempts >= 0"),
        CheckConstraint("auth_status IN ('active', 'locked', 'suspended', 'inactive')"),
        Index("idx_user_profiles_tenant_id", "tenant_id"),
        Index("idx_user_profiles_auth_status", "auth_status"),
        Index("idx_user_profiles_email", "tenant_id", "email"),
        Index("idx_user_profiles_last_login", "last_login"),
        Index("idx_user_profiles_mfa_enabled", "mfa_enabled"),
    )


class Role(Base):
    """Roles for role-based access control with hierarchical permissions."""
    
    __tablename__ = "roles"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    
    # Role definition
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    # Permissions (JSONB for flexibility)
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    
    # Hierarchy
    parent_role_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("roles.id")
    )
    level: Mapped[int] = mapped_column(Integer, server_default="0")
    
    # System roles vs custom roles
    is_system_role: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now()
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    updated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    user_roles: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="role")
    parent_role: Mapped[Optional["Role"]] = relationship("Role", remote_side=[id])
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint("char_length(name) <= 50"),
        CheckConstraint("char_length(display_name) <= 100"),
        CheckConstraint("level >= 0 AND level <= 10"),
        Index("idx_roles_tenant_id", "tenant_id"),
        Index("idx_roles_name", "tenant_id", "name"),
        Index("idx_roles_parent", "parent_role_id"),
        Index("idx_roles_system", "is_system_role"),
        Index("idx_roles_active", "is_active"),
    )


class UserRole(Base):
    """User role assignments with expiration support."""
    
    __tablename__ = "user_roles"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("user_profiles.id", ondelete="CASCADE")
    )
    role_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("roles.id", ondelete="CASCADE")
    )
    
    # Assignment details
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    granted_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    
    # Relationships
    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="user_roles")
    role: Mapped["Role"] = relationship("Role", back_populates="user_roles")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "role_id"),
        CheckConstraint("expires_at IS NULL OR expires_at > granted_at"),
        Index("idx_user_roles_tenant_user", "tenant_id", "user_id"),
        Index("idx_user_roles_role", "role_id"),
        Index("idx_user_roles_active", "is_active"),
        Index("idx_user_roles_expires", "expires_at"),
    )


class UserSession(Base):
    """User sessions management with device tracking and security controls."""
    
    __tablename__ = "user_sessions"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("user_profiles.id", ondelete="CASCADE")
    )
    
    # Session details
    session_token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    
    # Session metadata
    ip_address: Mapped[str] = mapped_column(INET, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255))
    device_name: Mapped[Optional[str]] = mapped_column(String(100))
    location: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Session timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    
    # Session status
    status: Mapped[str] = mapped_column(String(20), server_default="active")
    terminated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    terminated_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True))
    termination_reason: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Security flags
    is_trusted_device: Mapped[bool] = mapped_column(Boolean, server_default="false")
    requires_mfa: Mapped[bool] = mapped_column(Boolean, server_default="true")
    mfa_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    
    # Relationships
    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="sessions")
    
    # Constraints
    __table_args__ = (
        CheckConstraint("expires_at > created_at"),
        CheckConstraint("status IN ('active', 'expired', 'revoked')"),
        CheckConstraint(
            "(status = 'active') OR (terminated_at IS NOT NULL)",
            name="check_terminated_sessions"
        ),
        Index("idx_user_sessions_user", "user_id"),
        Index("idx_user_sessions_token", "session_token"),
        Index("idx_user_sessions_status", "status"),
        Index("idx_user_sessions_expires", "expires_at"),
        Index("idx_user_sessions_ip", "ip_address"),
        Index("idx_user_sessions_device", "device_fingerprint"),
    )


class AuthAttempt(Base):
    """Authentication attempts tracking for security monitoring."""
    
    __tablename__ = "auth_attempts"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Attempt details
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("user_profiles.id")
    )
    email: Mapped[Optional[str]] = mapped_column(String(255))
    ip_address: Mapped[str] = mapped_column(INET, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    
    # Attempt result
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(100))
    
    # MFA details
    mfa_required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    mfa_success: Mapped[Optional[bool]] = mapped_column(Boolean)
    mfa_method: Mapped[Optional[str]] = mapped_column(String(20))
    
    # Timing
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    
    # Location and risk scoring
    location: Mapped[Optional[dict]] = mapped_column(JSON)
    risk_score: Mapped[int] = mapped_column(Integer, server_default="0")
    
    # Additional metadata
    metadata: Mapped[Optional[dict]] = mapped_column(JSON, server_default="{}")
    
    # Relationships
    user: Mapped[Optional["UserProfile"]] = relationship("UserProfile", back_populates="auth_attempts")
    
    # Constraints
    __table_args__ = (
        CheckConstraint("risk_score >= 0 AND risk_score <= 100"),
        CheckConstraint("mfa_method IN ('totp', 'sms', 'email') OR mfa_method IS NULL"),
        Index("idx_auth_attempts_user", "user_id"),
        Index("idx_auth_attempts_ip", "ip_address"),
        Index("idx_auth_attempts_time", "attempted_at"),
        Index("idx_auth_attempts_success", "success"),
        Index("idx_auth_attempts_email", "email"),
    )


class SecurityAuditLog(Base):
    """Comprehensive security event audit log."""
    
    __tablename__ = "security_audit_log"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("tenants.id")
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("user_profiles.id")
    )
    
    # Event details
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Context
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    resource_id: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Event data
    event_data: Mapped[Optional[dict]] = mapped_column(JSON, server_default="{}")
    
    # Risk assessment
    risk_level: Mapped[str] = mapped_column(String(20), server_default="low")
    
    # Timing
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    
    # Additional metadata
    metadata: Mapped[Optional[dict]] = mapped_column(JSON, server_default="{}")
    
    # Constraints
    __table_args__ = (
        CheckConstraint("risk_level IN ('low', 'medium', 'high', 'critical')"),
        CheckConstraint(
            "event_type IN ('login_success', 'login_failed', 'logout', 'password_changed', "
            "'mfa_enabled', 'mfa_disabled', 'account_locked', 'account_unlocked', "
            "'session_created', 'session_expired', 'password_reset_requested', "
            "'password_reset_completed', 'suspicious_activity', 'authorization_check', "
            "'data_access', 'configuration_change')"
        ),
        Index("idx_security_audit_tenant", "tenant_id"),
        Index("idx_security_audit_user", "user_id"),
        Index("idx_security_audit_type", "event_type"),
        Index("idx_security_audit_time", "occurred_at"),
        Index("idx_security_audit_risk", "risk_level"),
        Index("idx_security_audit_resource", "resource_type", "resource_id"),
    )


class PasswordResetToken(Base):
    """Secure password reset token management."""
    
    __tablename__ = "password_reset_tokens"
    
    # Primary identification
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), 
        ForeignKey("user_profiles.id", ondelete="CASCADE")
    )
    
    # Token details
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    
    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Request context
    ip_address: Mapped[str] = mapped_column(INET, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    
    # Status
    is_used: Mapped[bool] = mapped_column(Boolean, server_default="false")
    
    # Constraints
    __table_args__ = (
        CheckConstraint("expires_at > created_at"),
        CheckConstraint("(NOT is_used) OR (used_at IS NOT NULL)"),
        Index("idx_password_reset_user", "user_id"),
        Index("idx_password_reset_token", "token_hash"),
        Index("idx_password_reset_expires", "expires_at"),
        Index("idx_password_reset_used", "is_used"),
    )


class RateLimit(Base):
    """Rate limiting tracking for abuse prevention."""
    
    __tablename__ = "rate_limits"
    
    # Composite primary key
    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # endpoint:identifier
    
    # Rate limit details
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    identifier: Mapped[str] = mapped_column(String(100), nullable=False)  # IP, user_id, etc.
    
    # Counts and timing
    request_count: Mapped[int] = mapped_column(Integer, server_default="1")
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    
    # Rate limit status
    is_blocked: Mapped[bool] = mapped_column(Boolean, server_default="false")
    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Metadata
    last_request: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    metadata: Mapped[Optional[dict]] = mapped_column(JSON, server_default="{}")
    
    # Constraints
    __table_args__ = (
        CheckConstraint("request_count >= 0"),
        Index("idx_rate_limits_endpoint", "endpoint"),
        Index("idx_rate_limits_identifier", "identifier"),
        Index("idx_rate_limits_window", "window_start"),
        Index("idx_rate_limits_blocked", "is_blocked"),
    )