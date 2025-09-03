"""
Database configuration and connection management for PostgreSQL with async support.
Implements connection pooling, RLS context setting, and health checks.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from uuid import UUID

from databases import Database
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.auth import Base


# Global database instances
database: Optional[Database] = None
async_engine = None
AsyncSessionLocal = None


async def connect_db():
    """Initialize database connections."""
    global database, async_engine, AsyncSessionLocal
    
    if database is None:
        # Create databases instance for raw queries
        database = Database(settings.DATABASE_URL)
        await database.connect()
    
    if async_engine is None:
        # Create SQLAlchemy async engine
        async_engine = create_async_engine(
            settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=3600,  # 1 hour
            echo=settings.DEBUG and settings.is_development,
        )
        
        # Create session factory
        AsyncSessionLocal = async_sessionmaker(
            async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )


async def disconnect_db():
    """Close database connections."""
    global database, async_engine
    
    if database:
        await database.disconnect()
        database = None
    
    if async_engine:
        await async_engine.dispose()
        async_engine = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency to get database session.
    
    Yields:
        AsyncSession: Database session
    """
    if AsyncSessionLocal is None:
        await connect_db()
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_with_tenant(tenant_id: UUID) -> AsyncGenerator[AsyncSession, None]:
    """
    Get database session with tenant context for RLS.
    
    Args:
        tenant_id: Tenant UUID for RLS context
        
    Yields:
        AsyncSession: Database session with tenant context
    """
    if AsyncSessionLocal is None:
        await connect_db()
    
    async with AsyncSessionLocal() as session:
        try:
            # Set tenant context for RLS
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)}
            )
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    """
    Async context manager for database sessions.
    
    Usage:
        async with get_db_context() as db:
            # Use db session
    """
    if AsyncSessionLocal is None:
        await connect_db()
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    """Create all database tables."""
    if async_engine is None:
        await connect_db()
    
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    """Drop all database tables (development only)."""
    if not settings.is_development:
        raise RuntimeError("Table dropping is only allowed in development")
    
    if async_engine is None:
        await connect_db()
    
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def health_check() -> dict:
    """
    Perform database health check.
    
    Returns:
        Health status information
    """
    try:
        if database is None:
            await connect_db()
        
        # Test basic query
        start_time = asyncio.get_event_loop().time()
        result = await database.fetch_one("SELECT 1 as test")
        response_time = asyncio.get_event_loop().time() - start_time
        
        if result and result["test"] == 1:
            return {
                "status": "healthy",
                "response_time_seconds": response_time,
                "connection_pool_size": settings.DATABASE_POOL_SIZE,
                "max_overflow": settings.DATABASE_MAX_OVERFLOW
            }
        else:
            return {
                "status": "unhealthy",
                "error": "Test query failed"
            }
            
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


async def execute_migration(migration_sql: str):
    """
    Execute database migration SQL.
    
    Args:
        migration_sql: SQL commands to execute
    """
    if async_engine is None:
        await connect_db()
    
    async with async_engine.begin() as conn:
        # Split by semicolon and execute each statement
        statements = [stmt.strip() for stmt in migration_sql.split(';') if stmt.strip()]
        
        for statement in statements:
            await conn.execute(text(statement))


class DatabaseManager:
    """Database manager for application lifecycle."""
    
    def __init__(self):
        self.connected = False
    
    async def startup(self):
        """Initialize database connections on startup."""
        try:
            await connect_db()
            self.connected = True
            
            # Run health check
            health = await health_check()
            if health["status"] != "healthy":
                raise RuntimeError(f"Database health check failed: {health.get('error')}")
                
            print(f"✅ Database connected successfully (response time: {health.get('response_time_seconds', 0):.3f}s)")
            
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            raise
    
    async def shutdown(self):
        """Close database connections on shutdown."""
        try:
            await disconnect_db()
            self.connected = False
            print("✅ Database disconnected successfully")
            
        except Exception as e:
            print(f"❌ Database disconnect failed: {e}")
    
    async def reset_database(self):
        """Reset database (development only)."""
        if not settings.is_development:
            raise RuntimeError("Database reset is only allowed in development")
        
        await drop_tables()
        await create_tables()
        print("✅ Database reset completed")


# Global database manager instance
db_manager = DatabaseManager()