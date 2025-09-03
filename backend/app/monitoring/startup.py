"""
Production monitoring startup and initialization
Sets up monitoring, alerting, and compliance tracking
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any

from app.core.config import settings
from app.core.database import get_db
from app.monitoring.auth_metrics import AuthenticationMetrics
from app.services.redis_service import redis_service


class MonitoringService:
    """Production monitoring service"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.metrics_collection_interval = 300  # 5 minutes
        self.alert_check_interval = 60  # 1 minute
        self.compliance_check_interval = 3600  # 1 hour
    
    async def start(self):
        """Start monitoring service"""
        if self.running:
            return
        
        self.logger.info("Starting authentication monitoring service...")
        self.running = True
        
        # Initialize monitoring components
        await self._initialize_monitoring()
        
        # Start background tasks
        tasks = [
            asyncio.create_task(self._metrics_collection_loop()),
            asyncio.create_task(self._alert_monitoring_loop()),
            asyncio.create_task(self._compliance_monitoring_loop()),
            asyncio.create_task(self._health_check_loop())
        ]
        
        self.logger.info("Authentication monitoring service started successfully")
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self.logger.info("Monitoring service cancelled")
        except Exception as e:
            self.logger.error(f"Monitoring service error: {str(e)}")
        finally:
            self.running = False
    
    async def stop(self):
        """Stop monitoring service"""
        self.logger.info("Stopping authentication monitoring service...")
        self.running = False
        
        # Cancel background tasks
        for task in asyncio.all_tasks():
            if not task.done():
                task.cancel()
        
        self.logger.info("Authentication monitoring service stopped")
    
    async def _initialize_monitoring(self):
        """Initialize monitoring components"""
        try:
            # Test Redis connectivity
            await redis_service.client.ping()
            self.logger.info("Redis connection established for monitoring")
            
            # Initialize metrics storage
            await self._initialize_metrics_storage()
            
            # Set up alert rules
            await self._setup_default_alert_rules()
            
            # Initialize compliance tracking
            await self._initialize_compliance_tracking()
            
        except Exception as e:
            self.logger.error(f"Failed to initialize monitoring: {str(e)}")
            raise
    
    async def _initialize_metrics_storage(self):
        """Initialize metrics storage in Redis"""
        try:
            # Create metrics metadata
            metadata = {
                "initialized_at": datetime.utcnow().isoformat(),
                "version": "1.0.0",
                "retention_hours": 168,  # 7 days
                "collection_interval_seconds": self.metrics_collection_interval
            }
            
            await redis_service.client.setex(
                "auth_monitoring:metadata",
                7 * 24 * 3600,  # 7 days
                str(metadata)
            )
            
            self.logger.info("Metrics storage initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize metrics storage: {str(e)}")
            raise
    
    async def _setup_default_alert_rules(self):
        """Setup default alert rules"""
        try:
            default_rules = [
                {
                    "name": "Critical Authentication Failure Rate",
                    "metric": "auth_failed_login_rate",
                    "threshold": 20.0,
                    "operator": ">",
                    "severity": "critical"
                },
                {
                    "name": "Account Lockout Spike",
                    "metric": "auth_account_lockouts",
                    "threshold": 10.0,
                    "operator": ">",
                    "severity": "high"
                },
                {
                    "name": "High Response Time",
                    "metric": "auth_avg_response_time_ms",
                    "threshold": 2000.0,
                    "operator": ">",
                    "severity": "medium"
                }
            ]
            
            for rule in default_rules:
                rule_key = f"auth_alert_rules:{rule['name']}"
                await redis_service.client.setex(
                    rule_key,
                    30 * 24 * 3600,  # 30 days
                    str(rule)
                )
            
            self.logger.info(f"Initialized {len(default_rules)} default alert rules")
            
        except Exception as e:
            self.logger.error(f"Failed to setup alert rules: {str(e)}")
    
    async def _initialize_compliance_tracking(self):
        """Initialize SOX compliance tracking"""
        try:
            compliance_config = {
                "sox_compliance_enabled": True,
                "audit_retention_days": 2555,  # 7 years for SOX
                "compliance_check_interval_hours": 1,
                "required_mfa_adoption_percent": 90.0,
                "required_password_policy_compliance": 95.0,
                "audit_trail_completeness_threshold": 99.5
            }
            
            await redis_service.client.setex(
                "auth_compliance:config",
                30 * 24 * 3600,  # 30 days
                str(compliance_config)
            )
            
            self.logger.info("SOX compliance tracking initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize compliance tracking: {str(e)}")
    
    async def _metrics_collection_loop(self):
        """Background metrics collection loop"""
        while self.running:
            try:
                # Get database session
                async for db_session in get_db():
                    metrics_service = AuthenticationMetrics(db_session)
                    
                    # Collect metrics
                    current_metrics = await metrics_service.collect_authentication_metrics()
                    
                    # Log key metrics
                    self.logger.info(
                        f"Metrics collected - "
                        f"Login rate: {current_metrics.get('auth_login_rate', 0):.1f}/hr, "
                        f"Success rate: {current_metrics.get('auth_success_rate', 0):.1f}%, "
                        f"Active sessions: {current_metrics.get('auth_active_sessions', 0)}"
                    )
                    
                    break  # Exit the async generator
                
                # Wait for next collection
                await asyncio.sleep(self.metrics_collection_interval)
                
            except Exception as e:
                self.logger.error(f"Error in metrics collection: {str(e)}")
                await asyncio.sleep(60)  # Wait 1 minute on error
    
    async def _alert_monitoring_loop(self):
        """Background alert monitoring loop"""
        while self.running:
            try:
                async for db_session in get_db():
                    metrics_service = AuthenticationMetrics(db_session)
                    
                    # Check for alerts
                    dashboard_data = await metrics_service.get_metrics_dashboard()
                    active_alerts = dashboard_data.get("active_alerts", [])
                    
                    if active_alerts:
                        critical_alerts = [
                            alert for alert in active_alerts 
                            if alert.get("level") == "critical"
                        ]
                        
                        if critical_alerts:
                            self.logger.critical(
                                f"CRITICAL SECURITY ALERT: {len(critical_alerts)} critical alerts active"
                            )
                        
                        self.logger.warning(f"Security alerts active: {len(active_alerts)}")
                    
                    break
                
                await asyncio.sleep(self.alert_check_interval)
                
            except Exception as e:
                self.logger.error(f"Error in alert monitoring: {str(e)}")
                await asyncio.sleep(60)
    
    async def _compliance_monitoring_loop(self):
        """Background compliance monitoring loop"""
        while self.running:
            try:
                async for db_session in get_db():
                    metrics_service = AuthenticationMetrics(db_session)
                    
                    # Generate compliance report
                    sox_report = await metrics_service.generate_sox_compliance_report()
                    compliance_score = sox_report["sox_compliance_report"]["overall_compliance_score"]
                    
                    # Check compliance thresholds
                    if compliance_score < 80.0:
                        self.logger.error(
                            f"SOX COMPLIANCE ALERT: Compliance score {compliance_score:.1f}% below threshold"
                        )
                    elif compliance_score < 90.0:
                        self.logger.warning(
                            f"SOX compliance warning: Score {compliance_score:.1f}% needs attention"
                        )
                    else:
                        self.logger.info(f"SOX compliance score: {compliance_score:.1f}%")
                    
                    break
                
                await asyncio.sleep(self.compliance_check_interval)
                
            except Exception as e:
                self.logger.error(f"Error in compliance monitoring: {str(e)}")
                await asyncio.sleep(300)  # Wait 5 minutes on error
    
    async def _health_check_loop(self):
        """Background health check loop"""
        while self.running:
            try:
                # Check system health
                health_status = await self._perform_health_check()
                
                if health_status["status"] != "healthy":
                    self.logger.warning(f"System health degraded: {health_status}")
                
                await asyncio.sleep(300)  # Every 5 minutes
                
            except Exception as e:
                self.logger.error(f"Error in health check: {str(e)}")
                await asyncio.sleep(300)
    
    async def _perform_health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {}
        }
        
        try:
            # Check Redis
            await redis_service.client.ping()
            health_status["components"]["redis"] = "healthy"
        except Exception:
            health_status["components"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"
        
        try:
            # Check database
            async for db_session in get_db():
                await db_session.execute("SELECT 1")
                health_status["components"]["database"] = "healthy"
                break
        except Exception:
            health_status["components"]["database"] = "unhealthy"
            health_status["status"] = "degraded"
        
        return health_status


# Global monitoring service instance
monitoring_service = MonitoringService()


async def start_monitoring():
    """Start the monitoring service"""
    if settings.is_production:
        await monitoring_service.start()
    else:
        logging.info("Monitoring service disabled in non-production environment")


async def stop_monitoring():
    """Stop the monitoring service"""
    await monitoring_service.stop()


# Startup event handler
async def on_startup():
    """FastAPI startup event handler"""
    logging.info("Initializing authentication monitoring...")
    
    # Start monitoring in background
    if settings.is_production or settings.ENABLE_METRICS:
        asyncio.create_task(start_monitoring())
    
    logging.info("Authentication monitoring initialized")


# Shutdown event handler  
async def on_shutdown():
    """FastAPI shutdown event handler"""
    logging.info("Shutting down authentication monitoring...")
    await stop_monitoring()
    logging.info("Authentication monitoring shutdown complete")