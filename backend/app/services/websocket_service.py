"""
WebSocket service for real-time progress tracking and notifications.

This module provides WebSocket functionality for:
- Real-time import progress updates
- Status change notifications
- Error reporting updates
- Connection management per tenant
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set, Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.redis_service import RedisService

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        # Active connections: tenant_id -> {user_id -> {websocket, subscriptions}}
        self.active_connections: Dict[UUID, Dict[UUID, Dict[str, Any]]] = {}
        # Import subscriptions: batch_id -> set of (tenant_id, user_id) pairs
        self.import_subscriptions: Dict[UUID, Set[tuple]] = {}
        self.redis_service = RedisService()
    
    async def connect(self, websocket: WebSocket, tenant_id: UUID, user_id: UUID):
        """Accept a WebSocket connection and register it."""
        await websocket.accept()
        
        # Initialize tenant connections if needed
        if tenant_id not in self.active_connections:
            self.active_connections[tenant_id] = {}
        
        # Store connection info
        self.active_connections[tenant_id][user_id] = {
            "websocket": websocket,
            "subscriptions": set(),
            "connected_at": datetime.utcnow()
        }
        
        logger.info(f"WebSocket connected: tenant={tenant_id}, user={user_id}")
        
        # Send initial connection confirmation
        await self.send_personal_message(
            websocket,
            {
                "type": "connection_established",
                "timestamp": datetime.utcnow().isoformat(),
                "message": "WebSocket connection established"
            }
        )
    
    def disconnect(self, tenant_id: UUID, user_id: UUID):
        """Disconnect and clean up a WebSocket connection."""
        try:
            if tenant_id in self.active_connections:
                if user_id in self.active_connections[tenant_id]:
                    # Get subscriptions before removing connection
                    connection_info = self.active_connections[tenant_id][user_id]
                    subscriptions = connection_info.get("subscriptions", set())
                    
                    # Remove from import subscriptions
                    for batch_id in subscriptions:
                        if batch_id in self.import_subscriptions:
                            self.import_subscriptions[batch_id].discard((tenant_id, user_id))
                            if not self.import_subscriptions[batch_id]:
                                del self.import_subscriptions[batch_id]
                    
                    # Remove connection
                    del self.active_connections[tenant_id][user_id]
                    
                    # Clean up empty tenant dict
                    if not self.active_connections[tenant_id]:
                        del self.active_connections[tenant_id]
                    
                    logger.info(f"WebSocket disconnected: tenant={tenant_id}, user={user_id}")
        
        except Exception as e:
            logger.error(f"Error during WebSocket disconnect: {e}")
    
    async def send_personal_message(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send a message to a specific WebSocket."""
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception as e:
            logger.error(f"Error sending WebSocket message: {e}")
    
    async def subscribe_to_import(self, tenant_id: UUID, user_id: UUID, batch_id: UUID):
        """Subscribe a user to import progress updates."""
        if tenant_id in self.active_connections and user_id in self.active_connections[tenant_id]:
            # Add to subscriptions
            self.active_connections[tenant_id][user_id]["subscriptions"].add(batch_id)
            
            # Track import subscriptions
            if batch_id not in self.import_subscriptions:
                self.import_subscriptions[batch_id] = set()
            self.import_subscriptions[batch_id].add((tenant_id, user_id))
            
            logger.info(f"User {user_id} subscribed to import {batch_id}")
            
            # Send confirmation
            websocket = self.active_connections[tenant_id][user_id]["websocket"]
            await self.send_personal_message(
                websocket,
                {
                    "type": "subscription_confirmed",
                    "batch_id": str(batch_id),
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
    
    async def unsubscribe_from_import(self, tenant_id: UUID, user_id: UUID, batch_id: UUID):
        """Unsubscribe a user from import progress updates."""
        if tenant_id in self.active_connections and user_id in self.active_connections[tenant_id]:
            # Remove from subscriptions
            self.active_connections[tenant_id][user_id]["subscriptions"].discard(batch_id)
            
            # Remove from import subscriptions
            if batch_id in self.import_subscriptions:
                self.import_subscriptions[batch_id].discard((tenant_id, user_id))
                if not self.import_subscriptions[batch_id]:
                    del self.import_subscriptions[batch_id]
            
            logger.info(f"User {user_id} unsubscribed from import {batch_id}")
    
    async def broadcast_import_progress(self, batch_id: UUID, progress_data: Dict[str, Any]):
        """Broadcast import progress to all subscribed users."""
        if batch_id not in self.import_subscriptions:
            return
        
        message = {
            "type": "import_progress",
            "batch_id": str(batch_id),
            "data": progress_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Get all subscribed connections
        subscribed_connections = []
        for tenant_id, user_id in self.import_subscriptions[batch_id]:
            if (tenant_id in self.active_connections and 
                user_id in self.active_connections[tenant_id]):
                websocket = self.active_connections[tenant_id][user_id]["websocket"]
                subscribed_connections.append(websocket)
        
        # Send to all subscribed connections
        if subscribed_connections:
            await self._broadcast_to_connections(subscribed_connections, message)
    
    async def broadcast_import_status_change(self, batch_id: UUID, status: str, 
                                           tenant_id: UUID, additional_data: Optional[Dict[str, Any]] = None):
        """Broadcast import status changes to subscribed users."""
        if batch_id not in self.import_subscriptions:
            return
        
        message = {
            "type": "import_status_change",
            "batch_id": str(batch_id),
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if additional_data:
            message["data"] = additional_data
        
        # Get subscribed connections for this tenant
        subscribed_connections = []
        for sub_tenant_id, user_id in self.import_subscriptions[batch_id]:
            if sub_tenant_id == tenant_id:
                if (tenant_id in self.active_connections and 
                    user_id in self.active_connections[tenant_id]):
                    websocket = self.active_connections[tenant_id][user_id]["websocket"]
                    subscribed_connections.append(websocket)
        
        # Send to subscribed connections
        if subscribed_connections:
            await self._broadcast_to_connections(subscribed_connections, message)
    
    async def send_import_error_notification(self, batch_id: UUID, error_data: Dict[str, Any],
                                           tenant_id: UUID):
        """Send error notifications to subscribed users."""
        if batch_id not in self.import_subscriptions:
            return
        
        message = {
            "type": "import_error",
            "batch_id": str(batch_id),
            "error": error_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Get subscribed connections for this tenant
        subscribed_connections = []
        for sub_tenant_id, user_id in self.import_subscriptions[batch_id]:
            if sub_tenant_id == tenant_id:
                if (tenant_id in self.active_connections and 
                    user_id in self.active_connections[tenant_id]):
                    websocket = self.active_connections[tenant_id][user_id]["websocket"]
                    subscribed_connections.append(websocket)
        
        # Send to subscribed connections
        if subscribed_connections:
            await self._broadcast_to_connections(subscribed_connections, message)
    
    async def _broadcast_to_connections(self, connections: List[WebSocket], message: Dict[str, Any]):
        """Send a message to multiple WebSocket connections."""
        if not connections:
            return
        
        # Create tasks for concurrent sending
        tasks = []
        for websocket in connections:
            task = asyncio.create_task(self.send_personal_message(websocket, message))
            tasks.append(task)
        
        # Wait for all sends to complete
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error broadcasting to connections: {e}")
    
    async def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics for monitoring."""
        total_connections = sum(
            len(tenant_connections) 
            for tenant_connections in self.active_connections.values()
        )
        
        tenant_stats = {}
        for tenant_id, connections in self.active_connections.items():
            tenant_stats[str(tenant_id)] = {
                "active_connections": len(connections),
                "users": list(str(user_id) for user_id in connections.keys())
            }
        
        return {
            "total_connections": total_connections,
            "total_tenants": len(self.active_connections),
            "active_imports": len(self.import_subscriptions),
            "tenant_breakdown": tenant_stats
        }


# Global connection manager instance
connection_manager = ConnectionManager()


class ImportProgressBroadcaster:
    """Service for broadcasting import progress updates via WebSocket and Redis."""
    
    def __init__(self):
        self.redis_service = RedisService()
        self.connection_manager = connection_manager
    
    async def update_progress(self, batch_id: UUID, progress_data: Dict[str, Any]):
        """Update import progress and broadcast to subscribers."""
        try:
            # Store progress in Redis for persistence
            cache_key = f"import_progress:{batch_id}"
            await self.redis_service.set_json(cache_key, progress_data, expire=3600)
            
            # Broadcast via WebSocket
            await self.connection_manager.broadcast_import_progress(batch_id, progress_data)
            
            logger.debug(f"Progress updated for import {batch_id}: {progress_data}")
            
        except Exception as e:
            logger.error(f"Error updating import progress: {e}")
    
    async def update_status(self, batch_id: UUID, status: str, tenant_id: UUID,
                          additional_data: Optional[Dict[str, Any]] = None):
        """Update import status and broadcast to subscribers."""
        try:
            # Store status in Redis
            status_data = {
                "status": status,
                "timestamp": datetime.utcnow().isoformat()
            }
            if additional_data:
                status_data.update(additional_data)
            
            cache_key = f"import_status:{batch_id}"
            await self.redis_service.set_json(cache_key, status_data, expire=3600)
            
            # Broadcast via WebSocket
            await self.connection_manager.broadcast_import_status_change(
                batch_id, status, tenant_id, additional_data
            )
            
            logger.info(f"Status updated for import {batch_id}: {status}")
            
        except Exception as e:
            logger.error(f"Error updating import status: {e}")
    
    async def report_error(self, batch_id: UUID, error_data: Dict[str, Any], tenant_id: UUID):
        """Report import error and notify subscribers."""
        try:
            # Store error in Redis
            error_cache_key = f"import_errors:{batch_id}"
            errors_list = await self.redis_service.get_json(error_cache_key) or []
            errors_list.append({
                **error_data,
                "timestamp": datetime.utcnow().isoformat()
            })
            await self.redis_service.set_json(error_cache_key, errors_list, expire=3600)
            
            # Broadcast error notification
            await self.connection_manager.send_import_error_notification(
                batch_id, error_data, tenant_id
            )
            
            logger.warning(f"Error reported for import {batch_id}: {error_data}")
            
        except Exception as e:
            logger.error(f"Error reporting import error: {e}")
    
    async def get_cached_progress(self, batch_id: UUID) -> Optional[Dict[str, Any]]:
        """Get cached progress data for an import."""
        try:
            cache_key = f"import_progress:{batch_id}"
            return await self.redis_service.get_json(cache_key)
        except Exception as e:
            logger.error(f"Error getting cached progress: {e}")
            return None
    
    async def get_cached_status(self, batch_id: UUID) -> Optional[Dict[str, Any]]:
        """Get cached status data for an import."""
        try:
            cache_key = f"import_status:{batch_id}"
            return await self.redis_service.get_json(cache_key)
        except Exception as e:
            logger.error(f"Error getting cached status: {e}")
            return None
    
    async def cleanup_import_cache(self, batch_id: UUID):
        """Clean up Redis cache for completed import."""
        try:
            keys_to_delete = [
                f"import_progress:{batch_id}",
                f"import_status:{batch_id}",
                f"import_errors:{batch_id}",
                f"csv_metadata:{batch_id}"
            ]
            
            for key in keys_to_delete:
                await self.redis_service.delete(key)
            
            logger.info(f"Cleaned up cache for import {batch_id}")
            
        except Exception as e:
            logger.error(f"Error cleaning up import cache: {e}")


# Global progress broadcaster instance
progress_broadcaster = ImportProgressBroadcaster()


async def handle_websocket_message(websocket: WebSocket, tenant_id: UUID, user_id: UUID, 
                                 message_data: Dict[str, Any]):
    """Handle incoming WebSocket messages from clients."""
    try:
        message_type = message_data.get("type")
        
        if message_type == "subscribe_import":
            batch_id = UUID(message_data["batch_id"])
            await connection_manager.subscribe_to_import(tenant_id, user_id, batch_id)
            
        elif message_type == "unsubscribe_import":
            batch_id = UUID(message_data["batch_id"])
            await connection_manager.unsubscribe_from_import(tenant_id, user_id, batch_id)
            
        elif message_type == "get_progress":
            batch_id = UUID(message_data["batch_id"])
            progress_data = await progress_broadcaster.get_cached_progress(batch_id)
            
            if progress_data:
                await connection_manager.send_personal_message(
                    websocket,
                    {
                        "type": "import_progress",
                        "batch_id": str(batch_id),
                        "data": progress_data,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
            
        elif message_type == "ping":
            # Respond to ping with pong
            await connection_manager.send_personal_message(
                websocket,
                {
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
        else:
            await connection_manager.send_personal_message(
                websocket,
                {
                    "type": "error",
                    "message": f"Unknown message type: {message_type}",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
    
    except Exception as e:
        logger.error(f"Error handling WebSocket message: {e}")
        await connection_manager.send_personal_message(
            websocket,
            {
                "type": "error",
                "message": "Error processing message",
                "timestamp": datetime.utcnow().isoformat()
            }
        )