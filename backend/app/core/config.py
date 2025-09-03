"""
Application configuration management using Pydantic settings.
Supports environment variables and .env files.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import AnyHttpUrl, BaseSettings, EmailStr, validator
from pydantic.fields import Field


class Settings(BaseSettings):
    """Application configuration with validation and environment variable support."""
    
    # Application settings
    APP_NAME: str = "Invoice Reconciliation Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = Field(default="development", env="ENVIRONMENT")
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    
    # CORS settings
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    
    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    # Database settings
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    DATABASE_POOL_SIZE: int = Field(default=10, env="DATABASE_POOL_SIZE")
    DATABASE_MAX_OVERFLOW: int = Field(default=20, env="DATABASE_MAX_OVERFLOW")
    
    # Redis settings
    REDIS_URL: str = Field(..., env="REDIS_URL")
    REDIS_MAX_CONNECTIONS: int = Field(default=10, env="REDIS_MAX_CONNECTIONS")
    
    # JWT Authentication settings
    JWT_SECRET_KEY: str = Field(..., env="JWT_SECRET_KEY")
    JWT_ALGORITHM: str = Field(default="RS256", env="JWT_ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, env="REFRESH_TOKEN_EXPIRE_DAYS")
    
    # JWT Keys for RS256
    JWT_PRIVATE_KEY: Optional[str] = Field(default=None, env="JWT_PRIVATE_KEY")
    JWT_PUBLIC_KEY: Optional[str] = Field(default=None, env="JWT_PUBLIC_KEY")
    
    @validator("JWT_PRIVATE_KEY", "JWT_PUBLIC_KEY")
    def validate_jwt_keys(cls, v: Optional[str], field) -> Optional[str]:
        if v is None:
            return v
        # Remove any extra whitespace and normalize line endings
        return v.replace('\\n', '\n').strip()
    
    # Password settings
    PASSWORD_MIN_LENGTH: int = Field(default=12, env="PASSWORD_MIN_LENGTH")
    PASSWORD_REQUIRE_UPPERCASE: bool = Field(default=True, env="PASSWORD_REQUIRE_UPPERCASE")
    PASSWORD_REQUIRE_LOWERCASE: bool = Field(default=True, env="PASSWORD_REQUIRE_LOWERCASE")
    PASSWORD_REQUIRE_DIGITS: bool = Field(default=True, env="PASSWORD_REQUIRE_DIGITS")
    PASSWORD_REQUIRE_SPECIAL: bool = Field(default=True, env="PASSWORD_REQUIRE_SPECIAL")
    PASSWORD_HISTORY_COUNT: int = Field(default=5, env="PASSWORD_HISTORY_COUNT")
    
    # Account lockout settings
    MAX_LOGIN_ATTEMPTS: int = Field(default=5, env="MAX_LOGIN_ATTEMPTS")
    LOCKOUT_DURATION_MINUTES: int = Field(default=30, env="LOCKOUT_DURATION_MINUTES")
    PROGRESSIVE_DELAY_ENABLED: bool = Field(default=True, env="PROGRESSIVE_DELAY_ENABLED")
    
    # Session settings
    SESSION_EXPIRE_HOURS: int = Field(default=8, env="SESSION_EXPIRE_HOURS")
    MAX_CONCURRENT_SESSIONS: int = Field(default=3, env="MAX_CONCURRENT_SESSIONS")
    TRUSTED_DEVICE_EXPIRE_DAYS: int = Field(default=30, env="TRUSTED_DEVICE_EXPIRE_DAYS")
    
    # MFA settings
    MFA_ENABLED: bool = Field(default=True, env="MFA_ENABLED")
    MFA_ISSUER_NAME: str = Field(default="Invoice Reconciliation Platform", env="MFA_ISSUER_NAME")
    MFA_DIGITS: int = Field(default=6, env="MFA_DIGITS")
    MFA_PERIOD: int = Field(default=30, env="MFA_PERIOD")
    MFA_BACKUP_CODES_COUNT: int = Field(default=10, env="MFA_BACKUP_CODES_COUNT")
    
    # Rate limiting settings
    RATE_LIMIT_ENABLED: bool = Field(default=True, env="RATE_LIMIT_ENABLED")
    RATE_LIMIT_LOGIN: str = Field(default="5/minute", env="RATE_LIMIT_LOGIN")
    RATE_LIMIT_API: str = Field(default="100/minute", env="RATE_LIMIT_API")
    RATE_LIMIT_BULK_UPLOAD: str = Field(default="10/hour", env="RATE_LIMIT_BULK_UPLOAD")
    
    # Email settings
    SMTP_SERVER: Optional[str] = Field(default=None, env="SMTP_SERVER")
    SMTP_PORT: int = Field(default=587, env="SMTP_PORT")
    SMTP_USERNAME: Optional[str] = Field(default=None, env="SMTP_USERNAME")
    SMTP_PASSWORD: Optional[str] = Field(default=None, env="SMTP_PASSWORD")
    SMTP_USE_TLS: bool = Field(default=True, env="SMTP_USE_TLS")
    FROM_EMAIL: Optional[EmailStr] = Field(default=None, env="FROM_EMAIL")
    FROM_NAME: str = Field(default="Invoice Reconciliation Platform", env="FROM_NAME")
    
    # Password reset settings
    PASSWORD_RESET_EXPIRE_MINUTES: int = Field(default=30, env="PASSWORD_RESET_EXPIRE_MINUTES")
    FRONTEND_URL: str = Field(default="https://app.example.com", env="FRONTEND_URL")
    
    # Monitoring and logging
    SENTRY_DSN: Optional[str] = Field(default=None, env="SENTRY_DSN")
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    STRUCTURED_LOGGING: bool = Field(default=True, env="STRUCTURED_LOGGING")
    
    # File upload settings
    MAX_UPLOAD_SIZE: int = Field(default=10 * 1024 * 1024, env="MAX_UPLOAD_SIZE")  # 10MB
    ALLOWED_UPLOAD_EXTENSIONS: List[str] = Field(
        default=["pdf", "csv", "xlsx", "xls"], 
        env="ALLOWED_UPLOAD_EXTENSIONS"
    )
    
    # Feature flags
    ENABLE_IDEMPOTENCY: bool = Field(default=True, env="ENABLE_IDEMPOTENCY")
    ENABLE_SWAGGER: bool = Field(default=True, env="ENABLE_SWAGGER")
    ENABLE_METRICS: bool = Field(default=True, env="ENABLE_METRICS")
    ENABLE_AUDIT_LOG: bool = Field(default=True, env="ENABLE_AUDIT_LOG")
    
    # External integrations
    QUICKBOOKS_CLIENT_ID: Optional[str] = Field(default=None, env="QUICKBOOKS_CLIENT_ID")
    QUICKBOOKS_CLIENT_SECRET: Optional[str] = Field(default=None, env="QUICKBOOKS_CLIENT_SECRET")
    XERO_CLIENT_ID: Optional[str] = Field(default=None, env="XERO_CLIENT_ID")
    XERO_CLIENT_SECRET: Optional[str] = Field(default=None, env="XERO_CLIENT_SECRET")
    
    # Supabase settings (since we're using Supabase for auth backend)
    SUPABASE_URL: Optional[str] = Field(default=None, env="SUPABASE_URL")
    SUPABASE_ANON_KEY: Optional[str] = Field(default=None, env="SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = Field(default=None, env="SUPABASE_SERVICE_ROLE_KEY")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENVIRONMENT.lower() == "development"
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT.lower() == "production"
    
    @property
    def database_config(self) -> Dict[str, Any]:
        """Get database configuration dictionary."""
        return {
            "url": self.DATABASE_URL,
            "pool_size": self.DATABASE_POOL_SIZE,
            "max_overflow": self.DATABASE_MAX_OVERFLOW,
            "echo": self.DEBUG and self.is_development,
        }
    
    @property
    def redis_config(self) -> Dict[str, Any]:
        """Get Redis configuration dictionary."""
        return {
            "url": self.REDIS_URL,
            "max_connections": self.REDIS_MAX_CONNECTIONS,
            "decode_responses": True,
        }
    
    @property
    def cors_config(self) -> Dict[str, Any]:
        """Get CORS configuration dictionary."""
        return {
            "allow_origins": [str(origin) for origin in self.BACKEND_CORS_ORIGINS],
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
            "allow_headers": [
                "Authorization",
                "Content-Type",
                "X-Requested-With",
                "Idempotency-Key",
                "X-Tenant-ID",
            ],
        }


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings instance."""
    return Settings()


# Convenience function to get settings
settings = get_settings()