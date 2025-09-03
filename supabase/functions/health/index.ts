// System Health Check Edge Function
// Provides health status for all system components
// Created: 2025-01-03

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts';
import {
  createSupabaseClient,
  APIError,
  createSuccessResponse,
  addCORSHeaders,
  createCORSResponse,
  logError
} from '../_shared/utils.ts';
import type { HealthCheck, ServiceHealth } from '../_shared/types.ts';

serve(async (req: Request) => {
  try {
    // Handle CORS
    if (req.method === 'OPTIONS') {
      return createCORSResponse();
    }

    if (req.method !== 'GET') {
      throw new APIError('method_not_allowed', 'Method not allowed', 405);
    }

    const url = new URL(req.url);
    const pathParts = url.pathname.split('/').filter(Boolean);

    let response: Response;

    if (pathParts.includes('version')) {
      response = await handleGetVersion();
    } else {
      response = await handleHealthCheck();
    }

    return addCORSHeaders(response);

  } catch (error) {
    logError(error);
    
    if (error instanceof APIError) {
      return addCORSHeaders(error.toResponse());
    }
    
    const apiError = new APIError('internal_error', 'Internal server error', 500);
    return addCORSHeaders(apiError.toResponse());
  }
});

// Main health check
async function handleHealthCheck(): Promise<Response> {
  const timestamp = new Date().toISOString();
  const version = Deno.env.get('API_VERSION') || '1.0.0';

  // Check all services
  const databaseHealth = await checkDatabaseHealth();
  const functionsHealth = await checkFunctionsHealth();
  const storageHealth = await checkStorageHealth();
  const authHealth = await checkAuthHealth();

  // Determine overall health status
  const services = { database: databaseHealth, functions: functionsHealth, storage: storageHealth, auth: authHealth };
  const overallStatus = determineOverallHealth(services);

  const healthCheck: HealthCheck = {
    status: overallStatus,
    timestamp,
    version,
    services
  };

  const statusCode = overallStatus === 'healthy' ? 200 : 503;
  return createSuccessResponse(healthCheck, statusCode);
}

// Check database connectivity
async function checkDatabaseHealth(): Promise<ServiceHealth> {
  const startTime = Date.now();
  
  try {
    const supabase = createSupabaseClient();
    
    // Simple connectivity test
    const { data, error } = await supabase
      .from('tenants')
      .select('id')
      .limit(1);

    const responseTime = Date.now() - startTime;

    if (error) {
      return {
        status: 'unhealthy',
        response_time_ms: responseTime,
        last_check: new Date().toISOString()
      };
    }

    // Determine status based on response time
    let status: 'healthy' | 'degraded' | 'unhealthy' = 'healthy';
    if (responseTime > 2000) {
      status = 'unhealthy';
    } else if (responseTime > 1000) {
      status = 'degraded';
    }

    return {
      status,
      response_time_ms: responseTime,
      last_check: new Date().toISOString()
    };

  } catch (error) {
    return {
      status: 'unhealthy',
      response_time_ms: Date.now() - startTime,
      last_check: new Date().toISOString()
    };
  }
}

// Check functions health
async function checkFunctionsHealth(): Promise<ServiceHealth> {
  const startTime = Date.now();
  
  try {
    // Test function execution capability
    const testResult = await new Promise((resolve) => {
      // Simple computational test
      const data = Array.from({ length: 1000 }, (_, i) => i);
      const sum = data.reduce((acc, val) => acc + val, 0);
      resolve(sum === 499500); // Expected sum for 0-999
    });

    const responseTime = Date.now() - startTime;

    return {
      status: testResult ? 'healthy' : 'degraded',
      response_time_ms: responseTime,
      last_check: new Date().toISOString()
    };

  } catch (error) {
    return {
      status: 'unhealthy',
      response_time_ms: Date.now() - startTime,
      last_check: new Date().toISOString()
    };
  }
}

// Check storage health
async function checkStorageHealth(): Promise<ServiceHealth> {
  const startTime = Date.now();
  
  try {
    const supabase = createSupabaseClient();
    
    // Test storage accessibility
    const { data, error } = await supabase.storage
      .from('documents')
      .list('', { limit: 1 });

    const responseTime = Date.now() - startTime;

    // Storage might not be initialized, so we check for specific errors
    const isHealthy = !error || error.message.includes('not found'); // Bucket not found is OK for health check
    
    let status: 'healthy' | 'degraded' | 'unhealthy' = 'healthy';
    if (!isHealthy) {
      status = 'unhealthy';
    } else if (responseTime > 2000) {
      status = 'degraded';
    }

    return {
      status,
      response_time_ms: responseTime,
      last_check: new Date().toISOString()
    };

  } catch (error) {
    return {
      status: 'unhealthy',
      response_time_ms: Date.now() - startTime,
      last_check: new Date().toISOString()
    };
  }
}

// Check auth health
async function checkAuthHealth(): Promise<ServiceHealth> {
  const startTime = Date.now();
  
  try {
    const supabase = createSupabaseClient();
    
    // Test auth service availability (check if we can access user management)
    const { data, error } = await supabase.auth.admin.listUsers({
      page: 1,
      perPage: 1
    });

    const responseTime = Date.now() - startTime;

    let status: 'healthy' | 'degraded' | 'unhealthy' = 'healthy';
    if (error && error.message?.includes('not authorized')) {
      // Auth service is responding but we don't have admin permissions
      // This is actually healthy for a function context
      status = 'healthy';
    } else if (error) {
      status = 'unhealthy';
    } else if (responseTime > 2000) {
      status = 'degraded';
    }

    return {
      status,
      response_time_ms: responseTime,
      last_check: new Date().toISOString()
    };

  } catch (error) {
    return {
      status: 'unhealthy',
      response_time_ms: Date.now() - startTime,
      last_check: new Date().toISOString()
    };
  }
}

// Determine overall system health
function determineOverallHealth(services: Record<string, ServiceHealth>): 'healthy' | 'degraded' | 'unhealthy' {
  const statuses = Object.values(services).map(service => service.status);
  
  // If any service is unhealthy, system is unhealthy
  if (statuses.includes('unhealthy')) {
    return 'unhealthy';
  }
  
  // If any service is degraded, system is degraded
  if (statuses.includes('degraded')) {
    return 'degraded';
  }
  
  // All services are healthy
  return 'healthy';
}

// Get version information
async function handleGetVersion(): Promise<Response> {
  const versionInfo = {
    api_version: Deno.env.get('API_VERSION') || '1.0.0',
    build_number: Deno.env.get('BUILD_NUMBER') || 'dev',
    build_date: Deno.env.get('BUILD_DATE') || new Date().toISOString(),
    git_commit: Deno.env.get('GIT_COMMIT') || 'unknown',
    deno_version: Deno.version.deno,
    typescript_version: Deno.version.typescript
  };

  return createSuccessResponse(versionInfo);
}