// Vendor Management Edge Function
// Handles vendor CRUD operations and normalization
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
  validateEmail,
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
  CreateVendorRequest,
  VendorStatus,
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
    const vendorId = pathParts[pathParts.length - 1];

    let response: Response;

    // Route handling
    if (req.method === 'GET' && validateUUID(vendorId)) {
      response = await handleGetVendor(supabase, vendorId, context);
    } else if (req.method === 'GET') {
      response = await handleListVendors(supabase, url, context);
    } else if (req.method === 'POST' && pathParts.includes('normalize')) {
      response = await handleNormalizeVendors(supabase, req, context);
    } else if (req.method === 'POST') {
      response = await handleCreateVendor(supabase, req, context);
    } else if (req.method === 'PUT' && validateUUID(vendorId)) {
      response = await handleUpdateVendor(supabase, req, vendorId, context);
    } else if (req.method === 'DELETE' && validateUUID(vendorId)) {
      response = await handleDeleteVendor(supabase, vendorId, context);
    } else {
      throw new APIError('not_found', 'Endpoint not found', 404);
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

// List vendors with search and filtering
async function handleListVendors(
  supabase: any,
  url: URL,
  context: any
): Promise<Response> {
  const { page, limit, sort } = parsePaginationParams(url);
  const orderBy = buildOrderByClause(sort);
  
  let query = supabase
    .from('vendors')
    .select('*', { count: 'exact' });

  // Apply search
  const search = url.searchParams.get('search');
  if (search) {
    query = query.or(`name.ilike.%${search}%,normalized_name.ilike.%${search}%,email.ilike.%${search}%`);
  }

  // Apply status filter
  const status = url.searchParams.get('status') as VendorStatus;
  if (status) {
    query = query.eq('status', status);
  }

  // Apply sorting and pagination
  const [field, direction] = orderBy.split(':');
  query = query.order(field, { ascending: direction === 'asc' });
  query = query.range((page - 1) * limit, page * limit - 1);

  const { data, error, count } = await query;

  if (error) {
    throw new APIError('database_error', 'Failed to fetch vendors', 500, error.message);
  }

  const pagination = createPagination(page, limit, count || 0);
  return createSuccessResponse(data, 200, pagination);
}

// Get single vendor
async function handleGetVendor(
  supabase: any,
  vendorId: string,
  context: any
): Promise<Response> {
  const { data, error } = await supabase
    .from('vendors')
    .select('*')
    .eq('id', vendorId)
    .single();

  if (error) {
    if (error.code === 'PGRST116') {
      throw new APIError('not_found', 'Vendor not found', 404);
    }
    throw new APIError('database_error', 'Failed to fetch vendor', 500, error.message);
  }

  return createSuccessResponse(data);
}

// Create new vendor
async function handleCreateVendor(
  supabase: any,
  req: Request,
  context: any
): Promise<Response> {
  // Only admins and managers can create vendors
  if (!['admin', 'manager'].includes(context.userRole)) {
    throw new APIError('forbidden', 'Insufficient permissions to create vendors', 403);
  }

  const idempotencyKey = getIdempotencyKey(req);
  if (!idempotencyKey) {
    throw new APIError('idempotency_key_required', 'Idempotency-Key header required', 400);
  }

  const requestData: CreateVendorRequest = await req.json();

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
  validateRequiredFields(requestData, ['name']);

  // Validate email format if provided
  if (requestData.email && !validateEmail(requestData.email)) {
    throw new APIError('validation_failed', 'Invalid email format', 400);
  }

  // Check for duplicate vendor names (normalized)
  const normalizedName = normalizeVendorName(requestData.name);
  const { data: existingVendor } = await supabase
    .from('vendors')
    .select('id')
    .eq('normalized_name', normalizedName)
    .single();

  if (existingVendor) {
    throw new APIError('duplicate_vendor', 'Vendor with similar name already exists', 409);
  }

  // Create vendor
  const vendorData = {
    tenant_id: context.tenantId,
    name: requestData.name.trim(),
    normalized_name: normalizedName,
    email: requestData.email || null,
    phone: requestData.phone || null,
    website: requestData.website || null,
    address_line_1: requestData.address?.line_1 || null,
    address_line_2: requestData.address?.line_2 || null,
    city: requestData.address?.city || null,
    state_province: requestData.address?.state_province || null,
    postal_code: requestData.address?.postal_code || null,
    country: requestData.address?.country || 'US',
    tax_id: requestData.tax_id || null,
    business_type: requestData.business_type || null,
    default_payment_terms: requestData.default_payment_terms || 30,
    status: 'active' as VendorStatus,
    created_by: context.userId
  };

  const { data: vendor, error } = await supabase
    .from('vendors')
    .insert([vendorData])
    .select()
    .single();

  if (error) {
    throw new APIError('database_error', 'Failed to create vendor', 500, error.message);
  }

  // Store idempotency result
  await storeIdempotencyResult(supabase, idempotencyKey, requestData, vendor);

  return createSuccessResponse(vendor, 201);
}

// Update vendor
async function handleUpdateVendor(
  supabase: any,
  req: Request,
  vendorId: string,
  context: any
): Promise<Response> {
  // Only admins and managers can update vendors
  if (!['admin', 'manager'].includes(context.userRole)) {
    throw new APIError('forbidden', 'Insufficient permissions to update vendors', 403);
  }

  const updateData = await req.json();

  // Check if vendor exists
  const { data: existingVendor, error: fetchError } = await supabase
    .from('vendors')
    .select('id, name')
    .eq('id', vendorId)
    .single();

  if (fetchError || !existingVendor) {
    throw new APIError('not_found', 'Vendor not found', 404);
  }

  // Validate update data
  const allowedUpdates = [
    'name', 'email', 'phone', 'website', 'address', 'tax_id', 
    'business_type', 'default_payment_terms', 'status'
  ];
  
  const updateFields: any = {};

  for (const field of allowedUpdates) {
    if (updateData[field] !== undefined) {
      if (field === 'address' && updateData[field]) {
        // Handle nested address object
        const addr = updateData[field];
        updateFields.address_line_1 = addr.line_1 || null;
        updateFields.address_line_2 = addr.line_2 || null;
        updateFields.city = addr.city || null;
        updateFields.state_province = addr.state_province || null;
        updateFields.postal_code = addr.postal_code || null;
        updateFields.country = addr.country || 'US';
      } else {
        updateFields[field] = updateData[field];
      }
    }
  }

  if (Object.keys(updateFields).length === 0) {
    throw new APIError('validation_failed', 'No valid update fields provided', 400);
  }

  // Validate email if being updated
  if (updateFields.email && !validateEmail(updateFields.email)) {
    throw new APIError('validation_failed', 'Invalid email format', 400);
  }

  // Update normalized name if name is being changed
  if (updateFields.name) {
    updateFields.normalized_name = normalizeVendorName(updateFields.name);
  }

  const { data: updatedVendor, error: updateError } = await supabase
    .from('vendors')
    .update(updateFields)
    .eq('id', vendorId)
    .select()
    .single();

  if (updateError) {
    throw new APIError('database_error', 'Failed to update vendor', 500, updateError.message);
  }

  return createSuccessResponse(updatedVendor);
}

// Delete vendor (soft delete by changing status)
async function handleDeleteVendor(
  supabase: any,
  vendorId: string,
  context: any
): Promise<Response> {
  // Only admins can delete vendors
  if (context.userRole !== 'admin') {
    throw new APIError('forbidden', 'Insufficient permissions to delete vendors', 403);
  }

  // Check if vendor has associated invoices or POs
  const { data: associatedRecords } = await supabase
    .from('invoices')
    .select('id')
    .eq('vendor_id', vendorId)
    .limit(1);

  if (associatedRecords && associatedRecords.length > 0) {
    throw new APIError('vendor_in_use', 'Cannot delete vendor with associated invoices', 409);
  }

  const { data: deletedVendor, error } = await supabase
    .from('vendors')
    .update({ status: 'inactive' })
    .eq('id', vendorId)
    .select()
    .single();

  if (error) {
    if (error.code === 'PGRST116') {
      throw new APIError('not_found', 'Vendor not found', 404);
    }
    throw new APIError('database_error', 'Failed to delete vendor', 500, error.message);
  }

  return createSuccessResponse(deletedVendor);
}

// Vendor normalization
async function handleNormalizeVendors(
  supabase: any,
  req: Request,
  context: any
): Promise<Response> {
  // Only admins and managers can normalize vendors
  if (!['admin', 'manager'].includes(context.userRole)) {
    throw new APIError('forbidden', 'Insufficient permissions to normalize vendors', 403);
  }

  const idempotencyKey = getIdempotencyKey(req);
  if (!idempotencyKey) {
    throw new APIError('idempotency_key_required', 'Idempotency-Key header required', 400);
  }

  const requestData = await req.json();
  const { threshold = 80, auto_merge = false } = requestData;

  // Create normalization job
  const jobId = crypto.randomUUID();
  const { data: job, error: jobError } = await supabase
    .from('vendor_normalization_jobs')
    .insert([{
      id: jobId,
      tenant_id: context.tenantId,
      status: 'queued',
      threshold: threshold,
      auto_merge: auto_merge,
      created_by: context.userId
    }])
    .select()
    .single();

  if (jobError) {
    throw new APIError('database_error', 'Failed to create normalization job', 500, jobError.message);
  }

  // Process normalization asynchronously
  processVendorNormalizationAsync(supabase, jobId, threshold, auto_merge, context).catch(error => {
    logError(error, context, { jobId });
  });

  return createSuccessResponse({
    job_id: jobId,
    status: 'queued',
    created_at: job.created_at
  }, 202);
}

// Async vendor normalization processing
async function processVendorNormalizationAsync(
  supabase: any,
  jobId: string,
  threshold: number,
  autoMerge: boolean,
  context: any
): Promise<void> {
  try {
    // Update job status
    await supabase
      .from('vendor_normalization_jobs')
      .update({ 
        status: 'processing',
        started_at: new Date().toISOString()
      })
      .eq('id', jobId);

    // Get all vendors for the tenant
    const { data: vendors, error: vendorError } = await supabase
      .from('vendors')
      .select('*')
      .eq('tenant_id', context.tenantId)
      .eq('status', 'active');

    if (vendorError) {
      throw new Error(`Failed to fetch vendors: ${vendorError.message}`);
    }

    const duplicateGroups = findDuplicateVendors(vendors, threshold);
    let potentialDuplicates = 0;
    let autoMergedCount = 0;

    // Process each group of potential duplicates
    for (const group of duplicateGroups) {
      if (group.length < 2) continue;

      potentialDuplicates += group.length;

      // Create normalization records for manual review
      for (let i = 1; i < group.length; i++) {
        const duplicateVendor = group[i];
        const canonicalVendor = group[0]; // First vendor as canonical

        const similarity = calculateVendorSimilarity(canonicalVendor, duplicateVendor);

        await supabase
          .from('vendor_normalization')
          .insert([{
            tenant_id: context.tenantId,
            original_name: duplicateVendor.name,
            normalized_name: canonicalVendor.normalized_name,
            confidence: similarity,
            canonical_vendor_id: canonicalVendor.id,
            status: autoMerge && similarity >= 95 ? 'approved' : 'pending'
          }]);

        // Auto-merge if enabled and high confidence
        if (autoMerge && similarity >= 95) {
          await mergeVendors(supabase, canonicalVendor.id, duplicateVendor.id, context);
          autoMergedCount++;
        }
      }
    }

    // Complete the job
    await supabase
      .from('vendor_normalization_jobs')
      .update({
        status: 'completed',
        completed_at: new Date().toISOString(),
        result_summary: {
          potential_duplicates: potentialDuplicates,
          auto_merged_count: autoMergedCount
        }
      })
      .eq('id', jobId);

  } catch (error) {
    logError(error, context, { jobId });

    await supabase
      .from('vendor_normalization_jobs')
      .update({
        status: 'failed',
        completed_at: new Date().toISOString(),
        error_message: error.message
      })
      .eq('id', jobId);
  }
}

// Vendor normalization utilities
function normalizeVendorName(name: string): string {
  return name
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9\s]/g, '') // Remove special characters
    .replace(/\b(INC|INCORPORATED|LLC|LTD|LIMITED|CORP|CORPORATION|CO|COMPANY)\b/g, '') // Remove legal suffixes
    .replace(/\s+/g, ' ') // Normalize whitespace
    .trim();
}

function findDuplicateVendors(vendors: any[], threshold: number): any[][] {
  const groups: any[][] = [];
  const processed = new Set();

  for (let i = 0; i < vendors.length; i++) {
    if (processed.has(vendors[i].id)) continue;

    const group = [vendors[i]];
    processed.add(vendors[i].id);

    for (let j = i + 1; j < vendors.length; j++) {
      if (processed.has(vendors[j].id)) continue;

      const similarity = calculateVendorSimilarity(vendors[i], vendors[j]);
      
      if (similarity >= threshold) {
        group.push(vendors[j]);
        processed.add(vendors[j].id);
      }
    }

    if (group.length > 1) {
      groups.push(group);
    }
  }

  return groups;
}

function calculateVendorSimilarity(vendor1: any, vendor2: any): number {
  const nameScore = calculateStringSimilarity(vendor1.normalized_name, vendor2.normalized_name) * 100;
  
  let emailScore = 0;
  if (vendor1.email && vendor2.email) {
    emailScore = vendor1.email.toLowerCase() === vendor2.email.toLowerCase() ? 100 : 0;
  }

  let phoneScore = 0;
  if (vendor1.phone && vendor2.phone) {
    phoneScore = normalizePhone(vendor1.phone) === normalizePhone(vendor2.phone) ? 100 : 0;
  }

  let taxIdScore = 0;
  if (vendor1.tax_id && vendor2.tax_id) {
    taxIdScore = vendor1.tax_id === vendor2.tax_id ? 100 : 0;
  }

  // Weighted similarity score
  const weights = { name: 0.6, email: 0.2, phone: 0.1, taxId: 0.1 };
  
  return (nameScore * weights.name) + 
         (emailScore * weights.email) + 
         (phoneScore * weights.phone) + 
         (taxIdScore * weights.taxId);
}

function calculateStringSimilarity(str1: string, str2: string): number {
  if (!str1 || !str2) return 0;
  
  const longer = str1.length > str2.length ? str1 : str2;
  const shorter = str1.length > str2.length ? str2 : str1;
  
  if (longer.length === 0) return 1;
  
  const distance = levenshteinDistance(longer, shorter);
  return (longer.length - distance) / longer.length;
}

function levenshteinDistance(str1: string, str2: string): number {
  const matrix = [];
  
  for (let i = 0; i <= str2.length; i++) {
    matrix[i] = [i];
  }
  
  for (let j = 0; j <= str1.length; j++) {
    matrix[0][j] = j;
  }
  
  for (let i = 1; i <= str2.length; i++) {
    for (let j = 1; j <= str1.length; j++) {
      if (str2.charAt(i - 1) === str1.charAt(j - 1)) {
        matrix[i][j] = matrix[i - 1][j - 1];
      } else {
        matrix[i][j] = Math.min(
          matrix[i - 1][j - 1] + 1,
          matrix[i][j - 1] + 1,
          matrix[i - 1][j] + 1
        );
      }
    }
  }
  
  return matrix[str2.length][str1.length];
}

function normalizePhone(phone: string): string {
  return phone.replace(/\D/g, ''); // Remove all non-digits
}

// Merge vendors
async function mergeVendors(
  supabase: any,
  canonicalVendorId: string,
  duplicateVendorId: string,
  context: any
): Promise<void> {
  try {
    // Update all invoices to use canonical vendor
    await supabase
      .from('invoices')
      .update({ vendor_id: canonicalVendorId })
      .eq('vendor_id', duplicateVendorId);

    // Update all POs to use canonical vendor
    await supabase
      .from('purchase_orders')
      .update({ vendor_id: canonicalVendorId })
      .eq('vendor_id', duplicateVendorId);

    // Update all receipts to use canonical vendor
    await supabase
      .from('receipts')
      .update({ vendor_id: canonicalVendorId })
      .eq('vendor_id', duplicateVendorId);

    // Mark duplicate vendor as inactive
    await supabase
      .from('vendors')
      .update({ 
        status: 'inactive',
        metadata: { merged_into: canonicalVendorId, merged_at: new Date().toISOString() }
      })
      .eq('id', duplicateVendorId);

  } catch (error) {
    logError(error, context, { canonicalVendorId, duplicateVendorId });
    throw error;
  }
}