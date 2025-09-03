"""
Redis service for caching, session management, rate limiting, and token blacklisting.
Provides comprehensive Redis-based functionality for authentication and security.
"""

import json
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

import redis.asyncio as redis
from pydantic import BaseModel

from app.core.config import settings


class RateLimitInfo(BaseModel):
    """Rate limit information model."""
    allowed: bool
    limit: int
    remaining: int
    reset_time: datetime
    retry_after: Optional[int] = None


class RedisService:
    """Redis service for caching, sessions, and rate limiting."""
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.connection_pool: Optional[redis.ConnectionPool] = None
    
    async def connect(self):
        """Initialize Redis connection pool."""
        try:
            self.connection_pool = redis.ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                decode_responses=True,
                retry_on_timeout=True,
                health_check_interval=30
            )
            
            self.redis_client = redis.Redis(
                connection_pool=self.connection_pool
            )
            
            # Test connection
            await self.redis_client.ping()
            
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Redis: {e}")
    
    async def disconnect(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()
        if self.connection_pool:
            await self.connection_pool.disconnect()
    
    # Rate Limiting Methods
    
    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int,
        identifier: Optional[str] = None
    ) -> bool:
        """
        Check if request is within rate limit using sliding window.
        
        Args:
            key: Rate limit key
            limit: Maximum requests allowed
            window: Time window in seconds
            identifier: Additional identifier for logging
            
        Returns:
            True if request is allowed
        """
        if not self.redis_client:
            return True  # Allow if Redis is unavailable
        
        rate_key = f"rate_limit:{key}"
        current_time = datetime.utcnow().timestamp()
        window_start = current_time - window
        
        pipe = self.redis_client.pipeline()
        
        # Remove expired entries
        pipe.zremrangebyscore(rate_key, 0, window_start)
        
        # Count current requests in window
        pipe.zcard(rate_key)
        
        # Add current request
        pipe.zadd(rate_key, {str(current_time): current_time})
        
        # Set expiration
        pipe.expire(rate_key, window + 1)
        
        results = await pipe.execute()
        current_count = results[1]
        
        if current_count >= limit:
            # Remove the request we just added since it's over limit
            await self.redis_client.zrem(rate_key, str(current_time))
            return False
        
        return True
    
    async def get_rate_limit_info(
        self,
        key: str,
        limit: int,
        window: int
    ) -> RateLimitInfo:
        """
        Get detailed rate limit information.
        
        Args:
            key: Rate limit key
            limit: Maximum requests allowed
            window: Time window in seconds
            
        Returns:
            RateLimitInfo with current status
        """
        if not self.redis_client:
            return RateLimitInfo(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_time=datetime.utcnow() + timedelta(seconds=window)
            )
        
        rate_key = f"rate_limit:{key}"
        current_time = datetime.utcnow().timestamp()
        window_start = current_time - window
        
        # Clean old entries and count current
        pipe = self.redis_client.pipeline()
        pipe.zremrangebyscore(rate_key, 0, window_start)
        pipe.zcard(rate_key)
        results = await pipe.execute()
        
        current_count = results[1]
        remaining = max(0, limit - current_count)
        reset_time = datetime.utcnow() + timedelta(seconds=window)
        
        return RateLimitInfo(
            allowed=current_count < limit,
            limit=limit,
            remaining=remaining,
            reset_time=reset_time,
            retry_after=window if current_count >= limit else None
        )
    
    async def get_progressive_delay(self, key: str) -> float:
        """
        Get progressive delay for failed attempts.
        
        Args:
            key: Delay tracking key
            
        Returns:
            Delay in seconds
        """
        if not self.redis_client:
            return 0.0
        
        delay_key = f"progressive_delay:{key}"
        
        try:
            # Get current attempt count
            attempts = await self.redis_client.get(delay_key)
            if not attempts:
                # First failure, set counter and minimal delay
                await self.redis_client.setex(delay_key, 300, "1")  # 5 minutes
                return 0.5
            
            attempt_count = int(attempts)
            # Increment counter
            await self.redis_client.incr(delay_key)
            await self.redis_client.expire(delay_key, 300)  # Reset after 5 minutes
            
            # Calculate exponential backoff delay (max 30 seconds)
            delay = min(2 ** attempt_count * 0.5, 30.0)
            return delay
            
        except Exception:
            return 0.0
    
    # Token Blacklisting
    
    async def blacklist_token(self, token: str, expires_in: int = 3600):
        """
        Add token to blacklist.
        
        Args:
            token: JWT token to blacklist
            expires_in: Expiration time in seconds
        """
        if not self.redis_client:
            return
        
        blacklist_key = f"blacklisted_token:{token}"
        await self.redis_client.setex(blacklist_key, expires_in, "1")
    
    async def is_token_blacklisted(self, token: str) -> bool:
        """
        Check if token is blacklisted.
        
        Args:
            token: JWT token to check
            
        Returns:
            True if token is blacklisted
        """
        if not self.redis_client:
            return False
        
        blacklist_key = f"blacklisted_token:{token}"
        result = await self.redis_client.get(blacklist_key)
        return result is not None
    
    # Session Management
    
    async def store_session(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        expires_in: int = 28800  # 8 hours
    ):
        """
        Store session data in Redis.
        
        Args:
            session_id: Session identifier
            session_data: Session data dictionary
            expires_in: Expiration time in seconds
        """
        if not self.redis_client:
            return
        
        session_key = f"session:{session_id}"
        await self.redis_client.setex(
            session_key,
            expires_in,
            json.dumps(session_data, default=str)
        )
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session data from Redis.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session data dictionary or None
        """
        if not self.redis_client:
            return None
        
        session_key = f"session:{session_id}"
        session_data = await self.redis_client.get(session_key)
        
        if session_data:
            try:
                return json.loads(session_data)
            except json.JSONDecodeError:
                return None
        
        return None
    
    async def delete_session(self, session_id: str):
        """
        Delete session from Redis.
        
        Args:
            session_id: Session identifier
        """
        if not self.redis_client:
            return
        
        session_key = f"session:{session_id}"
        await self.redis_client.delete(session_key)
    
    async def extend_session(self, session_id: str, extends_by: int = 3600):
        """
        Extend session expiration time.
        
        Args:
            session_id: Session identifier
            extends_by: Extension time in seconds
        """
        if not self.redis_client:
            return
        
        session_key = f"session:{session_id}"
        await self.redis_client.expire(session_key, extends_by)
    
    async def get_user_sessions(self, user_id: Union[str, UUID]) -> List[str]:
        """
        Get all active sessions for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of session IDs
        """
        if not self.redis_client:
            return []
        
        user_sessions_key = f"user_sessions:{user_id}"
        session_ids = await self.redis_client.smembers(user_sessions_key)
        return list(session_ids) if session_ids else []
    
    async def add_user_session(self, user_id: Union[str, UUID], session_id: str):
        """
        Track session for user.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
        """
        if not self.redis_client:
            return
        
        user_sessions_key = f"user_sessions:{user_id}"
        await self.redis_client.sadd(user_sessions_key, session_id)
        await self.redis_client.expire(user_sessions_key, 86400)  # 24 hours
    
    async def remove_user_session(self, user_id: Union[str, UUID], session_id: str):
        """
        Remove session tracking for user.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
        """
        if not self.redis_client:
            return
        
        user_sessions_key = f"user_sessions:{user_id}"
        await self.redis_client.srem(user_sessions_key, session_id)
    
    # Caching Methods
    
    async def set_cache(
        self,
        key: str,
        value: Any,
        expires_in: int = 3600,
        namespace: str = "cache"
    ):
        """
        Set cache value with expiration.
        
        Args:
            key: Cache key
            value: Value to cache (will be JSON encoded)
            expires_in: Expiration time in seconds
            namespace: Cache namespace
        """
        if not self.redis_client:
            return
        
        cache_key = f"{namespace}:{key}"
        serialized_value = json.dumps(value, default=str)
        await self.redis_client.setex(cache_key, expires_in, serialized_value)
    
    async def get_cache(
        self,
        key: str,
        namespace: str = "cache"
    ) -> Optional[Any]:
        """
        Get cache value.
        
        Args:
            key: Cache key
            namespace: Cache namespace
            
        Returns:
            Cached value or None
        """
        if not self.redis_client:
            return None
        
        cache_key = f"{namespace}:{key}"
        cached_value = await self.redis_client.get(cache_key)
        
        if cached_value:
            try:
                return json.loads(cached_value)
            except json.JSONDecodeError:
                return cached_value  # Return as string if not JSON
        
        return None
    
    async def delete_cache(
        self,
        key: str,
        namespace: str = "cache"
    ):
        """
        Delete cache entry.
        
        Args:
            key: Cache key
            namespace: Cache namespace
        """
        if not self.redis_client:
            return
        
        cache_key = f"{namespace}:{key}"
        await self.redis_client.delete(cache_key)
    
    async def delete_cache_pattern(
        self,
        pattern: str,
        namespace: str = "cache"
    ):
        """
        Delete cache entries matching pattern.
        
        Args:
            pattern: Pattern to match (Redis glob pattern)
            namespace: Cache namespace
        """
        if not self.redis_client:
            return
        
        search_pattern = f"{namespace}:{pattern}"
        keys = []
        
        async for key in self.redis_client.scan_iter(match=search_pattern):
            keys.append(key)
        
        if keys:
            await self.redis_client.delete(*keys)
    
    # IP Blocking and Security
    
    async def block_ip(
        self,
        ip_address: str,
        duration: int = 3600,
        reason: str = "suspicious_activity"
    ):
        """
        Block IP address temporarily.
        
        Args:
            ip_address: IP address to block
            duration: Block duration in seconds
            reason: Reason for blocking
        """
        if not self.redis_client:
            return
        
        block_key = f"blocked_ip:{ip_address}"
        block_data = {
            "blocked_at": datetime.utcnow().isoformat(),
            "reason": reason
        }
        await self.redis_client.setex(
            block_key,
            duration,
            json.dumps(block_data)
        )
    
    async def is_ip_blocked(self, ip_address: str) -> bool:
        """
        Check if IP address is blocked.
        
        Args:
            ip_address: IP address to check
            
        Returns:
            True if IP is blocked
        """
        if not self.redis_client:
            return False
        
        block_key = f"blocked_ip:{ip_address}"
        result = await self.redis_client.get(block_key)
        return result is not None
    
    async def unblock_ip(self, ip_address: str):
        """
        Unblock IP address.
        
        Args:
            ip_address: IP address to unblock
        """
        if not self.redis_client:
            return
        
        block_key = f"blocked_ip:{ip_address}"
        await self.redis_client.delete(block_key)
    
    # Device Fingerprinting
    
    async def track_device_attempt(
        self,
        device_fingerprint: str,
        ip_address: str,
        user_agent: str,
        success: bool
    ):
        """
        Track authentication attempt for device.
        
        Args:
            device_fingerprint: Device fingerprint
            ip_address: IP address
            user_agent: User agent string
            success: Whether attempt was successful
        """
        if not self.redis_client:
            return
        
        device_key = f"device_attempts:{device_fingerprint}"
        attempt_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "ip_address": ip_address,
            "user_agent": user_agent,
            "success": success
        }
        
        # Add to list (keep last 10 attempts)
        await self.redis_client.lpush(device_key, json.dumps(attempt_data))
        await self.redis_client.ltrim(device_key, 0, 9)  # Keep only 10 most recent
        await self.redis_client.expire(device_key, 86400)  # 24 hours
    
    async def get_device_attempts(
        self,
        device_fingerprint: str
    ) -> List[Dict[str, Any]]:
        """
        Get recent attempts for device.
        
        Args:
            device_fingerprint: Device fingerprint
            
        Returns:
            List of attempt data
        """
        if not self.redis_client:
            return []
        
        device_key = f"device_attempts:{device_fingerprint}"
        attempts = await self.redis_client.lrange(device_key, 0, -1)
        
        parsed_attempts = []
        for attempt in attempts:
            try:
                parsed_attempts.append(json.loads(attempt))
            except json.JSONDecodeError:
                continue
        
        return parsed_attempts
    
    # Health Check
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform Redis health check.
        
        Returns:
            Health status information
        """
        try:
            if not self.redis_client:
                return {
                    "status": "unhealthy",
                    "error": "Redis client not initialized"
                }
            
            # Test basic operations
            start_time = datetime.utcnow()
            await self.redis_client.ping()
            response_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Get Redis info
            info = await self.redis_client.info()
            
            return {
                "status": "healthy",
                "response_time_seconds": response_time,
                "redis_version": info.get("redis_version"),
                "used_memory": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "uptime_in_seconds": info.get("uptime_in_seconds")
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }


# Global Redis service instance
redis_service = RedisService()