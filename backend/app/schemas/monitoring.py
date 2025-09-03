"""
Pydantic schemas for monitoring and metrics API
"""

from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from uuid import UUID
from pydantic import BaseModel, Field


class MetricResponse(BaseModel):
    """Individual metric response"""
    name: str
    value: float
    timestamp: datetime
    description: Optional[str] = None


class HistoricalDataPoint(BaseModel):
    """Historical data point"""
    timestamp: datetime
    value: float


class AlertResponse(BaseModel):
    """Security alert response"""
    id: str
    name: str
    level: str  # critical, high, medium, low, info
    message: str
    metric_name: str
    current_value: float
    threshold: float
    timestamp: datetime
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    acknowledged: Optional[bool] = None
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    acknowledgment_note: Optional[str] = None


class AlertSummaryResponse(BaseModel):
    """Alert summary statistics"""
    total_alerts: int
    active_alerts: int
    critical_alerts: int
    high_alerts: int
    medium_alerts: int
    low_alerts: int


class SystemHealthResponse(BaseModel):
    """System health status"""
    authentication_health: str
    compliance_status: str
    database_status: Optional[str] = None
    redis_status: Optional[str] = None
    metrics_status: Optional[str] = None


class MetricsDashboardResponse(BaseModel):
    """Comprehensive metrics dashboard response"""
    current_metrics: Dict[str, float]
    historical_data: Dict[str, List[Dict[str, Any]]]
    active_alerts: List[AlertResponse]
    alert_summary: AlertSummaryResponse
    system_health: SystemHealthResponse
    
    class Config:
        from_attributes = True


class MetricsQueryRequest(BaseModel):
    """Custom metrics query request"""
    query_id: Optional[str] = None
    metrics: List[Dict[str, Any]] = Field(
        ...,
        description="List of metrics to query with configurations",
        example=[
            {
                "name": "auth_login_rate",
                "time_range_hours": 24,
                "aggregation": "avg"
            }
        ]
    )
    filters: Optional[Dict[str, Any]] = None


class AlertAcknowledgeRequest(BaseModel):
    """Alert acknowledgment request"""
    note: str = Field(..., description="Acknowledgment note")
    resolve: bool = Field(False, description="Whether to resolve the alert")


class ComplianceMetrics(BaseModel):
    """SOX compliance metrics"""
    audit_trail_completeness: float
    mfa_adoption_percent: float
    password_age_percent: float
    security_monitoring_active: float
    access_logging_percent: float


class AuditTrailAnalysis(BaseModel):
    """Audit trail analysis results"""
    total_events_logged: int
    completeness_percentage: float
    integrity_check_passed: bool
    retention_compliance: bool
    access_log_coverage: float


class AccessControlReview(BaseModel):
    """Access control review results"""
    mfa_adoption_percentage: float
    password_policy_compliance: float
    account_lockout_enabled: bool
    session_timeout_configured: bool
    privileged_access_monitored: bool
    access_review_current: bool


class MonitoringEffectiveness(BaseModel):
    """Security monitoring effectiveness assessment"""
    monitoring_active: bool
    alert_rules_configured: int
    alerts_generated: int
    alert_resolution_rate: float
    real_time_monitoring: bool
    automated_response_enabled: bool
    incident_documentation: bool


class ComplianceReportResponse(BaseModel):
    """SOX compliance report response"""
    report_id: str
    generated_at: datetime
    reporting_period: Dict[str, datetime]
    compliance_metrics: ComplianceMetrics
    audit_trail_analysis: AuditTrailAnalysis
    access_control_review: AccessControlReview
    monitoring_effectiveness: MonitoringEffectiveness
    overall_compliance_score: float
    
    class Config:
        from_attributes = True


class SecurityEventMetrics(BaseModel):
    """Security event metrics"""
    failed_login_attempts: int
    account_lockouts: int
    suspicious_activities: int
    mfa_bypass_attempts: int
    session_hijack_attempts: int
    password_reset_requests: int


class PerformanceMetrics(BaseModel):
    """Authentication performance metrics"""
    avg_response_time_ms: float
    database_query_time_ms: float
    redis_latency_ms: float
    throughput_requests_per_second: float
    error_rate_percent: float


class SessionMetrics(BaseModel):
    """Session management metrics"""
    active_sessions: int
    avg_session_duration_minutes: float
    concurrent_session_violations: int
    session_timeouts: int
    forced_logouts: int


class AuthenticationMetricsResponse(BaseModel):
    """Comprehensive authentication metrics"""
    timestamp: datetime
    login_metrics: Dict[str, float]
    security_metrics: SecurityEventMetrics
    performance_metrics: PerformanceMetrics
    session_metrics: SessionMetrics
    compliance_metrics: ComplianceMetrics


class MetricTrendResponse(BaseModel):
    """Metric trend analysis response"""
    metric_name: str
    time_range_hours: int
    data_points: int
    trend_direction: str  # increasing, decreasing, stable
    trend_percentage: float
    data: List[HistoricalDataPoint]


class AlertRuleRequest(BaseModel):
    """Request to create or update alert rule"""
    name: str
    metric_name: str
    threshold: float
    operator: str  # >, <, >=, <=, ==
    level: str  # critical, high, medium, low, info
    description: str
    enabled: bool = True


class AlertRuleResponse(BaseModel):
    """Alert rule response"""
    id: str
    name: str
    metric_name: str
    threshold: float
    operator: str
    level: str
    description: str
    enabled: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class MonitoringConfigRequest(BaseModel):
    """Monitoring configuration request"""
    alert_rules: List[AlertRuleRequest]
    metric_retention_hours: int = Field(168, description="Hours to retain metrics")
    alert_retention_hours: int = Field(720, description="Hours to retain alerts")
    notification_settings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Notification configuration"
    )


class MonitoringConfigResponse(BaseModel):
    """Monitoring configuration response"""
    config_id: str
    alert_rules_count: int
    metric_retention_hours: int
    alert_retention_hours: int
    notification_settings: Dict[str, Any]
    last_updated: datetime


class SecurityPostureResponse(BaseModel):
    """Security posture assessment"""
    overall_score: float = Field(..., description="Overall security score (0-100)")
    risk_level: str = Field(..., description="Overall risk level")
    active_threats: int
    vulnerabilities: int
    compliance_status: str
    recommendations: List[str]
    last_assessment: datetime


class ThreatDetectionResponse(BaseModel):
    """Threat detection status"""
    active_monitoring: bool
    detection_rules: int
    threats_detected_24h: int
    false_positive_rate: float
    mean_time_to_detection: float  # minutes
    mean_time_to_response: float   # minutes


class IncidentResponse(BaseModel):
    """Security incident response"""
    incident_id: str
    incident_type: str
    severity: str
    status: str  # open, investigating, resolved, closed
    created_at: datetime
    updated_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    description: str
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    remediation_steps: List[str] = Field(default_factory=list)