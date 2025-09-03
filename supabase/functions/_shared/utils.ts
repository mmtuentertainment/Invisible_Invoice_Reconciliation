// Shared utility functions for Supabase Edge Functions
// Created: 2025-01-03

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import type { Database, APIError, FunctionContext, Pagination, PaginationParams } from './types.ts';

// Initialize Supabase client
export function createSupabaseClient() {
  const supabaseUrl = Deno.env.get('SUPABASE_URL')!;
  const supabaseServiceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
  
  return createClient<Database>(supabaseUrl, supabaseServiceKey, {
    auth: {
      autoRefreshToken: false,
      persistSession: false
    }
  });
}

// Extract user context from JWT token
export async function getUserContext(req: Request): Promise<FunctionContext> {
  const authHeader = req.headers.get('Authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    throw new APIError('authentication_required', 'Bearer token required', 401);
  }

  const token = authHeader.substring(7);
  
  try {
    // Decode JWT payload (in production, should verify signature)
    const payload = JSON.parse(atob(token.split('.')[1]));
    
    // Extract tenant context from JWT claims
    const tenantId = payload.tenant_id;
    const userId = payload.sub;
    const userRole = payload.user_role || 'member';
    
    if (!tenantId) {
      throw new APIError('invalid_token', 'Tenant context missing from token', 401);
    }

    return {
      tenantId,
      userId,
      userRole
    };
  } catch (error) {
    throw new APIError('invalid_token', 'Invalid JWT token', 401);
  }
}

// Set tenant context for RLS
export async function setTenantContext(supabase: any, tenantId: string) {
  const { error } = await supabase.rpc('set_tenant_context', { 
    tenant_uuid: tenantId 
  });
  
  if (error) {
    throw new APIError('tenant_context_error', 'Failed to set tenant context', 500);
  }
}

// Custom API Error class
export class APIError extends Error {
  public type: string;
  public status: number;
  public detail?: string;
  public instance?: string;
  public correlationId: string;
  public errors?: Array<{ field: string; message: string; }>;

  constructor(
    type: string,
    message: string,
    status: number,
    detail?: string,
    errors?: Array<{ field: string; message: string; }>
  ) {
    super(message);
    this.name = 'APIError';
    this.type = `https://api.invoice-recon.com/errors/${type}`;
    this.status = status;
    this.detail = detail;
    this.correlationId = crypto.randomUUID();
    this.errors = errors;
  }

  toResponse(): Response {
    const errorBody = {
      type: this.type,
      title: this.message,
      status: this.status,
      detail: this.detail,
      instance: this.instance,
      correlationId: this.correlationId,
      ...(this.errors && { errors: this.errors })
    };

    return new Response(JSON.stringify(errorBody), {
      status: this.status,
      headers: {
        'Content-Type': 'application/json',
        'X-Correlation-ID': this.correlationId
      }
    });
  }
}

// Success response helper
export function createSuccessResponse<T>(
  data: T,
  status: number = 200,
  pagination?: Pagination
): Response {
  const body: any = { data };
  if (pagination) {
    body.pagination = pagination;
  }

  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'X-Correlation-ID': crypto.randomUUID()
    }
  });
}

// Validation helpers
export function validateRequiredFields(
  data: Record<string, any>,
  requiredFields: string[]
): void {
  const errors: Array<{ field: string; message: string }> = [];
  
  for (const field of requiredFields) {
    if (data[field] === undefined || data[field] === null || data[field] === '') {
      errors.push({
        field,
        message: `${field} is required`
      });
    }
  }
  
  if (errors.length > 0) {
    throw new APIError('validation_failed', 'Request validation failed', 400, undefined, errors);
  }
}

export function validateEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

export function validateUUID(uuid: string): boolean {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  return uuidRegex.test(uuid);
}

export function validateAmount(amount: number): boolean {
  return typeof amount === 'number' && amount >= 0 && Number.isFinite(amount);
}

export function validateDate(dateString: string): boolean {
  const date = new Date(dateString);
  return date instanceof Date && !isNaN(date.getTime());
}

// Pagination helpers
export function parsePaginationParams(url: URL): PaginationParams {
  const page = Math.max(1, parseInt(url.searchParams.get('page') ?? '1'));
  const limit = Math.min(100, Math.max(1, parseInt(url.searchParams.get('limit') ?? '20')));
  const sort = url.searchParams.get('sort') || 'created_at:desc';
  
  return { page, limit, sort };
}

export function createPagination(
  page: number,
  limit: number,
  totalItems: number
): Pagination {
  const totalPages = Math.ceil(totalItems / limit);
  
  return {
    page,
    limit,
    total_pages: totalPages,
    total_items: totalItems,
    has_next: page < totalPages,
    has_prev: page > 1
  };
}

export function buildOrderByClause(sort: string): string {
  const [field, direction] = sort.split(':');
  const validDirections = ['asc', 'desc'];
  const validFields = [
    'created_at', 'updated_at', 'name', 'invoice_number', 
    'po_number', 'total_amount', 'invoice_date', 'due_date',
    'status', 'matching_status', 'priority'
  ];
  
  if (!validFields.includes(field) || !validDirections.includes(direction)) {
    return 'created_at:desc';
  }
  
  return `${field}:${direction}`;
}

// CSV parsing helpers
export function parseCSV(content: string, options: {
  hasHeader?: boolean;
  delimiter?: string;
} = {}): Array<Record<string, string>> {
  const { hasHeader = true, delimiter = ',' } = options;
  const lines = content.split('\n').map(line => line.trim()).filter(line => line);
  
  if (lines.length === 0) {
    return [];
  }
  
  const headers = hasHeader 
    ? lines[0].split(delimiter).map(h => h.trim().replace(/"/g, ''))
    : Array.from({ length: lines[0].split(delimiter).length }, (_, i) => `column_${i + 1}`);
  
  const dataLines = hasHeader ? lines.slice(1) : lines;
  
  return dataLines.map((line, rowIndex) => {
    const values = line.split(delimiter).map(v => v.trim().replace(/"/g, ''));
    const row: Record<string, string> = {};
    
    headers.forEach((header, colIndex) => {
      row[header] = values[colIndex] || '';
    });
    
    return row;
  });
}

export function validateCSVRow(
  row: Record<string, string>,
  rowIndex: number,
  requiredFields: string[]
): Array<{ row_number: number; field: string; message: string }> {
  const errors: Array<{ row_number: number; field: string; message: string }> = [];
  
  for (const field of requiredFields) {
    if (!row[field] || row[field].trim() === '') {
      errors.push({
        row_number: rowIndex + 1,
        field,
        message: `${field} is required`
      });
    }
  }
  
  // Validate specific field types
  if (row.amount && !validateAmount(parseFloat(row.amount))) {
    errors.push({
      row_number: rowIndex + 1,
      field: 'amount',
      message: 'Amount must be a valid positive number'
    });
  }
  
  if (row.invoice_date && !validateDate(row.invoice_date)) {
    errors.push({
      row_number: rowIndex + 1,
      field: 'invoice_date',
      message: 'Invoice date must be in YYYY-MM-DD format'
    });
  }
  
  if (row.email && !validateEmail(row.email)) {
    errors.push({
      row_number: rowIndex + 1,
      field: 'email',
      message: 'Email must be a valid email address'
    });
  }
  
  return errors;
}

// Rate limiting helpers
export function createRateLimitKey(
  endpoint: string,
  identifier: string,
  window: string = '1m'
): string {
  return `rate_limit:${endpoint}:${identifier}:${window}`;
}

// Idempotency helpers
export function getIdempotencyKey(req: Request): string | null {
  return req.headers.get('Idempotency-Key');
}

export async function checkIdempotency(
  supabase: any,
  key: string,
  payload: any
): Promise<{ exists: boolean; response?: any }> {
  // In a real implementation, you'd store idempotency keys in Redis
  // For now, we'll use a simple database table approach
  const { data, error } = await supabase
    .from('idempotency_keys')
    .select('response_data')
    .eq('key', key)
    .single();
    
  if (error && error.code !== 'PGRST116') { // Not found error
    throw new APIError('idempotency_check_failed', 'Failed to check idempotency', 500);
  }
  
  if (data) {
    // Key exists, check if payload matches
    const storedPayload = data.response_data.request_payload;
    if (JSON.stringify(storedPayload) !== JSON.stringify(payload)) {
      throw new APIError('idempotency_conflict', 'Idempotency key used with different payload', 409);
    }
    return { exists: true, response: data.response_data };
  }
  
  return { exists: false };
}

export async function storeIdempotencyResult(
  supabase: any,
  key: string,
  requestPayload: any,
  responseData: any
): Promise<void> {
  const { error } = await supabase
    .from('idempotency_keys')
    .insert({
      key,
      request_payload: requestPayload,
      response_data: responseData,
      expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000) // 24 hours
    });
    
  if (error) {
    console.error('Failed to store idempotency result:', error);
  }
}

// Logging helpers
export function logRequest(
  req: Request,
  context: FunctionContext,
  startTime: number
) {
  const duration = Date.now() - startTime;
  console.log({
    timestamp: new Date().toISOString(),
    method: req.method,
    url: req.url,
    tenant_id: context.tenantId,
    user_id: context.userId,
    duration_ms: duration
  });
}

export function logError(
  error: Error,
  context?: FunctionContext,
  additionalInfo?: any
) {
  console.error({
    timestamp: new Date().toISOString(),
    error: {
      name: error.name,
      message: error.message,
      stack: error.stack
    },
    context,
    additional_info: additionalInfo
  });
}

// CORS headers
export function addCORSHeaders(response: Response): Response {
  response.headers.set('Access-Control-Allow-Origin', '*');
  response.headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  response.headers.set('Access-Control-Allow-Headers', 'Content-Type, Authorization, Idempotency-Key');
  return response;
}

export function createCORSResponse(): Response {
  return new Response(null, {
    status: 200,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, Idempotency-Key',
    }
  });
}