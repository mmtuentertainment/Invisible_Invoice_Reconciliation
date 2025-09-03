// 3-Way Matching Engine Edge Function
// Handles invoice-PO-receipt matching with AI enhancement
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
  getIdempotencyKey,
  logRequest,
  logError,
  addCORSHeaders,
  createCORSResponse
} from '../_shared/utils.ts';
import type { 
  MatchingRequest,
  ResolveExceptionRequest
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

    let response: Response;

    // Route handling
    if (req.method === 'POST' && pathParts.includes('run')) {
      response = await handleRunMatching(supabase, req, context);
    } else if (req.method === 'GET' && pathParts.includes('exceptions')) {
      response = await handleListExceptions(supabase, url, context);
    } else if (req.method === 'POST' && pathParts.includes('resolve')) {
      const exceptionId = pathParts[pathParts.indexOf('exceptions') + 1];
      response = await handleResolveException(supabase, req, exceptionId, context);
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

// Run 3-way matching
async function handleRunMatching(
  supabase: any,
  req: Request,
  context: any
): Promise<Response> {
  const idempotencyKey = getIdempotencyKey(req);
  if (!idempotencyKey) {
    throw new APIError('idempotency_key_required', 'Idempotency-Key header required', 400);
  }

  const requestData: MatchingRequest = await req.json();
  const { invoice_ids = [], auto_approve_threshold = 85 } = requestData;

  // Validate invoice IDs if provided
  for (const id of invoice_ids) {
    if (!validateUUID(id)) {
      throw new APIError('validation_failed', `Invalid invoice ID format: ${id}`, 400);
    }
  }

  // Create matching job
  const jobId = crypto.randomUUID();
  const { data: job, error: jobError } = await supabase
    .from('matching_jobs')
    .insert([{
      id: jobId,
      tenant_id: context.tenantId,
      job_type: '3way_matching',
      status: 'queued',
      invoice_ids: invoice_ids,
      auto_approve_threshold: auto_approve_threshold,
      created_by: context.userId
    }])
    .select()
    .single();

  if (jobError) {
    throw new APIError('database_error', 'Failed to create matching job', 500, jobError.message);
  }

  // Process matching asynchronously
  processMatchingAsync(supabase, jobId, invoice_ids, auto_approve_threshold, context).catch(error => {
    logError(error, context, { jobId });
  });

  return createSuccessResponse({
    job_id: jobId,
    status: 'queued',
    documents_to_process: invoice_ids.length || null,
    created_at: job.created_at
  }, 202);
}

// Async matching processing
async function processMatchingAsync(
  supabase: any,
  jobId: string,
  invoiceIds: string[],
  autoApproveThreshold: number,
  context: any
): Promise<void> {
  try {
    // Update job status
    await supabase
      .from('matching_jobs')
      .update({ 
        status: 'processing',
        started_at: new Date().toISOString()
      })
      .eq('id', jobId);

    // Get invoices to match
    let invoiceQuery = supabase
      .from('invoices')
      .select(`
        *,
        vendor:vendors(*),
        line_items:invoice_line_items(*)
      `)
      .eq('tenant_id', context.tenantId)
      .eq('matching_status', 'unmatched');

    if (invoiceIds.length > 0) {
      invoiceQuery = invoiceQuery.in('id', invoiceIds);
    }

    const { data: invoices, error: invoiceError } = await invoiceQuery;

    if (invoiceError) {
      throw new Error(`Failed to fetch invoices: ${invoiceError.message}`);
    }

    let processedCount = 0;
    let matchedCount = 0;
    let exceptionCount = 0;

    // Process each invoice
    for (const invoice of invoices) {
      try {
        const matchResult = await performThreeWayMatch(supabase, invoice, context);
        
        if (matchResult.overall_confidence >= autoApproveThreshold) {
          // Auto-approve high confidence matches
          await supabase
            .from('match_results')
            .update({ 
              approval_status: 'auto_approved',
              approved_at: new Date().toISOString()
            })
            .eq('id', matchResult.id);

          await supabase
            .from('invoices')
            .update({ matching_status: 'matched' })
            .eq('id', invoice.id);

          matchedCount++;
        } else if (matchResult.match_status === 'exception') {
          exceptionCount++;
        }

        processedCount++;

      } catch (error) {
        logError(error, context, { invoiceId: invoice.id, jobId });
        exceptionCount++;
        processedCount++;
      }
    }

    // Complete the job
    await supabase
      .from('matching_jobs')
      .update({
        status: 'completed',
        completed_at: new Date().toISOString(),
        result_summary: {
          total_processed: processedCount,
          matched_count: matchedCount,
          exception_count: exceptionCount
        }
      })
      .eq('id', jobId);

  } catch (error) {
    logError(error, context, { jobId });

    await supabase
      .from('matching_jobs')
      .update({
        status: 'failed',
        completed_at: new Date().toISOString(),
        error_message: error.message
      })
      .eq('id', jobId);
  }
}

// Core 3-way matching algorithm
async function performThreeWayMatch(
  supabase: any,
  invoice: any,
  context: any
): Promise<any> {
  const startTime = Date.now();

  // Find potential PO matches
  const poMatches = await findPOMatches(supabase, invoice);
  
  // Find potential receipt matches
  const receiptMatches = await findReceiptMatches(supabase, invoice);

  let bestMatch = null;
  let matchType = '2way_po_invoice';
  let overallConfidence = 0;
  let fieldScores = {};

  // Try 3-way match first (PO + Receipt + Invoice)
  for (const po of poMatches) {
    const receiptsForPO = receiptMatches.filter(r => r.po_id === po.id);
    
    for (const receipt of receiptsForPO) {
      const confidence = calculateThreeWayConfidence(invoice, po, receipt);
      
      if (confidence > overallConfidence) {
        overallConfidence = confidence;
        bestMatch = { invoice, po, receipt };
        matchType = '3way_full';
        fieldScores = {
          vendor_score: calculateVendorScore(invoice.vendor, po.vendor),
          amount_score: calculateAmountScore(invoice.total_amount, po.total_amount),
          date_score: calculateDateScore(invoice.invoice_date, po.po_date),
          po_number_score: po ? 100 : 0,
          receipt_match_score: calculateReceiptScore(invoice, receipt)
        };
      }
    }
  }

  // If no 3-way match, try 2-way PO-Invoice match
  if (overallConfidence < 70) {
    for (const po of poMatches) {
      const confidence = calculateTwoWayConfidence(invoice, po);
      
      if (confidence > overallConfidence) {
        overallConfidence = confidence;
        bestMatch = { invoice, po };
        matchType = '2way_po_invoice';
        fieldScores = {
          vendor_score: calculateVendorScore(invoice.vendor, po.vendor),
          amount_score: calculateAmountScore(invoice.total_amount, po.total_amount),
          date_score: calculateDateScore(invoice.invoice_date, po.po_date),
          po_number_score: 100
        };
      }
    }
  }

  // Enhanced matching with ML if available
  if (overallConfidence > 50 && overallConfidence < 95) {
    try {
      const mlEnhancement = await enhanceMatchingWithML(invoice, bestMatch?.po, bestMatch?.receipt);
      overallConfidence = Math.max(overallConfidence, mlEnhancement.confidence_score);
      fieldScores = { ...fieldScores, ...mlEnhancement.field_matches };
    } catch (error) {
      logError(error, context, { invoiceId: invoice.id });
    }
  }

  // Determine match status
  let matchStatus = 'failed';
  let exceptionType = null;
  let varianceAmount = null;

  if (overallConfidence >= 95) {
    matchStatus = 'matched';
  } else if (overallConfidence >= 70) {
    matchStatus = 'partial';
  } else if (overallConfidence >= 50) {
    matchStatus = 'exception';
    exceptionType = determineExceptionType(invoice, bestMatch?.po, fieldScores);
  } else {
    matchStatus = 'failed';
    exceptionType = 'no_match_found';
  }

  // Calculate variance amount
  if (bestMatch?.po) {
    varianceAmount = invoice.total_amount - bestMatch.po.total_amount;
  }

  // Create match result
  const { data: matchResult, error: matchError } = await supabase
    .from('match_results')
    .insert([{
      tenant_id: context.tenantId,
      invoice_id: invoice.id,
      po_id: bestMatch?.po?.id || null,
      receipt_id: bestMatch?.receipt?.id || null,
      match_type: matchType,
      match_status: matchStatus,
      overall_confidence: overallConfidence,
      field_scores: fieldScores,
      exception_type: exceptionType,
      variance_amount: varianceAmount,
      variance_percentage: bestMatch?.po ? (varianceAmount / bestMatch.po.total_amount) * 100 : null,
      approval_status: 'pending',
      matching_engine_version: '1.0.0',
      processing_time_ms: Date.now() - startTime,
      rules_applied: ['exact_match', 'tolerance_match', 'fuzzy_match']
    }])
    .select()
    .single();

  if (matchError) {
    throw new Error(`Failed to create match result: ${matchError.message}`);
  }

  // Create exception if needed
  if (matchStatus === 'exception') {
    await createMatchException(supabase, matchResult.id, exceptionType, invoice, bestMatch?.po, context);
  }

  // Log matching event
  await supabase.rpc('log_matching_event', {
    p_tenant_id: context.tenantId,
    p_event_type: 'match_attempt',
    p_match_result_id: matchResult.id,
    p_invoice_id: invoice.id,
    p_po_id: bestMatch?.po?.id || null,
    p_receipt_id: bestMatch?.receipt?.id || null,
    p_event_data: {
      confidence: overallConfidence,
      match_type: matchType,
      match_status: matchStatus
    },
    p_processing_time_ms: Date.now() - startTime
  });

  return matchResult;
}

// Find potential PO matches
async function findPOMatches(supabase: any, invoice: any): Promise<any[]> {
  let query = supabase
    .from('purchase_orders')
    .select(`
      *,
      vendor:vendors(*),
      line_items:po_line_items(*)
    `)
    .eq('tenant_id', invoice.tenant_id)
    .in('status', ['approved', 'partially_received', 'received']);

  // If invoice has PO reference, prioritize it
  if (invoice.po_id) {
    query = query.eq('id', invoice.po_id);
  } else if (invoice.vendor_id) {
    // Match by vendor
    query = query.eq('vendor_id', invoice.vendor_id);
  }

  const { data: pos, error } = await query.limit(10);

  if (error) {
    throw new Error(`Failed to find PO matches: ${error.message}`);
  }

  return pos || [];
}

// Find potential receipt matches
async function findReceiptMatches(supabase: any, invoice: any): Promise<any[]> {
  let query = supabase
    .from('receipts')
    .select(`
      *,
      line_items:receipt_line_items(*)
    `)
    .eq('tenant_id', invoice.tenant_id)
    .eq('status', 'accepted');

  if (invoice.vendor_id) {
    query = query.eq('vendor_id', invoice.vendor_id);
  }

  const { data: receipts, error } = await query.limit(10);

  if (error) {
    throw new Error(`Failed to find receipt matches: ${error.message}`);
  }

  return receipts || [];
}

// Calculate confidence scores
function calculateThreeWayConfidence(invoice: any, po: any, receipt: any): number {
  const vendorScore = calculateVendorScore(invoice.vendor, po.vendor);
  const amountScore = calculateAmountScore(invoice.total_amount, po.total_amount);
  const dateScore = calculateDateScore(invoice.invoice_date, po.po_date);
  const receiptScore = calculateReceiptScore(invoice, receipt);

  // Weighted average for 3-way match
  return (vendorScore * 0.25) + (amountScore * 0.35) + (dateScore * 0.15) + (receiptScore * 0.25);
}

function calculateTwoWayConfidence(invoice: any, po: any): number {
  const vendorScore = calculateVendorScore(invoice.vendor, po.vendor);
  const amountScore = calculateAmountScore(invoice.total_amount, po.total_amount);
  const dateScore = calculateDateScore(invoice.invoice_date, po.po_date);

  // Weighted average for 2-way match
  return (vendorScore * 0.3) + (amountScore * 0.4) + (dateScore * 0.3);
}

function calculateVendorScore(vendor1: any, vendor2: any): number {
  if (!vendor1 || !vendor2) return 0;
  
  // Exact match on normalized names
  if (vendor1.normalized_name === vendor2.normalized_name) return 100;
  
  // Fuzzy match using Levenshtein-like similarity
  const similarity = calculateStringSimilarity(vendor1.normalized_name, vendor2.normalized_name);
  return similarity * 100;
}

function calculateAmountScore(amount1: number, amount2: number): number {
  if (!amount1 || !amount2) return 0;
  
  const difference = Math.abs(amount1 - amount2);
  const averageAmount = (amount1 + amount2) / 2;
  
  // Allow 5% tolerance or $10, whichever is greater
  const tolerance = Math.max(averageAmount * 0.05, 10);
  
  if (difference <= tolerance) {
    return 100 - (difference / tolerance) * 20; // Gradual reduction within tolerance
  }
  
  return Math.max(0, 100 - (difference / averageAmount) * 100);
}

function calculateDateScore(date1: string, date2: string): number {
  if (!date1 || !date2) return 0;
  
  const d1 = new Date(date1);
  const d2 = new Date(date2);
  const daysDifference = Math.abs((d1.getTime() - d2.getTime()) / (1000 * 60 * 60 * 24));
  
  // Allow 7 days tolerance
  if (daysDifference <= 7) {
    return 100 - (daysDifference / 7) * 30;
  }
  
  return Math.max(0, 100 - daysDifference * 2);
}

function calculateReceiptScore(invoice: any, receipt: any): number {
  if (!receipt) return 0;
  
  // Check if receipt date is before invoice date (logical flow)
  const receiptDate = new Date(receipt.receipt_date);
  const invoiceDate = new Date(invoice.invoice_date);
  
  if (receiptDate <= invoiceDate) {
    return 90; // High score for logical date order
  }
  
  return 60; // Lower score for illogical date order
}

function calculateStringSimilarity(str1: string, str2: string): number {
  const longer = str1.length > str2.length ? str1 : str2;
  const shorter = str1.length > str2.length ? str2 : str1;
  
  if (longer.length === 0) return 1.0;
  
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

// ML Enhancement (placeholder for HuggingFace integration)
async function enhanceMatchingWithML(invoice: any, po: any, receipt?: any): Promise<any> {
  try {
    // This would integrate with HuggingFace API for advanced matching
    const response = await fetch('https://api-inference.huggingface.co/models/invoice-matching', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${Deno.env.get('HUGGINGFACE_API_KEY')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        invoice_data: {
          number: invoice.invoice_number,
          vendor: invoice.vendor?.name,
          amount: invoice.total_amount,
          date: invoice.invoice_date
        },
        po_data: po ? {
          number: po.po_number,
          vendor: po.vendor?.name,
          amount: po.total_amount,
          date: po.po_date
        } : null,
        receipt_data: receipt ? {
          number: receipt.receipt_number,
          date: receipt.receipt_date
        } : null
      })
    });

    if (response.ok) {
      return await response.json();
    }
    
    throw new Error(`ML API error: ${response.status}`);
    
  } catch (error) {
    // Fall back to rule-based matching if ML fails
    return {
      confidence_score: 0,
      field_matches: {}
    };
  }
}

// Determine exception type
function determineExceptionType(invoice: any, po: any, fieldScores: any): string {
  if (!po) return 'missing_document';
  
  if (fieldScores.amount_score < 70) return 'amount_variance';
  if (fieldScores.vendor_score < 80) return 'vendor_mismatch';
  if (fieldScores.date_score < 70) return 'date_variance';
  
  return 'approval_required';
}

// Create match exception
async function createMatchException(
  supabase: any,
  matchResultId: string,
  exceptionType: string,
  invoice: any,
  po: any,
  context: any
): Promise<void> {
  const exceptionDetails = generateExceptionDetails(exceptionType, invoice, po);
  
  await supabase
    .from('match_exceptions')
    .insert([{
      tenant_id: context.tenantId,
      match_result_id: matchResultId,
      exception_type: exceptionType,
      severity: determineSeverity(exceptionType, invoice, po),
      title: exceptionDetails.title,
      description: exceptionDetails.description,
      expected_value: exceptionDetails.expected_value,
      actual_value: exceptionDetails.actual_value,
      field_name: exceptionDetails.field_name,
      variance_amount: exceptionDetails.variance_amount,
      status: 'open',
      priority: determinePriority(exceptionType, invoice),
      due_date: new Date(Date.now() + 24 * 60 * 60 * 1000) // 24 hours from now
    }]);
}

function generateExceptionDetails(exceptionType: string, invoice: any, po: any): any {
  switch (exceptionType) {
    case 'amount_variance':
      return {
        title: 'Invoice Amount Variance',
        description: 'Invoice amount differs significantly from PO amount',
        expected_value: po?.total_amount?.toString(),
        actual_value: invoice.total_amount.toString(),
        field_name: 'total_amount',
        variance_amount: invoice.total_amount - (po?.total_amount || 0)
      };
    case 'vendor_mismatch':
      return {
        title: 'Vendor Mismatch',
        description: 'Invoice vendor does not match PO vendor',
        expected_value: po?.vendor?.name,
        actual_value: invoice.vendor?.name,
        field_name: 'vendor_name',
        variance_amount: null
      };
    default:
      return {
        title: 'Manual Review Required',
        description: 'This match requires manual review',
        expected_value: null,
        actual_value: null,
        field_name: null,
        variance_amount: null
      };
  }
}

function determineSeverity(exceptionType: string, invoice: any, po: any): string {
  if (exceptionType === 'amount_variance' && po) {
    const variance = Math.abs(invoice.total_amount - po.total_amount);
    if (variance > 1000) return 'high';
    if (variance > 100) return 'medium';
  }
  return 'medium';
}

function determinePriority(exceptionType: string, invoice: any): number {
  if (invoice.total_amount > 10000) return 1; // High priority for large amounts
  if (exceptionType === 'amount_variance') return 2;
  return 3;
}

// List matching exceptions
async function handleListExceptions(
  supabase: any,
  url: URL,
  context: any
): Promise<Response> {
  // Implementation similar to invoice listing with filters
  // This is a simplified version - full implementation would include pagination, filtering, etc.
  
  const { data: exceptions, error } = await supabase
    .from('match_exceptions')
    .select(`
      *,
      match_result:match_results(
        *,
        invoice:invoices(invoice_number, total_amount, vendor:vendors(name)),
        purchase_order:purchase_orders(po_number, total_amount)
      )
    `)
    .eq('status', 'open')
    .order('priority', { ascending: true })
    .order('created_at', { ascending: false })
    .limit(50);

  if (error) {
    throw new APIError('database_error', 'Failed to fetch exceptions', 500, error.message);
  }

  return createSuccessResponse(exceptions);
}

// Resolve exception
async function handleResolveException(
  supabase: any,
  req: Request,
  exceptionId: string,
  context: any
): Promise<Response> {
  if (!validateUUID(exceptionId)) {
    throw new APIError('invalid_exception_id', 'Valid exception ID required', 400);
  }

  const requestData: ResolveExceptionRequest = await req.json();
  validateRequiredFields(requestData, ['resolution']);

  const { data: updatedException, error } = await supabase
    .from('match_exceptions')
    .update({
      status: 'resolved',
      resolution: requestData.resolution,
      resolution_notes: requestData.notes || null,
      resolved_by: context.userId,
      resolved_at: new Date().toISOString()
    })
    .eq('id', exceptionId)
    .select()
    .single();

  if (error) {
    if (error.code === 'PGRST116') {
      throw new APIError('not_found', 'Exception not found', 404);
    }
    throw new APIError('database_error', 'Failed to resolve exception', 500, error.message);
  }

  return createSuccessResponse(updatedException);
}