"""
FastAPI main application with comprehensive authentication system
Production-ready application with security, monitoring, and error handling
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

# Import core modules
from app.core.config import settings
from app.core.database import db_manager
from app.core.middleware import (
    SecurityHeadersMiddleware,
    RateLimitMiddleware,
    DeviceFingerprintMiddleware,
    TenantContextMiddleware,
    AuditLoggingMiddleware
)
from app.services.redis_service import redis_service

# Import API routers
from app.api.v1.endpoints import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown events"""
    # Startup
    try:
        print("🚀 Starting Invoice Reconciliation Platform API...")
        
        # Initialize database
        await db_manager.startup()
        
        # Initialize Redis
        await redis_service.connect()
        
        # Verify Redis health
        redis_health = await redis_service.health_check()
        if redis_health["status"] != "healthy":
            print(f"⚠️ Redis health check failed: {redis_health.get('error')}")
        else:
            print(f"✅ Redis connected (response time: {redis_health.get('response_time_seconds', 0):.3f}s)")
        
        print("✅ Application startup completed successfully")
        
    except Exception as e:
        print(f"❌ Application startup failed: {e}")
        raise
    
    yield
    
    # Shutdown
    try:
        print("🛑 Shutting down Invoice Reconciliation Platform API...")
        
        # Close database connections
        await db_manager.shutdown()
        
        # Close Redis connection
        await redis_service.disconnect()
        
        print("✅ Application shutdown completed successfully")
        
    except Exception as e:
        print(f"❌ Application shutdown failed: {e}")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Secure invoice reconciliation platform with automated 3-way matching",
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.ENABLE_SWAGGER else None,
    docs_url=None,  # Disabled by default, custom docs below
    redoc_url=None,
    lifespan=lifespan,
)

# Add security middleware (order matters!)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(TenantContextMiddleware)
app.add_middleware(DeviceFingerprintMiddleware)
app.add_middleware(RateLimitMiddleware, enabled=settings.RATE_LIMIT_ENABLED)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    **settings.cors_config
)

# Add trusted host middleware for production
if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["invoice-recon.com", "*.invoice-recon.com"]
    )


# Custom OpenAPI schema
def custom_openapi():
    """Generate custom OpenAPI schema with security definitions"""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token for authentication"
        }
    }
    
    # Add security to all endpoints
    for path in openapi_schema["paths"]:
        for method in openapi_schema["paths"][path]:
            if method != "options":  # Exclude OPTIONS
                openapi_schema["paths"][path][method]["security"] = [
                    {"BearerAuth": []}
                ]
    
    # Add custom info
    openapi_schema["info"]["x-logo"] = {
        "url": "https://invoice-recon.com/logo.png"
    }
    
    openapi_schema["info"]["contact"] = {
        "name": "API Support",
        "url": "https://invoice-recon.com/support",
        "email": "support@invoice-recon.com"
    }
    
    openapi_schema["info"]["license"] = {
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT"
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# Custom documentation endpoint
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """Custom Swagger UI with enhanced security"""
    if not settings.ENABLE_SWAGGER:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documentation is disabled"
        )
    
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Interactive API Documentation",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@4.15.5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@4.15.5/swagger-ui.css",
        swagger_ui_parameters={
            "deepLinking": True,
            "displayOperationId": True,
            "defaultModelsExpandDepth": 2,
            "defaultModelExpandDepth": 2,
            "displayRequestDuration": True,
            "docExpansion": "none",
            "filter": True,
            "showExtensions": True,
            "showCommonExtensions": True,
        }
    )


# Global exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with RFC 9457 format"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": f"https://api.invoice-recon.com/errors/{exc.status_code}",
            "title": "HTTP Error",
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": str(request.url),
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    if settings.DEBUG:
        import traceback
        detail = f"{exc.__class__.__name__}: {str(exc)}\n{traceback.format_exc()}"
    else:
        detail = "An internal server error occurred"
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "type": "https://api.invoice-recon.com/errors/internal-server-error",
            "title": "Internal Server Error",
            "status": 500,
            "detail": detail,
            "instance": str(request.url),
        }
    )


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Comprehensive health check for monitoring"""
    try:
        # Check database
        db_health = await db_manager.health_check()
        
        # Check Redis
        redis_health = await redis_service.health_check()
        
        # Determine overall status
        overall_status = "healthy"
        if db_health["status"] != "healthy" or redis_health["status"] != "healthy":
            overall_status = "unhealthy"
        
        return {
            "status": overall_status,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "timestamp": "2025-01-03T12:00:00Z",
            "services": {
                "database": db_health,
                "redis": redis_health,
            }
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": "2025-01-03T12:00:00Z"
            }
        )


# Readiness probe for Kubernetes
@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Readiness check for container orchestration"""
    # Check if all critical services are ready
    db_health = await db_manager.health_check()
    redis_health = await redis_service.health_check()
    
    if db_health["status"] == "healthy" and redis_health["status"] == "healthy":
        return {"status": "ready"}
    else:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not ready"}
        )


# Liveness probe for Kubernetes
@app.get("/alive", tags=["Health"])
async def liveness_check():
    """Liveness check for container orchestration"""
    return {"status": "alive"}


# Include API routers
app.include_router(auth.router, prefix=settings.API_V1_STR, tags=["Authentication"])

# Add additional routers here as they are created
# app.include_router(invoices.router, prefix=settings.API_V1_STR, tags=["Invoices"])
# app.include_router(vendors.router, prefix=settings.API_V1_STR, tags=["Vendors"])
# app.include_router(matching.router, prefix=settings.API_V1_STR, tags=["Matching"])


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """API root endpoint with basic information"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "Secure invoice reconciliation platform with automated 3-way matching",
        "environment": settings.ENVIRONMENT,
        "documentation": "/docs" if settings.ENABLE_SWAGGER else None,
        "health": "/health",
        "api_version": "v1",
        "api_base": settings.API_V1_STR,
        "features": [
            "Multi-tenant architecture",
            "JWT authentication with MFA",
            "Role-based access control",
            "Automated invoice matching",
            "Real-time audit logging",
            "Enterprise security features"
        ]
    }


# Metrics endpoint for Prometheus (if enabled)
if settings.ENABLE_METRICS:
    from prometheus_fastapi_instrumentator import Instrumentator
    
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics"],
        env_var_name="ENABLE_METRICS",
        inprogress_name="inprogress",
        inprogress_labels=True,
    )
    
    instrumentator.instrument(app).expose(app, endpoint="/metrics", tags=["Metrics"])


# Add startup message
@app.on_event("startup")
async def startup_message():
    """Display startup information"""
    print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                     Invoice Reconciliation Platform API                     ║
║                                                                              ║
║  Version: {settings.APP_VERSION:<20} Environment: {settings.ENVIRONMENT:<20}      ║
║  Debug: {str(settings.DEBUG):<22} Docs: {'/docs' if settings.ENABLE_SWAGGER else 'Disabled':<26}      ║
║                                                                              ║
║  🔒 Security Features Active:                                               ║
║  • JWT Authentication with RS256                                            ║
║  • Multi-Factor Authentication (TOTP)                                       ║
║  • Role-Based Access Control                                                ║
║  • Rate Limiting & IP Blocking                                              ║
║  • Session Management & Device Tracking                                     ║
║  • Comprehensive Audit Logging                                              ║
║  • Multi-Tenant Row Level Security                                          ║
║                                                                              ║
║  📊 Endpoints: /health, /ready, /alive, {settings.API_V1_STR}                        ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    import uvicorn
    
    # Development server
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        reload_excludes=["*.pyc", "*.log"],
        log_level="info",
        access_log=True,
        use_colors=True,
    )