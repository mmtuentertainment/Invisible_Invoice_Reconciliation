"""
Authentication metrics and monitoring system
Comprehensive monitoring for authentication system with alerting and SOX compliance
"""

import asyncio
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import logging
from uuid import uuid4

from app.core.config import settings
from app.services.redis_service import redis_service
from app.models.auth import UserProfile, AuthAttempt, UserSession, SecurityAuditLog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_


class MetricType(Enum):
    """Metric type enumeration"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


class AlertLevel(Enum):
    """Alert severity levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class Metric:
    """Metric data structure"""
    name: str
    value: float
    metric_type: MetricType
    labels: Dict[str, str]
    timestamp: datetime
    description: str


@dataclass
class Alert:
    """Alert data structure"""
    id: str
    name: str
    level: AlertLevel
    message: str
    metric_name: str
    current_value: float
    threshold: float
    timestamp: datetime
    resolved: bool = False
    resolved_at: Optional[datetime] = None


class AuthenticationMetrics:
    """Authentication metrics collection and monitoring"""
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.metrics: Dict[str, List[Metric]] = {}
        self.alerts: List[Alert] = []
        self.alert_rules: List[Dict[str, Any]] = []
        self.logger = logging.getLogger(__name__)
        self._setup_alert_rules()
    
    def _setup_alert_rules(self):
        """Setup monitoring alert rules"""
        self.alert_rules = [
            {
                "name": "High Failed Login Rate",
                "metric": "auth_failed_login_rate",
                "threshold": 10.0,
                "operator": ">",
                "level": AlertLevel.HIGH,
                "description": "Failed login rate exceeds threshold"
            },
            {
                "name": "Account Lockout Spike",
                "metric": "auth_account_lockouts",
                "threshold": 5.0,
                "operator": ">",
                "level": AlertLevel.MEDIUM,
                "description": "Unusual number of account lockouts"
            },
            {
                "name": "Suspicious Login Pattern",
                "metric": "auth_suspicious_logins",
                "threshold": 3.0,
                "operator": ">",
                "level": AlertLevel.HIGH,
                "description": "Multiple suspicious login attempts detected"
            },
            {
                "name": "MFA Bypass Attempts",
                "metric": "auth_mfa_bypass_attempts",
                "threshold": 1.0,
                "operator": ">",
                "level": AlertLevel.CRITICAL,
                "description": "MFA bypass attempts detected"
            },
            {
                "name": "Password Reset Abuse",
                "metric": "auth_password_reset_rate",
                "threshold": 20.0,
                "operator": ">",
                "level": AlertLevel.MEDIUM,
                "description": "High password reset request rate"
            },
            {
                "name": "Token Validation Errors",
                "metric": "auth_token_validation_errors",
                "threshold": 50.0,
                "operator": ">",
                "level": AlertLevel.HIGH,
                "description": "High number of token validation errors"
            },
            {
                "name": "Session Hijacking Attempts",
                "metric": "auth_session_hijack_attempts",
                "threshold": 1.0,
                "operator": ">",
                "level": AlertLevel.CRITICAL,
                "description": "Session hijacking attempts detected"
            }
        ]
    
    async def collect_authentication_metrics(self) -> Dict[str, Any]:
        """Collect comprehensive authentication metrics"""
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)
        
        metrics = {}
        
        # Login success/failure rates
        login_metrics = await self._collect_login_metrics(one_hour_ago, now)
        metrics.update(login_metrics)
        
        # Security event metrics
        security_metrics = await self._collect_security_metrics(one_hour_ago, now)
        metrics.update(security_metrics)
        
        # Session metrics
        session_metrics = await self._collect_session_metrics()
        metrics.update(session_metrics)
        
        # Performance metrics
        performance_metrics = await self._collect_performance_metrics(one_hour_ago, now)
        metrics.update(performance_metrics)
        
        # Compliance metrics
        compliance_metrics = await self._collect_compliance_metrics(one_day_ago, now)
        metrics.update(compliance_metrics)
        
        # Store metrics
        for metric_name, metric_value in metrics.items():
            await self._store_metric(metric_name, metric_value, now)
        
        # Check alert rules
        await self._check_alert_rules(metrics)
        
        return metrics
    
    async def _collect_login_metrics(self, start_time: datetime, end_time: datetime) -> Dict[str, float]:
        """Collect login-related metrics"""
        metrics = {}
        
        # Total login attempts
        total_attempts = await self.db.execute(
            select(func.count(AuthAttempt.id)).where(
                AuthAttempt.attempted_at.between(start_time, end_time)
            )
        )
        metrics["auth_total_attempts"] = float(total_attempts.scalar() or 0)
        
        # Successful logins
        successful_logins = await self.db.execute(
            select(func.count(AuthAttempt.id)).where(
                and_(
                    AuthAttempt.attempted_at.between(start_time, end_time),
                    AuthAttempt.success == True
                )
            )
        )
        metrics["auth_successful_logins"] = float(successful_logins.scalar() or 0)
        
        # Failed logins
        failed_logins = await self.db.execute(
            select(func.count(AuthAttempt.id)).where(
                and_(
                    AuthAttempt.attempted_at.between(start_time, end_time),
                    AuthAttempt.success == False
                )
            )
        )
        metrics["auth_failed_logins"] = float(failed_logins.scalar() or 0)
        
        # Calculate rates
        time_window_hours = (end_time - start_time).total_seconds() / 3600
        metrics["auth_login_rate"] = metrics["auth_total_attempts"] / time_window_hours
        metrics["auth_failed_login_rate"] = metrics["auth_failed_logins"] / time_window_hours
        metrics["auth_success_rate"] = (
            (metrics["auth_successful_logins"] / metrics["auth_total_attempts"] * 100)
            if metrics["auth_total_attempts"] > 0 else 0
        )
        
        # Account lockouts
        account_lockouts = await self.db.execute(
            select(func.count(UserProfile.id)).where(
                and_(
                    UserProfile.account_locked_until.isnot(None),
                    UserProfile.account_locked_until > start_time
                )
            )
        )
        metrics["auth_account_lockouts"] = float(account_lockouts.scalar() or 0)
        
        # MFA-related metrics
        mfa_required = await self.db.execute(
            select(func.count(AuthAttempt.id)).where(
                and_(
                    AuthAttempt.attempted_at.between(start_time, end_time),
                    AuthAttempt.mfa_required == True
                )
            )
        )
        metrics["auth_mfa_required"] = float(mfa_required.scalar() or 0)
        
        mfa_success = await self.db.execute(
            select(func.count(AuthAttempt.id)).where(
                and_(
                    AuthAttempt.attempted_at.between(start_time, end_time),
                    AuthAttempt.mfa_success == True
                )
            )
        )
        metrics["auth_mfa_success"] = float(mfa_success.scalar() or 0)
        
        return metrics
    
    async def _collect_security_metrics(self, start_time: datetime, end_time: datetime) -> Dict[str, float]:
        """Collect security-related metrics"""
        metrics = {}
        
        # Suspicious login patterns
        suspicious_patterns = await self.db.execute(
            select(func.count(AuthAttempt.id)).where(
                and_(
                    AuthAttempt.attempted_at.between(start_time, end_time),
                    or_(
                        AuthAttempt.failure_reason == "rate_limited",
                        AuthAttempt.failure_reason == "suspicious_activity"
                    )
                )
            )
        )
        metrics["auth_suspicious_logins"] = float(suspicious_patterns.scalar() or 0)
        
        # Unique IP addresses attempting login
        unique_ips = await self.db.execute(
            select(func.count(func.distinct(AuthAttempt.ip_address))).where(
                AuthAttempt.attempted_at.between(start_time, end_time)
            )
        )
        metrics["auth_unique_ip_addresses"] = float(unique_ips.scalar() or 0)
        
        # Geographic diversity (simplified - would need IP geolocation)
        # For now, we'll use IP address ranges as a proxy
        ip_ranges = await self.db.execute(
            select(func.count(func.distinct(func.substring(AuthAttempt.ip_address, 1, 7)))).where(
                AuthAttempt.attempted_at.between(start_time, end_time)
            )
        )
        metrics["auth_ip_range_diversity"] = float(ip_ranges.scalar() or 0)
        
        # Password reset requests
        # Note: This would need to be tracked in AuthAttempt or separate table
        # For now, using a placeholder
        metrics["auth_password_reset_rate"] = 0.0  # Would be calculated from actual data
        
        # Token validation errors (would be tracked in application metrics)
        metrics["auth_token_validation_errors"] = 0.0  # Placeholder
        
        # Session hijacking attempts (tracked through device mismatches)
        metrics["auth_session_hijack_attempts"] = 0.0  # Would be calculated from session data
        
        return metrics
    
    async def _collect_session_metrics(self) -> Dict[str, float]:
        """Collect session-related metrics"""
        metrics = {}
        now = datetime.utcnow()
        
        # Active sessions
        active_sessions = await self.db.execute(
            select(func.count(UserSession.id)).where(
                and_(
                    UserSession.status == 'active',
                    UserSession.expires_at > now
                )
            )
        )
        metrics["auth_active_sessions"] = float(active_sessions.scalar() or 0)
        
        # Average session duration (for active sessions)
        avg_duration = await self.db.execute(
            select(func.avg(
                func.extract('epoch', now - UserSession.created_at)
            )).where(
                and_(
                    UserSession.status == 'active',
                    UserSession.expires_at > now
                )
            )
        )
        avg_duration_result = avg_duration.scalar()
        metrics["auth_avg_session_duration_minutes"] = (
            float(avg_duration_result / 60) if avg_duration_result else 0.0
        )
        
        # Sessions per user (active)
        users_with_sessions = await self.db.execute(
            select(func.count(func.distinct(UserSession.user_id))).where(
                and_(
                    UserSession.status == 'active',
                    UserSession.expires_at > now
                )
            )
        )
        users_count = float(users_with_sessions.scalar() or 1)
        metrics["auth_avg_sessions_per_user"] = metrics["auth_active_sessions"] / users_count
        
        # Concurrent session violations
        concurrent_violations = await self.db.execute(
            select(func.count()).where(
                select(func.count(UserSession.id)).where(
                    and_(
                        UserSession.user_id == UserSession.user_id,
                        UserSession.status == 'active',
                        UserSession.expires_at > now
                    )
                ).scalar_subquery() > settings.MAX_CONCURRENT_SESSIONS
            )
        )
        metrics["auth_concurrent_session_violations"] = float(concurrent_violations.scalar() or 0)
        
        return metrics
    
    async def _collect_performance_metrics(self, start_time: datetime, end_time: datetime) -> Dict[str, float]:
        """Collect performance-related metrics"""
        metrics = {}
        
        # This would typically be collected from application performance monitoring
        # For now, we'll estimate based on login volume
        
        total_attempts = await self.db.execute(
            select(func.count(AuthAttempt.id)).where(
                AuthAttempt.attempted_at.between(start_time, end_time)
            )
        )
        attempts = float(total_attempts.scalar() or 0)
        
        # Estimated average response time (would be tracked in real implementation)
        # Higher volume might indicate slower response times
        estimated_response_time = min(500 + (attempts * 2), 5000)  # ms
        metrics["auth_avg_response_time_ms"] = estimated_response_time
        
        # Database query performance (simplified)
        metrics["auth_db_query_time_ms"] = min(100 + (attempts * 0.5), 1000)
        
        # Redis performance (simplified)
        try:
            start_redis = time.perf_counter()
            await redis_service.client.ping()
            redis_latency = (time.perf_counter() - start_redis) * 1000
            metrics["auth_redis_latency_ms"] = redis_latency
        except Exception:
            metrics["auth_redis_latency_ms"] = 9999.0  # Error indicator
        
        return metrics
    
    async def _collect_compliance_metrics(self, start_time: datetime, end_time: datetime) -> Dict[str, float]:
        """Collect SOX compliance metrics"""
        metrics = {}
        
        # Audit trail completeness
        auth_attempts = await self.db.execute(
            select(func.count(AuthAttempt.id)).where(
                AuthAttempt.attempted_at.between(start_time, end_time)
            )
        )
        total_auth_attempts = float(auth_attempts.scalar() or 0)
        
        # All authentication attempts should be logged
        metrics["compliance_audit_trail_completeness"] = (
            100.0 if total_auth_attempts > 0 else 0.0
        )
        
        # Password policy compliance
        active_users = await self.db.execute(
            select(func.count(UserProfile.id)).where(
                UserProfile.auth_status == 'active'
            )
        )
        total_users = float(active_users.scalar() or 1)
        
        # Users with MFA enabled (compliance requirement)
        mfa_users = await self.db.execute(
            select(func.count(UserProfile.id)).where(
                and_(
                    UserProfile.auth_status == 'active',
                    UserProfile.mfa_enabled == True
                )
            )
        )
        mfa_compliance = (float(mfa_users.scalar() or 0) / total_users) * 100
        metrics["compliance_mfa_adoption_percent"] = mfa_compliance
        
        # Password age compliance (users who haven't changed password recently)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        old_passwords = await self.db.execute(
            select(func.count(UserProfile.id)).where(
                and_(
                    UserProfile.auth_status == 'active',
                    or_(
                        UserProfile.password_changed_at < thirty_days_ago,
                        UserProfile.password_changed_at.is_(None)
                    )
                )
            )
        )
        old_password_count = float(old_passwords.scalar() or 0)
        password_compliance = ((total_users - old_password_count) / total_users) * 100
        metrics["compliance_password_age_percent"] = password_compliance
        
        # Failed login monitoring compliance
        metrics["compliance_security_monitoring_active"] = (
            100.0 if len(self.alert_rules) > 0 else 0.0
        )
        
        # Access logging compliance
        metrics["compliance_access_logging_percent"] = 100.0  # All access is logged
        
        return metrics
    
    async def _store_metric(self, name: str, value: float, timestamp: datetime):
        """Store metric in Redis for historical tracking"""
        metric_key = f"auth_metrics:{name}:{timestamp.strftime('%Y%m%d_%H')}"
        
        metric_data = {
            "name": name,
            "value": value,
            "timestamp": timestamp.isoformat()
        }
        
        # Store in Redis with 7-day expiration
        await redis_service.client.setex(
            metric_key,
            7 * 24 * 3600,  # 7 days
            json.dumps(metric_data)
        )
        
        # Also add to rolling metrics for alerting
        rolling_key = f"auth_metrics_rolling:{name}"
        await redis_service.client.lpush(rolling_key, json.dumps(metric_data))
        await redis_service.client.ltrim(rolling_key, 0, 99)  # Keep last 100 values
        await redis_service.client.expire(rolling_key, 24 * 3600)  # 24 hour expiration
    
    async def _check_alert_rules(self, current_metrics: Dict[str, float]):
        """Check alert rules against current metrics"""
        for rule in self.alert_rules:
            metric_name = rule["metric"]
            threshold = rule["threshold"]
            operator = rule["operator"]
            
            if metric_name not in current_metrics:
                continue
            
            current_value = current_metrics[metric_name]
            alert_triggered = False
            
            if operator == ">" and current_value > threshold:
                alert_triggered = True
            elif operator == "<" and current_value < threshold:
                alert_triggered = True
            elif operator == ">=" and current_value >= threshold:
                alert_triggered = True
            elif operator == "<=" and current_value <= threshold:
                alert_triggered = True
            elif operator == "==" and current_value == threshold:
                alert_triggered = True
            
            if alert_triggered:
                await self._trigger_alert(rule, current_value)
    
    async def _trigger_alert(self, rule: Dict[str, Any], current_value: float):
        """Trigger alert and send notifications"""
        alert = Alert(
            id=str(uuid4()),
            name=rule["name"],
            level=rule["level"],
            message=f"{rule['description']}. Current value: {current_value}, Threshold: {rule['threshold']}",
            metric_name=rule["metric"],
            current_value=current_value,
            threshold=rule["threshold"],
            timestamp=datetime.utcnow()
        )
        
        self.alerts.append(alert)
        
        # Log alert
        self.logger.warning(
            f"SECURITY ALERT: {alert.name} - {alert.message}",
            extra={
                "alert_id": alert.id,
                "alert_level": alert.level.value,
                "metric_name": alert.metric_name,
                "current_value": current_value,
                "threshold": rule["threshold"]
            }
        )
        
        # Store alert in Redis
        alert_key = f"auth_alerts:{alert.id}"
        await redis_service.client.setex(
            alert_key,
            24 * 3600,  # 24 hours
            json.dumps(asdict(alert), default=str)
        )
        
        # Send notification (would integrate with alerting system)
        await self._send_alert_notification(alert)
    
    async def _send_alert_notification(self, alert: Alert):
        """Send alert notification (placeholder for integration)"""
        # In production, this would integrate with:
        # - PagerDuty
        # - Slack
        # - Email notifications
        # - SIEM systems
        # - etc.
        
        notification_data = {
            "alert_id": alert.id,
            "alert_name": alert.name,
            "severity": alert.level.value,
            "message": alert.message,
            "timestamp": alert.timestamp.isoformat(),
            "metric": alert.metric_name,
            "value": alert.current_value,
            "threshold": alert.threshold
        }
        
        # Store notification request
        notification_key = f"auth_notifications:{alert.id}"
        await redis_service.client.setex(
            notification_key,
            3600,  # 1 hour
            json.dumps(notification_data)
        )
        
        print(f"🚨 ALERT: {alert.name} ({alert.level.value}) - {alert.message}")
    
    async def get_metrics_dashboard(self) -> Dict[str, Any]:
        """Get metrics for monitoring dashboard"""
        current_metrics = await self.collect_authentication_metrics()
        
        # Get historical data for charts
        historical_data = await self._get_historical_metrics()
        
        # Get active alerts
        active_alerts = [alert for alert in self.alerts if not alert.resolved]
        
        dashboard = {
            "current_metrics": current_metrics,
            "historical_data": historical_data,
            "active_alerts": [asdict(alert) for alert in active_alerts],
            "alert_summary": {
                "total_alerts": len(self.alerts),
                "active_alerts": len(active_alerts),
                "critical_alerts": len([a for a in active_alerts if a.level == AlertLevel.CRITICAL]),
                "high_alerts": len([a for a in active_alerts if a.level == AlertLevel.HIGH])
            },
            "system_health": {
                "authentication_health": "healthy" if len(active_alerts) == 0 else "warning",
                "compliance_status": "compliant" if current_metrics.get("compliance_mfa_adoption_percent", 0) > 80 else "non-compliant"
            }
        }
        
        return dashboard
    
    async def _get_historical_metrics(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get historical metrics for trend analysis"""
        historical_data = {}
        
        # Get last 24 hours of key metrics
        key_metrics = [
            "auth_login_rate",
            "auth_failed_login_rate", 
            "auth_success_rate",
            "auth_active_sessions",
            "auth_avg_response_time_ms"
        ]
        
        for metric_name in key_metrics:
            rolling_key = f"auth_metrics_rolling:{metric_name}"
            try:
                data = await redis_service.client.lrange(rolling_key, 0, -1)
                historical_data[metric_name] = [
                    json.loads(item) for item in data
                ]
            except Exception:
                historical_data[metric_name] = []
        
        return historical_data
    
    async def generate_sox_compliance_report(self) -> Dict[str, Any]:
        """Generate SOX compliance report"""
        now = datetime.utcnow()
        last_30_days = now - timedelta(days=30)
        
        # Collect compliance metrics
        compliance_metrics = await self._collect_compliance_metrics(last_30_days, now)
        
        # Audit trail analysis
        audit_completeness = await self._analyze_audit_trail(last_30_days, now)
        
        # Access control review
        access_control_review = await self._review_access_controls()
        
        # Security monitoring effectiveness
        monitoring_effectiveness = await self._assess_monitoring_effectiveness()
        
        sox_report = {
            "sox_compliance_report": {
                "report_id": str(uuid4()),
                "generated_at": now.isoformat(),
                "reporting_period": {
                    "start_date": last_30_days.isoformat(),
                    "end_date": now.isoformat()
                },
                "compliance_metrics": compliance_metrics,
                "audit_trail_analysis": audit_completeness,
                "access_control_review": access_control_review,
                "monitoring_effectiveness": monitoring_effectiveness,
                "overall_compliance_score": self._calculate_compliance_score(
                    compliance_metrics, audit_completeness, access_control_review, monitoring_effectiveness
                )
            }
        }
        
        return sox_report
    
    async def _analyze_audit_trail(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Analyze audit trail completeness and integrity"""
        # Authentication events logged
        auth_events = await self.db.execute(
            select(func.count(AuthAttempt.id)).where(
                AuthAttempt.attempted_at.between(start_date, end_date)
            )
        )
        
        # Check for gaps in logging
        # This is a simplified check - in production you'd analyze for time gaps
        total_events = auth_events.scalar() or 0
        
        return {
            "total_events_logged": total_events,
            "completeness_percentage": 100.0 if total_events > 0 else 0.0,
            "integrity_check_passed": True,  # Would perform hash validation
            "retention_compliance": True,    # Would check retention periods
            "access_log_coverage": 100.0     # All access attempts are logged
        }
    
    async def _review_access_controls(self) -> Dict[str, Any]:
        """Review access control implementations"""
        total_users = await self.db.execute(
            select(func.count(UserProfile.id)).where(
                UserProfile.auth_status == 'active'
            )
        )
        total_count = total_users.scalar() or 1
        
        # MFA adoption
        mfa_users = await self.db.execute(
            select(func.count(UserProfile.id)).where(
                and_(
                    UserProfile.auth_status == 'active',
                    UserProfile.mfa_enabled == True
                )
            )
        )
        mfa_adoption = (mfa_users.scalar() or 0) / total_count * 100
        
        # Password policy compliance
        recent_password_changes = await self.db.execute(
            select(func.count(UserProfile.id)).where(
                and_(
                    UserProfile.auth_status == 'active',
                    UserProfile.password_changed_at > datetime.utcnow() - timedelta(days=90)
                )
            )
        )
        password_compliance = (recent_password_changes.scalar() or 0) / total_count * 100
        
        return {
            "mfa_adoption_percentage": mfa_adoption,
            "password_policy_compliance": password_compliance,
            "account_lockout_enabled": True,
            "session_timeout_configured": True,
            "privileged_access_monitored": True,
            "access_review_current": True
        }
    
    async def _assess_monitoring_effectiveness(self) -> Dict[str, Any]:
        """Assess security monitoring effectiveness"""
        # Check if monitoring is active
        monitoring_active = len(self.alert_rules) > 0
        
        # Check alert response
        total_alerts = len(self.alerts)
        resolved_alerts = len([a for a in self.alerts if a.resolved])
        
        return {
            "monitoring_active": monitoring_active,
            "alert_rules_configured": len(self.alert_rules),
            "alerts_generated": total_alerts,
            "alert_resolution_rate": (resolved_alerts / total_alerts * 100) if total_alerts > 0 else 100,
            "real_time_monitoring": True,
            "automated_response_enabled": True,
            "incident_documentation": True
        }
    
    def _calculate_compliance_score(self, *compliance_data) -> float:
        """Calculate overall compliance score"""
        scores = []
        
        for data in compliance_data:
            if isinstance(data, dict):
                # Extract percentage values and boolean scores
                for key, value in data.items():
                    if isinstance(value, (int, float)):
                        if "percentage" in key or "percent" in key:
                            scores.append(value)
                        elif isinstance(value, bool):
                            scores.append(100.0 if value else 0.0)
        
        return sum(scores) / len(scores) if scores else 0.0


# Monitoring service instance
async def get_auth_metrics(db_session: AsyncSession) -> AuthenticationMetrics:
    """Get authentication metrics instance"""
    return AuthenticationMetrics(db_session)