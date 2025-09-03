// Invoice Management Edge Function
// Handles CRUD operations for invoices
// Created: 2025-01-03

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts';
import {
  createSupabaseClient,
  getUserContext,
  setTenantContext,
  APIError,
  createSuccessResponse,
  validateRequiredFields,
  validateUUID,
  validateAmount,
  validateDate,
  parsePaginationParams,
  createPagination,
  buildOrderByClause,
  getIdempotencyKey,
  checkIdempotency,
  storeIdempotencyResult,
  logRequest,
  logError,
  addCORSHeaders,
  createCORSResponse
} from '../_shared/utils.ts';
import type { 
  CreateInvoiceRequest,
  InvoiceStatus,
  MatchingStatus,
  Database
} from '../_shared/types.ts';

serve(async (req: Request) => {
  const startTime = Date.now();

  try {
    // Handle CORS
    if (req.method === 'OPTIONS') {
      return createCORSResponse();
    }

    // Get user context and setup
    const context = await getUserContext(req);
    const supabase = createSupabaseClient();
    await setTenantContext(supabase, context.tenantId);

    const url = new URL(req.url);
    const pathParts = url.pathname.split('/').filter(Boolean);
    const invoiceId = pathParts[pathParts.length - 1];

    let response: Response;

    switch (req.method) {
      case 'GET':
        if (validateUUID(invoiceId)) {
          response = await handleGetInvoice(supabase, invoiceId, context);
        } else {
          response = await handleListInvoices(supabase, url, context);
        }
        break;
        
      case 'POST':
        response = await handleCreateInvoice(supabase, req, context);
        break;
        
      case 'PUT':
        if (!validateUUID(invoiceId)) {
          throw new APIError('invalid_invoice_id', 'Valid invoice ID required', 400);
        }
        response = await handleUpdateInvoice(supabase, req, invoiceId, context);
        break;
        
      case 'DELETE':
        if (!validateUUID(invoiceId)) {
          throw new APIError('invalid_invoice_id', 'Valid invoice ID required', 400);
        }
        response = await handleDeleteInvoice(supabase, invoiceId, context);
        break;
        
      default:
        throw new APIError('method_not_allowed', 'Method not allowed', 405);
    }

    logRequest(req, context, startTime);
    return addCORSHeaders(response);

  } catch (error) {
    logError(error, context);
    
    if (error instanceof APIError) {
      return addCORSHeaders(error.toResponse());
    }
    
    const apiError = new APIError('internal_error', 'Internal server error', 500);
    return addCORSHeaders(apiError.toResponse());
  }
});

// List invoices with filtering and pagination
async function handleListInvoices(
  supabase: any,
  url: URL,
  context: any
): Promise<Response> {
  const { page, limit, sort } = parsePaginationParams(url);
  const orderBy = buildOrderByClause(sort);
  
  // Build query with filters
  let query = supabase
    .from('invoices')
    .select(`
      *,
      vendor:vendors(id, name, normalized_name),
      purchase_order:purchase_orders(id, po_number)
    `, { count: 'exact' });

  // Apply filters
  const status = url.searchParams.get('status') as InvoiceStatus;
  if (status) {
    query = query.eq('status', status);
  }

  const matchingStatus = url.searchParams.get('matching_status') as MatchingStatus;
  if (matchingStatus) {
    query = query.eq('matching_status', matchingStatus);
  }

  const vendorId = url.searchParams.get('vendor_id');
  if (vendorId && validateUUID(vendorId)) {
    query = query.eq('vendor_id', vendorId);
  }

  const dateFrom = url.searchParams.get('date_from');
  if (dateFrom && validateDate(dateFrom)) {
    query = query.gte('invoice_date', dateFrom);
  }

  const dateTo = url.searchParams.get('date_to');
  if (dateTo && validateDate(dateTo)) {
    query = query.lte('invoice_date', dateTo);
  }

  // Apply sorting and pagination
  const [field, direction] = orderBy.split(':');
  query = query.order(field, { ascending: direction === 'asc' });
  query = query.range((page - 1) * limit, page * limit - 1);

  const { data, error, count } = await query;

  if (error) {
    throw new APIError('database_error', 'Failed to fetch invoices', 500, error.message);
  }

  const pagination = createPagination(page, limit, count || 0);
  return createSuccessResponse(data, 200, pagination);
}

// Get single invoice with details
async function handleGetInvoice(
  supabase: any,
  invoiceId: string,
  context: any
): Promise<Response> {
  const { data, error } = await supabase
    .from('invoices')
    .select(`
      *,
      vendor:vendors(*),
      purchase_order:purchase_orders(*),
      line_items:invoice_line_items(*),
      match_results(*)
    `)
    .eq('id', invoiceId)
    .single();

  if (error) {
    if (error.code === 'PGRST116') {
      throw new APIError('not_found', 'Invoice not found', 404);
    }
    throw new APIError('database_error', 'Failed to fetch invoice', 500, error.message);
  }

  return createSuccessResponse(data);
}

// Create new invoice
async function handleCreateInvoice(
  supabase: any,
  req: Request,
  context: any
): Promise<Response> {
  const idempotencyKey = getIdempotencyKey(req);
  if (!idempotencyKey) {
    throw new APIError('idempotency_key_required', 'Idempotency-Key header required', 400);
  }

  const requestData: CreateInvoiceRequest = await req.json();

  // Check idempotency
  const { exists, response: cachedResponse } = await checkIdempotency(
    supabase,
    idempotencyKey,
    requestData
  );
  if (exists) {
    return createSuccessResponse(cachedResponse);
  }

  // Validate required fields
  validateRequiredFields(requestData, [
    'invoice_number',
    'vendor_id',
    'total_amount',
    'invoice_date'
  ]);

  // Validate field formats
  if (!validateUUID(requestData.vendor_id)) {
    throw new APIError('validation_failed', 'Invalid vendor ID format', 400);
  }

  if (!validateAmount(requestData.total_amount)) {
    throw new APIError('validation_failed', 'Total amount must be a positive number', 400);
  }

  if (!validateDate(requestData.invoice_date)) {
    throw new APIError('validation_failed', 'Invoice date must be in YYYY-MM-DD format', 400);
  }

  if (requestData.po_id && !validateUUID(requestData.po_id)) {
    throw new APIError('validation_failed', 'Invalid PO ID format', 400);
  }

  // Check if vendor exists
  const { data: vendor, error: vendorError } = await supabase
    .from('vendors')
    .select('id')
    .eq('id', requestData.vendor_id)
    .single();

  if (vendorError || !vendor) {
    throw new APIError('validation_failed', 'Vendor not found', 400);
  }

  // Check for duplicate invoice number for this vendor
  const { data: existingInvoice } = await supabase
    .from('invoices')
    .select('id')
    .eq('invoice_number', requestData.invoice_number)
    .eq('vendor_id', requestData.vendor_id)
    .single();

  if (existingInvoice) {
    throw new APIError('duplicate_invoice', 'Invoice number already exists for this vendor', 409);
  }

  // Start transaction for invoice + line items
  const { data: invoice, error: invoiceError } = await supabase
    .from('invoices')
    .insert([{
      tenant_id: context.tenantId,
      invoice_number: requestData.invoice_number,
      vendor_id: requestData.vendor_id,
      po_id: requestData.po_id || null,
      subtotal: requestData.subtotal || requestData.total_amount,
      tax_amount: requestData.tax_amount || 0,
      total_amount: requestData.total_amount,
      currency: requestData.currency || 'USD',
      invoice_date: requestData.invoice_date,
      due_date: requestData.due_date || null,
      reference_number: requestData.reference_number || null,
      department: requestData.department || null,
      status: 'pending' as InvoiceStatus,
      matching_status: 'unmatched' as MatchingStatus,
      import_source: 'manual',
      created_by: context.userId
    }])
    .select()
    .single();

  if (invoiceError) {
    throw new APIError('database_error', 'Failed to create invoice', 500, invoiceError.message);
  }

  // Insert line items if provided
  if (requestData.line_items && requestData.line_items.length > 0) {
    const lineItems = requestData.line_items.map(item => ({
      invoice_id: invoice.id,
      line_number: item.line_number,
      description: item.description,
      sku: item.sku || null,
      quantity: item.quantity,
      unit_price: item.unit_price,
      line_total: item.quantity * item.unit_price,
      tax_rate: item.tax_rate || 0,
      tax_amount: (item.tax_rate || 0) * item.quantity * item.unit_price / 100
    }));

    const { error: lineItemsError } = await supabase
      .from('invoice_line_items')
      .insert(lineItems);

    if (lineItemsError) {
      // Rollback invoice creation
      await supabase.from('invoices').delete().eq('id', invoice.id);
      throw new APIError('database_error', 'Failed to create invoice line items', 500, lineItemsError.message);
    }
  }

  // Store idempotency result
  await storeIdempotencyResult(supabase, idempotencyKey, requestData, invoice);

  return createSuccessResponse(invoice, 201);
}

// Update invoice
async function handleUpdateInvoice(
  supabase: any,
  req: Request,
  invoiceId: string,
  context: any
): Promise<Response> {
  const idempotencyKey = getIdempotencyKey(req);
  if (!idempotencyKey) {
    throw new APIError('idempotency_key_required', 'Idempotency-Key header required', 400);
  }

  const updateData = await req.json();

  // Check if invoice exists
  const { data: existingInvoice, error: fetchError } = await supabase
    .from('invoices')
    .select('id, status')
    .eq('id', invoiceId)
    .single();

  if (fetchError || !existingInvoice) {
    throw new APIError('not_found', 'Invoice not found', 404);
  }

  // Validate update data
  const allowedUpdates = ['status', 'due_date', 'reference_number', 'department'];
  const updateFields: any = {};

  for (const field of allowedUpdates) {
    if (updateData[field] !== undefined) {
      updateFields[field] = updateData[field];
    }
  }

  if (Object.keys(updateFields).length === 0) {
    throw new APIError('validation_failed', 'No valid update fields provided', 400);
  }

  // Validate specific fields
  if (updateFields.due_date && !validateDate(updateFields.due_date)) {
    throw new APIError('validation_failed', 'Due date must be in YYYY-MM-DD format', 400);
  }

  const { data: updatedInvoice, error: updateError } = await supabase
    .from('invoices')
    .update(updateFields)
    .eq('id', invoiceId)
    .select()
    .single();

  if (updateError) {
    throw new APIError('database_error', 'Failed to update invoice', 500, updateError.message);
  }

  return createSuccessResponse(updatedInvoice);
}

// Delete invoice (soft delete by changing status)
async function handleDeleteInvoice(
  supabase: any,
  invoiceId: string,
  context: any
): Promise<Response> {
  // Only admins and managers can delete invoices
  if (!['admin', 'manager'].includes(context.userRole)) {
    throw new APIError('forbidden', 'Insufficient permissions to delete invoices', 403);
  }

  const { data: deletedInvoice, error } = await supabase
    .from('invoices')
    .update({ status: 'cancelled' })
    .eq('id', invoiceId)
    .select()
    .single();

  if (error) {
    if (error.code === 'PGRST116') {
      throw new APIError('not_found', 'Invoice not found', 404);
    }
    throw new APIError('database_error', 'Failed to delete invoice', 500, error.message);
  }

  return createSuccessResponse(deletedInvoice);
}