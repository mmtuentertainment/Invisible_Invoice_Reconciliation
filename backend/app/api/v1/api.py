"""
FastAPI v1 API router configuration.

Includes all API endpoints for the invoice reconciliation platform,
with a focus on the automated matching engine endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, monitoring, matching, invoice_upload, websocket

api_router = APIRouter()

# Authentication endpoints
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Monitoring and health endpoints
api_router.include_router(monitoring.router, prefix="/monitoring", tags=["Monitoring"])

# Automated matching engine endpoints
api_router.include_router(matching.router, prefix="/matching", tags=["Matching"])

# Invoice upload endpoints
api_router.include_router(invoice_upload.router, prefix="/invoices/upload", tags=["Invoice Upload"])

# WebSocket endpoints
api_router.include_router(websocket.router, prefix="/ws", tags=["WebSocket"])