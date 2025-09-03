"""
Security audit service for logging authentication events and security incidents.
Provides comprehensive audit trail for compliance and security monitoring.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from pydantic import BaseModel

from app.models.auth import SecurityAuditLog, AuthAttempt


class AuditEventData(BaseModel):
    """Audit event data structure."""
    event_type: str
    description: str
    user_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    risk_level: str = "low"
    event_data: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}


class SecurityMetrics(BaseModel):
    """Security metrics summary."""
    total_events: int
    events_by_type: Dict[str, int]
    events_by_risk_level: Dict[str, int]
    failed_logins_24h: int
    locked_accounts: int
    suspicious_activities: int
    top_risk_ips: List[Dict[str, Any]]


class AuditService:
    """Security audit service for comprehensive event logging and analysis."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def log_security_event(
        self,
        event_type: str,
        description: str,
        tenant_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        risk_level: str = "low",
        event_data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log security event to audit trail.
        
        Args:
            event_type: Type of security event
            description: Human-readable description
            tenant_id: Tenant UUID (if applicable)
            user_id: User UUID (if applicable)
            resource_type: Type of resource affected
            resource_id: Resource identifier
            ip_address: Source IP address
            user_agent: User agent string
            risk_level: Risk level (low, medium, high, critical)
            event_data: Additional event-specific data
            metadata: Additional metadata
        """
        audit_log = SecurityAuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event_type,
            event_description=description,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            risk_level=risk_level,
            event_data=event_data or {},
            metadata=metadata or {},
            occurred_at=datetime.utcnow()
        )
        
        self.db.add(audit_log)
        await self.db.commit()
    
    async def log_authentication_event(
        self,
        event_type: str,
        user_id: Optional[UUID],
        tenant_id: Optional[UUID],
        email: str,
        ip_address: str,
        user_agent: Optional[str] = None,
        success: bool = True,
        failure_reason: Optional[str] = None,
        mfa_used: bool = False,
        device_fingerprint: Optional[str] = None
    ):
        """
        Log authentication-specific events.
        
        Args:
            event_type: Authentication event type
            user_id: User UUID (if known)
            tenant_id: Tenant UUID (if known)
            email: User email
            ip_address: Source IP address
            user_agent: User agent string
            success: Whether authentication succeeded
            failure_reason: Reason for failure (if applicable)
            mfa_used: Whether MFA was used
            device_fingerprint: Device fingerprint
        """
        event_data = {
            "email": email,
            "success": success,
            "mfa_used": mfa_used,
            "device_fingerprint": device_fingerprint
        }
        
        if failure_reason:
            event_data["failure_reason"] = failure_reason
        
        risk_level = "low"
        if not success:
            risk_level = "medium"
            if failure_reason in ["brute_force", "suspicious_activity", "account_locked"]:
                risk_level = "high"
        
        await self.log_security_event(
            event_type=event_type,
            description=f"Authentication attempt: {event_type}",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="authentication",
            ip_address=ip_address,
            user_agent=user_agent,
            risk_level=risk_level,
            event_data=event_data
        )
    
    async def log_authorization_event(
        self,
        user_id: UUID,
        tenant_id: UUID,
        resource_type: str,
        resource_id: str,
        action: str,
        allowed: bool,
        ip_address: Optional[str] = None,
        reason: Optional[str] = None
    ):
        """
        Log authorization events.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            resource_type: Type of resource
            resource_id: Resource identifier
            action: Action attempted
            allowed: Whether action was allowed
            ip_address: Source IP address
            reason: Reason for denial (if applicable)
        """
        event_data = {
            "action": action,
            "allowed": allowed
        }
        
        if reason:
            event_data["reason"] = reason
        
        description = f"Authorization {'granted' if allowed else 'denied'} for {action} on {resource_type}"
        
        await self.log_security_event(
            event_type="authorization_check",
            description=description,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            risk_level="low" if allowed else "medium",
            event_data=event_data
        )
    
    async def log_data_access_event(
        self,
        user_id: UUID,
        tenant_id: UUID,
        resource_type: str,
        resource_id: str,
        action: str,
        ip_address: Optional[str] = None,
        sensitive_data: bool = False,
        data_classification: str = "internal"
    ):
        """
        Log data access events for compliance.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            resource_type: Type of resource accessed
            resource_id: Resource identifier
            action: Action performed
            ip_address: Source IP address
            sensitive_data: Whether sensitive data was accessed
            data_classification: Data classification level
        """
        event_data = {
            "action": action,
            "sensitive_data": sensitive_data,
            "data_classification": data_classification
        }
        
        risk_level = "low"
        if sensitive_data:
            risk_level = "medium"
        if data_classification in ["confidential", "restricted"]:
            risk_level = "high"
        
        await self.log_security_event(
            event_type="data_access",
            description=f"Data access: {action} on {resource_type}",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            risk_level=risk_level,
            event_data=event_data
        )
    
    async def log_configuration_change(
        self,
        user_id: UUID,
        tenant_id: UUID,
        resource_type: str,
        resource_id: str,
        changes: Dict[str, Any],
        ip_address: Optional[str] = None
    ):
        """
        Log configuration changes.
        
        Args:
            user_id: User making the change
            tenant_id: Tenant UUID
            resource_type: Type of resource changed
            resource_id: Resource identifier
            changes: Dictionary of changes made
            ip_address: Source IP address
        """
        await self.log_security_event(
            event_type="configuration_change",
            description=f"Configuration change on {resource_type}",
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            risk_level="medium",
            event_data={"changes": changes}
        )
    
    async def get_security_metrics(
        self,
        tenant_id: Optional[UUID] = None,
        hours: int = 24
    ) -> SecurityMetrics:
        """
        Get security metrics for dashboard.
        
        Args:
            tenant_id: Filter by tenant (None for system-wide)
            hours: Time window in hours
            
        Returns:
            SecurityMetrics summary
        """
        time_threshold = datetime.utcnow() - timedelta(hours=hours)
        
        # Base query conditions
        conditions = [SecurityAuditLog.occurred_at >= time_threshold]
        if tenant_id:
            conditions.append(SecurityAuditLog.tenant_id == tenant_id)
        
        # Total events
        total_events_query = select(func.count(SecurityAuditLog.id)).where(and_(*conditions))
        total_events_result = await self.db.execute(total_events_query)
        total_events = total_events_result.scalar() or 0
        
        # Events by type
        events_by_type_query = select(
            SecurityAuditLog.event_type,
            func.count(SecurityAuditLog.id)
        ).where(and_(*conditions)).group_by(SecurityAuditLog.event_type)
        events_by_type_result = await self.db.execute(events_by_type_query)
        events_by_type = dict(events_by_type_result.fetchall())
        
        # Events by risk level
        events_by_risk_query = select(
            SecurityAuditLog.risk_level,
            func.count(SecurityAuditLog.id)
        ).where(and_(*conditions)).group_by(SecurityAuditLog.risk_level)
        events_by_risk_result = await self.db.execute(events_by_risk_query)
        events_by_risk_level = dict(events_by_risk_result.fetchall())
        
        # Failed logins in last 24h
        auth_conditions = [AuthAttempt.attempted_at >= time_threshold, AuthAttempt.success == False]
        failed_logins_query = select(func.count(AuthAttempt.id)).where(and_(*auth_conditions))
        failed_logins_result = await self.db.execute(failed_logins_query)
        failed_logins_24h = failed_logins_result.scalar() or 0
        
        # Top risk IPs
        top_risk_ips_query = select(
            SecurityAuditLog.ip_address,
            func.count(SecurityAuditLog.id).label('event_count'),
            func.max(SecurityAuditLog.risk_level).label('max_risk')
        ).where(
            and_(
                SecurityAuditLog.occurred_at >= time_threshold,
                SecurityAuditLog.ip_address.isnot(None),
                SecurityAuditLog.risk_level.in_(['medium', 'high', 'critical'])
            )
        ).group_by(SecurityAuditLog.ip_address).order_by(
            func.count(SecurityAuditLog.id).desc()
        ).limit(10)
        
        top_risk_ips_result = await self.db.execute(top_risk_ips_query)
        top_risk_ips = [
            {
                "ip_address": row.ip_address,
                "event_count": row.event_count,
                "max_risk_level": row.max_risk
            }
            for row in top_risk_ips_result.fetchall()
        ]
        
        # Suspicious activities (high/critical risk events)
        suspicious_query = select(func.count(SecurityAuditLog.id)).where(
            and_(
                SecurityAuditLog.occurred_at >= time_threshold,
                SecurityAuditLog.risk_level.in_(['high', 'critical'])
            )
        )
        if tenant_id:
            suspicious_query = suspicious_query.where(SecurityAuditLog.tenant_id == tenant_id)
        
        suspicious_result = await self.db.execute(suspicious_query)
        suspicious_activities = suspicious_result.scalar() or 0
        
        return SecurityMetrics(
            total_events=total_events,
            events_by_type=events_by_type,
            events_by_risk_level=events_by_risk_level,
            failed_logins_24h=failed_logins_24h,
            locked_accounts=0,  # Would need separate query for locked accounts
            suspicious_activities=suspicious_activities,
            top_risk_ips=top_risk_ips
        )
    
    async def get_audit_trail(
        self,
        tenant_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        event_type: Optional[str] = None,
        resource_type: Optional[str] = None,
        risk_level: Optional[str] = None,
        hours: int = 24,
        limit: int = 100,
        offset: int = 0
    ) -> List[SecurityAuditLog]:
        """
        Get filtered audit trail.
        
        Args:
            tenant_id: Filter by tenant
            user_id: Filter by user
            event_type: Filter by event type
            resource_type: Filter by resource type
            risk_level: Filter by risk level
            hours: Time window in hours
            limit: Maximum records to return
            offset: Pagination offset
            
        Returns:
            List of audit log entries
        """
        time_threshold = datetime.utcnow() - timedelta(hours=hours)
        conditions = [SecurityAuditLog.occurred_at >= time_threshold]
        
        if tenant_id:
            conditions.append(SecurityAuditLog.tenant_id == tenant_id)
        if user_id:
            conditions.append(SecurityAuditLog.user_id == user_id)
        if event_type:
            conditions.append(SecurityAuditLog.event_type == event_type)
        if resource_type:
            conditions.append(SecurityAuditLog.resource_type == resource_type)
        if risk_level:
            conditions.append(SecurityAuditLog.risk_level == risk_level)
        
        query = select(SecurityAuditLog).where(
            and_(*conditions)
        ).order_by(
            SecurityAuditLog.occurred_at.desc()
        ).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def detect_suspicious_patterns(
        self,
        tenant_id: Optional[UUID] = None,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Detect suspicious activity patterns.
        
        Args:
            tenant_id: Filter by tenant
            hours: Time window in hours
            
        Returns:
            List of suspicious patterns detected
        """
        time_threshold = datetime.utcnow() - timedelta(hours=hours)
        patterns = []
        
        # Pattern 1: Multiple failed logins from same IP
        failed_logins_query = select(
            AuthAttempt.ip_address,
            func.count(AuthAttempt.id).label('failed_count'),
            func.count(func.distinct(AuthAttempt.email)).label('unique_emails')
        ).where(
            and_(
                AuthAttempt.attempted_at >= time_threshold,
                AuthAttempt.success == False
            )
        ).group_by(AuthAttempt.ip_address).having(
            func.count(AuthAttempt.id) >= 10
        )
        
        failed_logins_result = await self.db.execute(failed_logins_query)
        for row in failed_logins_result.fetchall():
            patterns.append({
                "type": "brute_force_attempt",
                "description": f"Multiple failed logins from IP {row.ip_address}",
                "severity": "high",
                "data": {
                    "ip_address": row.ip_address,
                    "failed_attempts": row.failed_count,
                    "unique_emails": row.unique_emails
                }
            })
        
        # Pattern 2: Successful login after many failures
        suspicious_success_query = select(
            AuthAttempt.ip_address,
            AuthAttempt.email,
            func.count(AuthAttempt.id).label('total_attempts')
        ).where(
            and_(
                AuthAttempt.attempted_at >= time_threshold,
                AuthAttempt.success == True
            )
        ).group_by(AuthAttempt.ip_address, AuthAttempt.email)
        
        # Pattern 3: Geographic anomalies (would need geolocation data)
        # Pattern 4: Unusual access times (would need user behavior baseline)
        
        return patterns
    
    async def cleanup_old_audit_logs(self, days: int = 90) -> int:
        """
        Clean up old audit logs beyond retention period.
        
        Args:
            days: Retention period in days
            
        Returns:
            Number of records deleted
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Delete old security audit logs
        delete_query = SecurityAuditLog.__table__.delete().where(
            SecurityAuditLog.occurred_at < cutoff_date
        )
        result = await self.db.execute(delete_query)
        deleted_count = result.rowcount
        
        # Delete old auth attempts
        delete_auth_query = AuthAttempt.__table__.delete().where(
            AuthAttempt.attempted_at < cutoff_date
        )
        auth_result = await self.db.execute(delete_auth_query)
        deleted_count += auth_result.rowcount
        
        await self.db.commit()
        return deleted_count


# Helper function to create audit service with database session
async def get_audit_service(db: AsyncSession) -> AuditService:
    """Get audit service instance with database session."""
    return AuditService(db)


# Global audit service (initialized with request-specific DB session)
audit_service = None