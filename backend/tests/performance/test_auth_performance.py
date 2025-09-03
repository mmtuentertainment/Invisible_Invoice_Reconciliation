"""
Performance tests for authentication system
Tests authentication performance, scalability, and resource usage
"""

import pytest
import asyncio
import time
import psutil
from datetime import datetime
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any

from app.services.auth_service import AuthenticationService, LoginRequest, DeviceInfo
from app.services.redis_service import redis_service
from app.models.auth import UserProfile
from app.core.security import security
from app.core.database import get_db


@pytest.mark.performance
class TestAuthenticationPerformance:
    """Performance tests for authentication system"""
    
    @pytest.fixture
    async def db_session(self):
        """Get database session for tests"""
        async for session in get_db():
            yield session
    
    @pytest.fixture
    async def performance_users(self, db_session):
        """Create multiple test users for performance testing"""
        users = []
        tenant_id = uuid4()
        
        for i in range(100):
            user = UserProfile(
                id=uuid4(),
                tenant_id=tenant_id,
                email=f"perf_user_{i}@test.com",
                password_hash=security.hash_password("TestPassword123!"),
                full_name=f"Performance User {i}",
                auth_status="active",
                created_at=datetime.utcnow()
            )
            users.append(user)
            db_session.add(user)
        
        await db_session.commit()
        yield users
        
        # Cleanup
        for user in users:
            await db_session.delete(user)
        await db_session.commit()
    
    @pytest.mark.asyncio
    async def test_single_authentication_performance(self, db_session, performance_users):
        """Test single authentication request performance"""
        auth_service = AuthenticationService(db_session)
        user = performance_users[0]
        
        device_info = DeviceInfo(
            ip_address="127.0.0.1",
            user_agent="Performance Test Client",
            fingerprint="perf_device"
        )
        
        login_request = LoginRequest(
            email=user.email,
            password="TestPassword123!"
        )
        
        # Warm up
        await auth_service.authenticate_user(login_request, device_info)
        
        # Measure performance
        start_time = time.perf_counter()
        result = await auth_service.authenticate_user(login_request, device_info)
        end_time = time.perf_counter()
        
        duration = end_time - start_time
        
        assert result.success is True
        assert duration < 0.5  # Should complete within 500ms
        
        print(f"Single authentication time: {duration:.3f} seconds")
    
    @pytest.mark.asyncio
    async def test_concurrent_authentication_performance(self, db_session, performance_users):
        """Test concurrent authentication performance"""
        auth_service = AuthenticationService(db_session)
        
        async def authenticate_user(user_index: int):
            user = performance_users[user_index]
            device_info = DeviceInfo(
                ip_address="127.0.0.1",
                user_agent=f"Perf Client {user_index}",
                fingerprint=f"device_{user_index}"
            )
            
            login_request = LoginRequest(
                email=user.email,
                password="TestPassword123!"
            )
            
            start_time = time.perf_counter()
            result = await auth_service.authenticate_user(login_request, device_info)
            end_time = time.perf_counter()
            
            return {
                'success': result.success,
                'duration': end_time - start_time,
                'user_index': user_index
            }
        
        # Test with different concurrency levels
        concurrency_levels = [10, 25, 50]
        
        for concurrency in concurrency_levels:
            start_time = time.perf_counter()
            
            tasks = [authenticate_user(i) for i in range(concurrency)]
            results = await asyncio.gather(*tasks)
            
            end_time = time.perf_counter()
            total_duration = end_time - start_time
            
            successful_logins = sum(1 for r in results if r['success'])
            avg_duration = sum(r['duration'] for r in results) / len(results)
            throughput = successful_logins / total_duration
            
            print(f"Concurrency {concurrency}: {successful_logins}/{concurrency} successful")
            print(f"Total time: {total_duration:.3f}s, Avg per request: {avg_duration:.3f}s")
            print(f"Throughput: {throughput:.2f} req/s")
            
            # Performance assertions
            assert successful_logins >= concurrency * 0.9  # At least 90% success
            assert avg_duration < 2.0  # Average should be under 2 seconds
            assert throughput > 5  # Should handle at least 5 req/s
    
    @pytest.mark.asyncio
    async def test_token_operations_performance(self, db_session, performance_users):
        """Test JWT token creation and verification performance"""
        user = performance_users[0]
        permissions = ["invoice:read", "vendor:manage", "user:read"]
        
        # Test token creation performance
        create_times = []
        for _ in range(1000):
            start_time = time.perf_counter()
            token = security.create_access_token(
                user_id=user.id,
                tenant_id=user.tenant_id,
                permissions=permissions
            )
            end_time = time.perf_counter()
            create_times.append(end_time - start_time)
        
        avg_create_time = sum(create_times) / len(create_times)
        
        # Test token verification performance
        verify_times = []
        for _ in range(1000):
            start_time = time.perf_counter()
            payload = security.verify_token(token)
            end_time = time.perf_counter()
            verify_times.append(end_time - start_time)
        
        avg_verify_time = sum(verify_times) / len(verify_times)
        
        print(f"Avg token creation time: {avg_create_time*1000:.2f}ms")
        print(f"Avg token verification time: {avg_verify_time*1000:.2f}ms")
        
        # Performance assertions
        assert avg_create_time < 0.01  # Should be under 10ms
        assert avg_verify_time < 0.005  # Should be under 5ms
    
    @pytest.mark.asyncio
    async def test_password_hashing_performance(self):
        """Test password hashing and verification performance"""
        passwords = [f"TestPassword{i}!" for i in range(100)]
        
        # Test hashing performance
        hash_times = []
        hashes = []
        
        for password in passwords:
            start_time = time.perf_counter()
            password_hash = security.hash_password(password)
            end_time = time.perf_counter()
            
            hash_times.append(end_time - start_time)
            hashes.append(password_hash)
        
        avg_hash_time = sum(hash_times) / len(hash_times)
        
        # Test verification performance
        verify_times = []
        for password, password_hash in zip(passwords, hashes):
            start_time = time.perf_counter()
            is_valid = security.verify_password(password, password_hash)
            end_time = time.perf_counter()
            
            verify_times.append(end_time - start_time)
            assert is_valid is True
        
        avg_verify_time = sum(verify_times) / len(verify_times)
        
        print(f"Avg password hashing time: {avg_hash_time*1000:.2f}ms")
        print(f"Avg password verification time: {avg_verify_time*1000:.2f}ms")
        
        # Performance assertions (bcrypt should be slow by design)
        assert 0.05 < avg_hash_time < 0.5  # Should be between 50ms-500ms
        assert 0.05 < avg_verify_time < 0.5  # Should be between 50ms-500ms
    
    @pytest.mark.asyncio
    async def test_redis_performance(self):
        """Test Redis operations performance"""
        # Test rate limiting performance
        rate_limit_times = []
        
        for i in range(1000):
            key = f"test_rate_limit_{i}"
            start_time = time.perf_counter()
            result = await redis_service.check_rate_limit(key, limit=10, window=60)
            end_time = time.perf_counter()
            
            rate_limit_times.append(end_time - start_time)
        
        avg_rate_limit_time = sum(rate_limit_times) / len(rate_limit_times)
        
        # Test token blacklisting performance
        blacklist_times = []
        tokens = [f"test_token_{i}" for i in range(1000)]
        
        for token in tokens:
            start_time = time.perf_counter()
            await redis_service.blacklist_token(token)
            end_time = time.perf_counter()
            
            blacklist_times.append(end_time - start_time)
        
        avg_blacklist_time = sum(blacklist_times) / len(blacklist_times)
        
        print(f"Avg rate limit check time: {avg_rate_limit_time*1000:.2f}ms")
        print(f"Avg token blacklist time: {avg_blacklist_time*1000:.2f}ms")
        
        # Performance assertions
        assert avg_rate_limit_time < 0.01  # Should be under 10ms
        assert avg_blacklist_time < 0.01  # Should be under 10ms
        
        # Cleanup
        for token in tokens:
            await redis_service.client.delete(f"blacklist:{token}")
    
    @pytest.mark.asyncio
    async def test_memory_usage_under_load(self, db_session, performance_users):
        """Test memory usage during high load authentication"""
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        auth_service = AuthenticationService(db_session)
        
        # Create many concurrent authentication requests
        async def authenticate_user(user_index: int):
            user = performance_users[user_index % len(performance_users)]
            device_info = DeviceInfo(
                ip_address=f"192.168.1.{user_index % 255}",
                user_agent=f"Load Test Client {user_index}",
                fingerprint=f"load_device_{user_index}"
            )
            
            login_request = LoginRequest(
                email=user.email,
                password="TestPassword123!"
            )
            
            return await auth_service.authenticate_user(login_request, device_info)
        
        # Run 500 concurrent authentications
        tasks = [authenticate_user(i) for i in range(500)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        peak_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = peak_memory - initial_memory
        
        successful_auths = sum(1 for r in results if hasattr(r, 'success') and r.success)
        
        print(f"Initial memory: {initial_memory:.2f} MB")
        print(f"Peak memory: {peak_memory:.2f} MB")
        print(f"Memory increase: {memory_increase:.2f} MB")
        print(f"Successful authentications: {successful_auths}/500")
        
        # Memory usage should be reasonable
        assert memory_increase < 500  # Should not increase by more than 500MB
        assert successful_auths > 400  # Should have high success rate
    
    @pytest.mark.asyncio
    async def test_database_connection_pool_performance(self, performance_users):
        """Test database connection pool performance under load"""
        async def db_operation():
            async for session in get_db():
                # Simulate database-heavy authentication operations
                from sqlalchemy import select, text
                
                # Multiple queries similar to authentication flow
                await session.execute(select(UserProfile).limit(1))
                await session.execute(text("SELECT 1"))
                await session.execute(select(UserProfile).where(UserProfile.email == 'test@example.com'))
                return True
        
        # Test connection pool under high concurrency
        start_time = time.perf_counter()
        
        tasks = [db_operation() for _ in range(100)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.perf_counter()
        duration = end_time - start_time
        
        successful_ops = sum(1 for r in results if r is True)
        
        print(f"Database operations: {successful_ops}/100 successful")
        print(f"Total time: {duration:.3f}s")
        print(f"Avg time per operation: {duration/100:.3f}s")
        
        # Performance assertions
        assert successful_ops >= 95  # At least 95% success
        assert duration < 10.0  # Should complete within 10 seconds
        assert duration/100 < 0.1  # Average should be under 100ms per operation


@pytest.mark.performance
class TestAuthenticationScalability:
    """Scalability tests for authentication system"""
    
    @pytest.mark.asyncio
    async def test_user_scalability(self, db_session):
        """Test authentication performance with large number of users"""
        # This test would create thousands of users and test authentication
        # performance as user base grows
        pass
    
    @pytest.mark.asyncio
    async def test_session_scalability(self, db_session):
        """Test session management with thousands of active sessions"""
        # Test session management performance with large number of active sessions
        pass
    
    @pytest.mark.asyncio
    async def test_audit_log_scalability(self, db_session):
        """Test audit logging performance with high volume"""
        # Test audit logging performance with thousands of events
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "performance"])