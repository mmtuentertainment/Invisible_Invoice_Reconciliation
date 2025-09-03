"""
WebSocket endpoints for real-time communication.

Provides WebSocket connections for:
- Import progress tracking
- Status updates
- Error notifications
- System notifications
"""

import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.security import HTTPBearer

from app.api.deps import get_current_user_websocket, get_tenant_id_websocket
from app.models.auth import User
from app.services.websocket_service import connection_manager, handle_websocket_message

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/{tenant_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    tenant_id: UUID,
    token: Optional[str] = None
):
    """
    WebSocket endpoint for real-time communication.
    
    Supports authentication via query parameter token.
    Handles subscription management for import progress updates.
    
    Message types:
    - subscribe_import: Subscribe to import progress updates
    - unsubscribe_import: Unsubscribe from import updates  
    - get_progress: Get current progress for an import
    - ping: Heartbeat message
    
    Response types:
    - connection_established: Confirmation of connection
    - subscription_confirmed: Confirmation of subscription
    - import_progress: Progress update data
    - import_status_change: Status change notification
    - import_error: Error notification
    - pong: Response to ping
    - error: Error message
    """
    user: Optional[User] = None
    
    try:
        # Authenticate user if token provided
        if token:
            user = await get_current_user_websocket(token)
            # Verify tenant access
            user_tenant_id = await get_tenant_id_websocket(user)
            if user_tenant_id != tenant_id:
                await websocket.close(code=4003, reason="Forbidden: Invalid tenant")
                return
        else:
            # For now, allow unauthenticated connections for development
            # In production, this should require authentication
            if not settings.DEBUG:
                await websocket.close(code=4001, reason="Authentication required")
                return
            # Create a mock user for unauthenticated connections
            from uuid import uuid4
            class MockUser:
                id = uuid4()
            user = MockUser()
        
        # Accept connection
        await connection_manager.connect(websocket, tenant_id, user.id)
        
        try:
            while True:
                # Wait for message
                data = await websocket.receive_text()
                
                try:
                    message_data = json.loads(data)
                    await handle_websocket_message(websocket, tenant_id, user.id, message_data)
                    
                except json.JSONDecodeError:
                    await connection_manager.send_personal_message(
                        websocket,
                        {
                            "type": "error",
                            "message": "Invalid JSON format",
                            "timestamp": "now"
                        }
                    )
                except Exception as e:
                    logger.error(f"Error processing WebSocket message: {e}")
                    await connection_manager.send_personal_message(
                        websocket,
                        {
                            "type": "error", 
                            "message": "Error processing message",
                            "timestamp": "now"
                        }
                    )
                
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: tenant={tenant_id}, user={user.id if user else 'unknown'}")
            
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        try:
            await websocket.close(code=4000, reason="Internal server error")
        except:
            pass  # Connection might already be closed
            
    finally:
        # Clean up connection
        if user:
            connection_manager.disconnect(tenant_id, user.id)


@router.get("/ws/stats")
async def get_websocket_stats(
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Get WebSocket connection statistics.
    
    Returns information about active connections, subscriptions, and usage.
    Requires authentication.
    """
    try:
        stats = await connection_manager.get_connection_stats()
        return {
            "status": "success",
            "data": stats
        }
        
    except Exception as e:
        logger.error(f"Error getting WebSocket stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get WebSocket statistics"
        )