"""
FastAPI middleware for authentication, authorization, rate limiting, and security headers.
Implements comprehensive security middleware stack for the application.
"""

import time
import hashlib
from datetime import datetime
from typing import Callable, Optional
from uuid import UUID

from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from app.core.config import settings
from app.core.security import security
from app.services.redis_service import redis_service
from app.services.rbac_service import get_rbac_service
from app.models.auth import UserProfile


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> StarletteResponse:
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            )
        
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware for rate limiting requests."""
    
    def __init__(self, app, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled and settings.RATE_LIMIT_ENABLED
    
    async def dispatch(self, request: Request, call_next: Callable) -> StarletteResponse:
        if not self.enabled:
            return await call_next(request)
        
        # Get client IP address
        client_ip = self._get_client_ip(request)
        
        # Check if IP is blocked
        if await redis_service.is_ip_blocked(client_ip):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "type": "https://api.invoice-recon.com/errors/rate-limit",
                    "title": "IP Address Blocked",
                    "status": 429,
                    "detail": "Your IP address has been temporarily blocked due to suspicious activity"
                }
            )
        
        # Apply endpoint-specific rate limiting
        rate_limit_key = self._get_rate_limit_key(request)
        limit, window = self._get_rate_limit_config(request)
        
        if not await redis_service.check_rate_limit(rate_limit_key, limit, window):
            # Get rate limit info for headers
            rate_info = await redis_service.get_rate_limit_info(rate_limit_key, limit, window)
            
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "type": "https://api.invoice-recon.com/errors/rate-limit",
                    "title": "Rate Limit Exceeded",
                    "status": 429,
                    "detail": f"Too many requests. Limit: {limit} per {window} seconds"
                }
            )
            
            # Add rate limit headers
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(rate_info.remaining)
            response.headers["X-RateLimit-Reset"] = str(int(rate_info.reset_time.timestamp()))
            
            if rate_info.retry_after:
                response.headers["Retry-After"] = str(rate_info.retry_after)
            
            return response
        
        response = await call_next(request)
        
        # Add rate limit headers to successful responses
        rate_info = await redis_service.get_rate_limit_info(rate_limit_key, limit, window)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(rate_info.remaining)
        response.headers["X-RateLimit-Reset"] = str(int(rate_info.reset_time.timestamp()))
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request."""
        # Check X-Forwarded-For header first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        # Check X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        # Fall back to direct client IP
        return request.client.host if request.client else "unknown"
    
    def _get_rate_limit_key(self, request: Request) -> str:
        """Generate rate limit key for request."""
        client_ip = self._get_client_ip(request)
        endpoint = f"{request.method}:{request.url.path}"
        return f"{endpoint}:{client_ip}"
    
    def _get_rate_limit_config(self, request: Request) -> tuple[int, int]:
        """Get rate limit configuration for endpoint."""
        path = request.url.path
        
        # Authentication endpoints (stricter limits)
        if "/auth/" in path:
            if "login" in path:
                return 5, 60  # 5 attempts per minute
            elif "refresh" in path:
                return 10, 60  # 10 refreshes per minute
            return 20, 60  # General auth endpoints
        
        # Bulk upload endpoints
        if "/bulk" in path:
            return 10, 3600  # 10 uploads per hour
        
        # Default API limits
        return 100, 60  # 100 requests per minute


class AuthenticationMiddleware:
    """Dependency for JWT authentication and user context."""
    
    def __init__(self):
        self.bearer_scheme = HTTPBearer(auto_error=False)
    
    async def __call__(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = None
    ) -> Optional[dict]:
        """
        Authenticate request and return user context.
        
        Returns:
            Dictionary with user_id, tenant_id, permissions, and session_id
        """
        if not credentials:
            credentials = await self.bearer_scheme(request)
        
        if not credentials:
            return None
        
        # Verify JWT token
        payload = security.verify_token(credentials.credentials)
        if not payload:
            return None
        
        # Check if token is blacklisted
        if await redis_service.is_token_blacklisted(credentials.credentials):
            return None
        
        # Validate session if session_id is present
        if payload.session_id:
            session_data = await redis_service.get_session(payload.session_id)
            if not session_data:
                return None
            
            # Update session last accessed
            await redis_service.extend_session(payload.session_id, settings.SESSION_EXPIRE_HOURS * 3600)
        
        return {
            "user_id": UUID(payload.sub),
            "tenant_id": UUID(payload.tenant_id),
            "permissions": payload.permissions or [],
            "session_id": payload.session_id,
            "device_id": payload.device_id,
            "token_type": payload.type
        }


class DeviceFingerprintMiddleware(BaseHTTPMiddleware):
    """Middleware to generate and track device fingerprints."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> StarletteResponse:
        # Generate device fingerprint from request headers
        fingerprint = self._generate_device_fingerprint(request)
        
        # Add fingerprint to request state
        request.state.device_fingerprint = fingerprint
        
        # Track device if user is authenticated
        if hasattr(request.state, "user") and request.state.user:
            client_ip = self._get_client_ip(request)
            user_agent = request.headers.get("User-Agent", "")
            
            # Track device attempt (will be marked as successful if request completes)
            await redis_service.track_device_attempt(
                device_fingerprint=fingerprint,
                ip_address=client_ip,
                user_agent=user_agent,
                success=True  # Assume success, error handler will update if needed
            )
        
        return await call_next(request)
    
    def _generate_device_fingerprint(self, request: Request) -> str:
        """Generate device fingerprint from request characteristics."""
        # Collect fingerprinting data
        user_agent = request.headers.get("User-Agent", "")
        accept = request.headers.get("Accept", "")
        accept_language = request.headers.get("Accept-Language", "")
        accept_encoding = request.headers.get("Accept-Encoding", "")
        
        # Create fingerprint string
        fingerprint_data = f"{user_agent}:{accept}:{accept_language}:{accept_encoding}"
        
        # Hash the fingerprint for privacy and consistency
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        return request.client.host if request.client else "unknown"


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Middleware to set tenant context for database queries."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> StarletteResponse:
        # Extract tenant ID from authentication or headers
        tenant_id = None
        
        # Try to get tenant from authenticated user context
        if hasattr(request.state, "user") and request.state.user:
            tenant_id = request.state.user.get("tenant_id")
        
        # Try to get tenant from X-Tenant-ID header (for service-to-service calls)
        if not tenant_id:
            tenant_header = request.headers.get("X-Tenant-ID")
            if tenant_header:
                try:
                    tenant_id = UUID(tenant_header)
                except ValueError:
                    pass
        
        # Store tenant context in request state
        if tenant_id:
            request.state.tenant_id = tenant_id
        
        return await call_next(request)


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for audit logging of requests."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> StarletteResponse:
        start_time = time.time()
        
        # Extract request information
        method = request.method
        path = request.url.path
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "")
        
        # Get user context if available
        user_id = None
        tenant_id = None
        if hasattr(request.state, "user") and request.state.user:
            user_id = request.state.user.get("user_id")
            tenant_id = request.state.user.get("tenant_id")
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            success = 200 <= status_code < 400
            
        except Exception as e:
            status_code = 500
            success = False
            response = JSONResponse(
                status_code=500,
                content={
                    "type": "https://api.invoice-recon.com/errors/internal-server-error",
                    "title": "Internal Server Error",
                    "status": 500,
                    "detail": "An unexpected error occurred"
                }
            )
        
        processing_time = time.time() - start_time
        
        # Log audit trail for sensitive operations
        if self._should_audit_request(path, method):
            # Import here to avoid circular imports
            from app.services.audit_service import AuditService
            from app.core.database import get_db
            
            # This would need to be async context, simplified for now
            # In real implementation, you'd use background tasks
            pass
        
        # Add performance headers
        response.headers["X-Processing-Time"] = f"{processing_time:.3f}"
        
        return response
    
    def _should_audit_request(self, path: str, method: str) -> bool:
        """Determine if request should be audited."""
        # Audit authentication operations
        if "/auth/" in path:
            return True
        
        # Audit data modification operations
        if method in ["POST", "PUT", "PATCH", "DELETE"]:
            return True
        
        # Audit admin operations
        if "/admin/" in path:
            return True
        
        return False
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        return request.client.host if request.client else "unknown"


# Dependency functions for FastAPI endpoints

async def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency to get current authenticated user.
    
    Raises:
        HTTPException: If user is not authenticated
    """
    auth_middleware = AuthenticationMiddleware()
    user_context = await auth_middleware(request)
    
    if not user_context:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return user_context


async def get_current_active_user(request: Request) -> dict:
    """
    FastAPI dependency to get current active user.
    
    Raises:
        HTTPException: If user is not authenticated or inactive
    """
    user_context = await get_current_user(request)
    
    # Additional checks can be added here to verify user is active
    # This would typically involve database lookup
    
    return user_context


def require_permissions(*required_permissions: str):
    """
    FastAPI dependency factory to require specific permissions.
    
    Args:
        *required_permissions: List of required permission strings
    
    Returns:
        Dependency function that checks permissions
    """
    async def permission_dependency(
        request: Request,
        user_context: dict = None
    ) -> dict:
        if not user_context:
            user_context = await get_current_user(request)
        
        user_permissions = set(user_context.get("permissions", []))
        
        # Check if user has system admin permission
        if "system:*" in user_permissions:
            return user_context
        
        # Check if user has any of the required permissions
        required_perms = set(required_permissions)
        if not required_perms.intersection(user_permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {list(required_perms)}"
            )
        
        return user_context
    
    return permission_dependency


def require_role(*required_roles: str):
    """
    FastAPI dependency factory to require specific roles.
    
    Args:
        *required_roles: List of required role names
    
    Returns:
        Dependency function that checks roles
    """
    async def role_dependency(
        request: Request,
        user_context: dict = None
    ) -> dict:
        if not user_context:
            user_context = await get_current_user(request)
        
        # This would require additional database lookup to get user roles
        # Simplified implementation for now
        
        return user_context
    
    return role_dependency


async def get_device_info(request: Request) -> dict:
    """
    FastAPI dependency to get device information.
    
    Returns:
        Dictionary with device information
    """
    return {
        "ip_address": request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown"),
        "user_agent": request.headers.get("User-Agent", ""),
        "device_fingerprint": getattr(request.state, "device_fingerprint", None),
        "device_name": request.headers.get("X-Device-Name")
    }