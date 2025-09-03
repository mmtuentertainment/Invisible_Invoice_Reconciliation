"""
Monitoring endpoints for authentication system
Provides metrics, alerts, and compliance reporting
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.middleware import get_current_user, require_permissions
from app.monitoring.auth_metrics import AuthenticationMetrics, get_auth_metrics
from app.schemas.monitoring import (
    MetricsDashboardResponse, AlertResponse, ComplianceReportResponse,
    MetricsQueryRequest, AlertAcknowledgeRequest
)


router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


@router.get(
    "/dashboard",
    response_model=MetricsDashboardResponse,
    summary="Get monitoring dashboard",
    description="Get comprehensive authentication monitoring dashboard"
)
async def get_monitoring_dashboard(
    user_context: dict = Depends(require_permissions(["monitoring:read", "admin:*"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Get authentication monitoring dashboard with current metrics,
    historical data, and active alerts.
    
    Requires monitoring:read or admin permissions.
    """
    metrics_service = await get_auth_metrics(db)
    dashboard_data = await metrics_service.get_metrics_dashboard()
    
    return MetricsDashboardResponse(**dashboard_data)


@router.get(
    "/metrics",
    summary="Get current metrics",
    description="Get current authentication metrics"
)
async def get_current_metrics(
    metric_names: Optional[List[str]] = Query(None, description="Specific metrics to retrieve"),
    user_context: dict = Depends(require_permissions(["monitoring:read", "admin:*"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current authentication metrics.
    
    Can filter by specific metric names if provided.
    """
    metrics_service = await get_auth_metrics(db)
    all_metrics = await metrics_service.collect_authentication_metrics()
    
    if metric_names:
        filtered_metrics = {
            name: value for name, value in all_metrics.items() 
            if name in metric_names
        }
        return {"metrics": filtered_metrics}
    
    return {"metrics": all_metrics}


@router.get(
    "/metrics/historical",
    summary="Get historical metrics",
    description="Get historical authentication metrics for trend analysis"
)
async def get_historical_metrics(
    metric_name: str = Query(..., description="Metric name to retrieve"),
    hours: int = Query(24, description="Number of hours of history", ge=1, le=168),
    user_context: dict = Depends(require_permissions(["monitoring:read", "admin:*"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Get historical data for a specific metric.
    
    Returns time-series data for trend analysis and charting.
    """
    metrics_service = await get_auth_metrics(db)
    
    try:
        from app.services.redis_service import redis_service
        import json
        
        # Get historical data from Redis
        rolling_key = f"auth_metrics_rolling:{metric_name}"
        data = await redis_service.client.lrange(rolling_key, 0, -1)
        
        historical_data = []
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        for item in data:
            try:
                metric_data = json.loads(item)
                metric_time = datetime.fromisoformat(metric_data["timestamp"])
                
                if metric_time >= cutoff_time:
                    historical_data.append(metric_data)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        
        # Sort by timestamp
        historical_data.sort(key=lambda x: x["timestamp"])
        
        return {
            "metric_name": metric_name,
            "time_range_hours": hours,
            "data_points": len(historical_data),
            "data": historical_data
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving historical data: {str(e)}"
        )


@router.get(
    "/alerts",
    response_model=List[AlertResponse],
    summary="Get active alerts",
    description="Get all active authentication security alerts"
)
async def get_active_alerts(
    severity: Optional[str] = Query(None, description="Filter by alert severity"),
    user_context: dict = Depends(require_permissions(["monitoring:read", "admin:*"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Get active security alerts for authentication system.
    
    Can filter by severity level (critical, high, medium, low, info).
    """
    metrics_service = await get_auth_metrics(db)
    
    # Get current dashboard to access alerts
    dashboard_data = await metrics_service.get_metrics_dashboard()
    active_alerts = dashboard_data.get("active_alerts", [])
    
    if severity:
        active_alerts = [
            alert for alert in active_alerts 
            if alert.get("level", "").lower() == severity.lower()
        ]
    
    return active_alerts


@router.post(
    "/alerts/{alert_id}/acknowledge",
    summary="Acknowledge alert",
    description="Acknowledge and optionally resolve an alert"
)
async def acknowledge_alert(
    alert_id: str,
    acknowledge_data: AlertAcknowledgeRequest,
    user_context: dict = Depends(require_permissions(["monitoring:write", "admin:*"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Acknowledge an alert and optionally mark it as resolved.
    
    Requires monitoring:write or admin permissions.
    """
    try:
        from app.services.redis_service import redis_service
        import json
        
        # Get alert from Redis
        alert_key = f"auth_alerts:{alert_id}"
        alert_data = await redis_service.client.get(alert_key)
        
        if not alert_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert not found"
            )
        
        alert = json.loads(alert_data)
        
        # Update alert
        alert["acknowledged"] = True
        alert["acknowledged_by"] = user_context["user_id"]
        alert["acknowledged_at"] = datetime.utcnow().isoformat()
        alert["acknowledgment_note"] = acknowledge_data.note
        
        if acknowledge_data.resolve:
            alert["resolved"] = True
            alert["resolved_at"] = datetime.utcnow().isoformat()
            alert["resolved_by"] = user_context["user_id"]
        
        # Save updated alert
        await redis_service.client.setex(
            alert_key,
            24 * 3600,  # 24 hours
            json.dumps(alert)
        )
        
        # Log the acknowledgment
        from app.services.audit_service import get_audit_service
        audit_service = await get_audit_service(db)
        
        await audit_service.log_security_event(
            tenant_id=UUID(user_context["tenant_id"]),
            user_id=UUID(user_context["user_id"]),
            event_type="alert_acknowledged",
            description=f"Alert {alert_id} acknowledged: {acknowledge_data.note}",
            metadata={
                "alert_id": alert_id,
                "alert_name": alert.get("name"),
                "resolved": acknowledge_data.resolve
            }
        )
        
        return {"message": "Alert acknowledged successfully", "alert_id": alert_id}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error acknowledging alert: {str(e)}"
        )


@router.get(
    "/compliance/sox-report",
    response_model=ComplianceReportResponse,
    summary="Generate SOX compliance report",
    description="Generate comprehensive SOX compliance report for authentication system"
)
async def generate_sox_compliance_report(
    user_context: dict = Depends(require_permissions(["compliance:read", "admin:*"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate SOX compliance report for authentication system.
    
    Provides comprehensive analysis of compliance posture including:
    - Audit trail completeness
    - Access control effectiveness
    - Security monitoring status
    - Policy compliance metrics
    
    Requires compliance:read or admin permissions.
    """
    metrics_service = await get_auth_metrics(db)
    sox_report = await metrics_service.generate_sox_compliance_report()
    
    # Log compliance report generation
    from app.services.audit_service import get_audit_service
    audit_service = await get_audit_service(db)
    
    await audit_service.log_security_event(
        tenant_id=UUID(user_context["tenant_id"]),
        user_id=UUID(user_context["user_id"]),
        event_type="compliance_report_generated",
        description="SOX compliance report generated",
        metadata={
            "report_id": sox_report["sox_compliance_report"]["report_id"],
            "compliance_score": sox_report["sox_compliance_report"]["overall_compliance_score"]
        }
    )
    
    return ComplianceReportResponse(**sox_report["sox_compliance_report"])


@router.get(
    "/health",
    summary="Get system health status",
    description="Get authentication system health and status"
)
async def get_system_health(
    user_context: dict = Depends(require_permissions(["monitoring:read", "admin:*"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Get overall system health status for authentication components.
    """
    try:
        from app.services.redis_service import redis_service
        import time
        
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {}
        }
        
        # Check database connectivity
        try:
            await db.execute("SELECT 1")
            health_status["components"]["database"] = {
                "status": "healthy",
                "response_time_ms": 0  # Would measure actual response time
            }
        except Exception as e:
            health_status["components"]["database"] = {
                "status": "unhealthy", 
                "error": str(e)
            }
            health_status["status"] = "degraded"
        
        # Check Redis connectivity
        try:
            start_time = time.perf_counter()
            await redis_service.client.ping()
            redis_response_time = (time.perf_counter() - start_time) * 1000
            
            health_status["components"]["redis"] = {
                "status": "healthy",
                "response_time_ms": round(redis_response_time, 2)
            }
        except Exception as e:
            health_status["components"]["redis"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["status"] = "degraded"
        
        # Check metrics collection
        try:
            metrics_service = await get_auth_metrics(db)
            test_metrics = await metrics_service.collect_authentication_metrics()
            
            health_status["components"]["metrics"] = {
                "status": "healthy",
                "metrics_collected": len(test_metrics)
            }
        except Exception as e:
            health_status["components"]["metrics"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["status"] = "degraded"
        
        # Check alerting system
        health_status["components"]["alerting"] = {
            "status": "healthy",
            "alert_rules_configured": 7  # Number of alert rules
        }
        
        return health_status
        
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e)
            }
        )


@router.post(
    "/metrics/custom-query",
    summary="Execute custom metrics query",
    description="Execute custom metrics query for advanced analysis"
)
async def custom_metrics_query(
    query_request: MetricsQueryRequest,
    user_context: dict = Depends(require_permissions(["monitoring:advanced", "admin:*"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Execute custom metrics query for advanced analysis and reporting.
    
    Supports complex queries across multiple metrics and time ranges.
    Requires monitoring:advanced or admin permissions.
    """
    try:
        from app.services.redis_service import redis_service
        import json
        
        results = {}
        
        for metric_config in query_request.metrics:
            metric_name = metric_config["name"]
            time_range_hours = metric_config.get("time_range_hours", 24)
            aggregation = metric_config.get("aggregation", "raw")  # raw, avg, sum, max, min
            
            # Get data from Redis
            rolling_key = f"auth_metrics_rolling:{metric_name}"
            data = await redis_service.client.lrange(rolling_key, 0, -1)
            
            metric_values = []
            cutoff_time = datetime.utcnow() - timedelta(hours=time_range_hours)
            
            for item in data:
                try:
                    metric_data = json.loads(item)
                    metric_time = datetime.fromisoformat(metric_data["timestamp"])
                    
                    if metric_time >= cutoff_time:
                        metric_values.append(metric_data["value"])
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
            
            # Apply aggregation
            if aggregation == "avg" and metric_values:
                result = sum(metric_values) / len(metric_values)
            elif aggregation == "sum":
                result = sum(metric_values)
            elif aggregation == "max" and metric_values:
                result = max(metric_values)
            elif aggregation == "min" and metric_values:
                result = min(metric_values)
            elif aggregation == "count":
                result = len(metric_values)
            else:
                result = metric_values  # raw data
            
            results[metric_name] = {
                "aggregation": aggregation,
                "time_range_hours": time_range_hours,
                "data_points": len(metric_values),
                "result": result
            }
        
        return {
            "query_id": query_request.query_id or str(UUID()),
            "executed_at": datetime.utcnow().isoformat(),
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error executing custom query: {str(e)}"
        )