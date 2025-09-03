'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { toast } from 'sonner';

interface WebSocketMessage {
  type: string;
  batch_id?: string;
  data?: any;
  timestamp: string;
  error?: string;
  message?: string;
}

interface ProgressData {
  progress_percentage: number;
  processing_stage: string;
  statistics: any;
  status: string;
}

type MessageHandler = (data: ProgressData) => void;

export function useWebSocketConnection() {
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const subscriptions = useRef<Map<string, MessageHandler>>(new Map());
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5;
  const reconnectTimeout = useRef<NodeJS.Timeout | null>(null);

  const getWebSocketUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const tenantId = localStorage.getItem('tenant_id') || 'default';
    const token = localStorage.getItem('access_token');
    
    let url = `${protocol}//${host}/api/v1/ws/${tenantId}`;
    if (token) {
      url += `?token=${encodeURIComponent(token)}`;
    }
    
    return url;
  }, []);

  const connect = useCallback(() => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      return; // Already connected
    }

    try {
      const wsUrl = getWebSocketUrl();
      ws.current = new WebSocket(wsUrl);

      ws.current.onopen = () => {
        setIsConnected(true);
        setConnectionError(null);
        reconnectAttempts.current = 0;
        console.log('WebSocket connected');
      };

      ws.current.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          handleMessage(message);
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };

      ws.current.onclose = (event) => {
        setIsConnected(false);
        console.log('WebSocket closed:', event.code, event.reason);

        // Attempt to reconnect unless it was a clean close
        if (event.code !== 1000 && reconnectAttempts.current < maxReconnectAttempts) {
          const delay = Math.pow(2, reconnectAttempts.current) * 1000; // Exponential backoff
          reconnectTimeout.current = setTimeout(() => {
            reconnectAttempts.current++;
            connect();
          }, delay);
        } else if (reconnectAttempts.current >= maxReconnectAttempts) {
          setConnectionError('Failed to establish WebSocket connection after multiple attempts');
        }
      };

      ws.current.onerror = (error) => {
        console.error('WebSocket error:', error);
        setConnectionError('WebSocket connection error');
      };

    } catch (error) {
      console.error('Error creating WebSocket connection:', error);
      setConnectionError('Failed to create WebSocket connection');
    }
  }, [getWebSocketUrl]);

  const disconnect = useCallback(() => {
    if (reconnectTimeout.current) {
      clearTimeout(reconnectTimeout.current);
      reconnectTimeout.current = null;
    }

    if (ws.current) {
      ws.current.close(1000, 'Client disconnect');
      ws.current = null;
    }

    setIsConnected(false);
    setConnectionError(null);
    subscriptions.current.clear();
  }, []);

  const sendMessage = useCallback((message: any) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(message));
      return true;
    }
    return false;
  }, []);

  const handleMessage = useCallback((message: WebSocketMessage) => {
    switch (message.type) {
      case 'connection_established':
        console.log('WebSocket connection established');
        break;

      case 'import_progress':
        if (message.batch_id && message.data) {
          const handler = subscriptions.current.get(message.batch_id);
          if (handler) {
            handler(message.data);
          }
        }
        break;

      case 'import_status_change':
        if (message.batch_id && message.data) {
          const handler = subscriptions.current.get(message.batch_id);
          if (handler) {
            handler({
              ...message.data,
              status: message.data.status || 'unknown',
              progress_percentage: message.data.progress_percentage || 0
            });
          }
        }
        break;

      case 'import_error':
        if (message.error && message.batch_id) {
          toast.error(`Import error: ${message.error.message || 'Unknown error'}`);
          const handler = subscriptions.current.get(message.batch_id);
          if (handler) {
            handler({
              status: 'error',
              progress_percentage: 100,
              processing_stage: 'Error occurred',
              statistics: {}
            });
          }
        }
        break;

      case 'subscription_confirmed':
        console.log('Subscription confirmed for batch:', message.batch_id);
        break;

      case 'pong':
        // Heartbeat response
        break;

      case 'error':
        console.error('WebSocket error message:', message.message);
        if (message.message) {
          toast.error(message.message);
        }
        break;

      default:
        console.log('Unknown WebSocket message type:', message.type);
    }
  }, []);

  const subscribe = useCallback((batchId: string, handler: MessageHandler) => {
    // Store the handler
    subscriptions.current.set(batchId, handler);

    // Send subscription message if connected
    if (sendMessage({
      type: 'subscribe_import',
      batch_id: batchId
    })) {
      console.log('Subscribed to batch:', batchId);
    } else {
      console.warn('Not connected, subscription will be sent when connection is established');
    }

    // Return unsubscribe function
    return () => unsubscribe(batchId);
  }, [sendMessage]);

  const unsubscribe = useCallback((batchId: string) => {
    subscriptions.current.delete(batchId);
    
    sendMessage({
      type: 'unsubscribe_import',
      batch_id: batchId
    });
    
    console.log('Unsubscribed from batch:', batchId);
  }, [sendMessage]);

  const getProgress = useCallback((batchId: string) => {
    return sendMessage({
      type: 'get_progress',
      batch_id: batchId
    });
  }, [sendMessage]);

  // Heartbeat to keep connection alive
  useEffect(() => {
    if (!isConnected) return;

    const heartbeat = setInterval(() => {
      sendMessage({ type: 'ping' });
    }, 30000); // Every 30 seconds

    return () => clearInterval(heartbeat);
  }, [isConnected, sendMessage]);

  // Auto-connect on mount
  useEffect(() => {
    connect();
    
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  // Reconnect on focus if disconnected
  useEffect(() => {
    const handleFocus = () => {
      if (!isConnected && reconnectAttempts.current < maxReconnectAttempts) {
        connect();
      }
    };

    window.addEventListener('focus', handleFocus);
    return () => window.removeEventListener('focus', handleFocus);
  }, [isConnected, connect]);

  return {
    isConnected,
    connectionError,
    connect,
    disconnect,
    subscribe,
    unsubscribe,
    getProgress,
    sendMessage,
  };
}