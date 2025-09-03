// Invoice Processing Edge Function  
// Handles CSV import and validation pipeline
// Created: 2025-01-03

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts';
import {
  createSupabaseClient,
  getUserContext,
  setTenantContext,
  APIError,
  createSuccessResponse,
  parseCSV,
  validateCSVRow,
  validateRequiredFields,
  validateUUID,
  validateAmount,
  validateDate,
  validateEmail,
  getIdempotencyKey,
  logRequest,
  logError,
  addCORSHeaders,
  createCORSResponse
} from '../_shared/utils.ts';
import type { 
  CSVImportOptions,
  ImportJob,
  ImportJobStatus
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
    if (req.method === 'POST' && pathParts.includes('csv')) {
      response = await handleCSVImport(supabase, req, context);
    } else if (req.method === 'GET' && pathParts.includes('status')) {
      const jobId = pathParts[pathParts.length - 1];
      response = await handleGetImportStatus(supabase, jobId, context);
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

// Handle CSV import
async function handleCSVImport(
  supabase: any,
  req: Request,
  context: any
): Promise<Response> {
  const idempotencyKey = getIdempotencyKey(req);
  if (!idempotencyKey) {
    throw new APIError('idempotency_key_required', 'Idempotency-Key header required', 400);
  }

  // Parse multipart form data
  const formData = await req.formData();
  const file = formData.get('file') as File;
  const optionsStr = formData.get('options') as string;

  if (!file) {
    throw new APIError('validation_failed', 'CSV file is required', 400);
  }

  // Validate file size (50MB limit)
  const maxSize = 50 * 1024 * 1024; // 50MB
  if (file.size > maxSize) {
    throw new APIError('file_too_large', 'File size exceeds 50MB limit', 413);
  }

  // Validate file type
  if (!file.name.toLowerCase().endsWith('.csv') && file.type !== 'text/csv') {
    throw new APIError('invalid_file_type', 'File must be a CSV', 400);
  }

  // Parse options
  const options: CSVImportOptions = optionsStr ? JSON.parse(optionsStr) : {};
  const {
    has_header = true,
    delimiter = ',',
    skip_validation = false,
    auto_match = true
  } = options;

  // Create import job record
  const jobId = crypto.randomUUID();
  const { data: job, error: jobError } = await supabase
    .from('import_jobs')
    .insert([{
      id: jobId,
      tenant_id: context.tenantId,
      job_type: 'csv_import',
      status: 'queued',
      file_name: file.name,
      file_size: file.size,
      options: options,
      created_by: context.userId
    }])
    .select()
    .single();

  if (jobError) {
    throw new APIError('database_error', 'Failed to create import job', 500, jobError.message);
  }

  // Process CSV asynchronously
  processCSVAsync(supabase, jobId, file, options, context).catch(error => {
    logError(error, context, { jobId });
  });

  const importJob: ImportJob = {
    job_id: jobId,
    status: 'queued',
    created_at: job.created_at
  };

  return createSuccessResponse(importJob, 202);
}

// Async CSV processing function
async function processCSVAsync(
  supabase: any,
  jobId: string,
  file: File,
  options: CSVImportOptions,
  context: any
): Promise<void> {
  try {
    // Update job status to processing
    await supabase
      .from('import_jobs')
      .update({ 
        status: 'processing', 
        started_at: new Date().toISOString() 
      })
      .eq('id', jobId);

    // Read and parse CSV
    const content = await file.text();
    const rows = parseCSV(content, {
      hasHeader: options.has_header,
      delimiter: options.delimiter
    });

    if (rows.length === 0) {
      throw new Error('CSV file is empty or invalid');
    }

    // Initialize progress tracking
    const progress = {
      total_rows: rows.length,
      processed_rows: 0,
      successful_rows: 0,
      failed_rows: 0,
      warnings: 0
    };

    const errors: Array<{
      row_number: number;
      field: string;
      message: string;
    }> = [];

    const successfulInvoices: any[] = [];

    // Required fields for invoice CSV
    const requiredFields = ['invoice_number', 'vendor_name', 'amount', 'invoice_date'];

    // Process each row
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      progress.processed_rows++;

      try {
        // Validate row
        const rowErrors = validateCSVRow(row, i, requiredFields);
        if (rowErrors.length > 0) {
          errors.push(...rowErrors);
          progress.failed_rows++;
          continue;
        }

        // Normalize and validate data
        const invoiceData = await normalizeInvoiceRow(supabase, row, context);
        
        // Create invoice record
        const { data: invoice, error: invoiceError } = await supabase
          .from('invoices')
          .insert([{
            ...invoiceData,
            tenant_id: context.tenantId,
            import_batch_id: jobId,
            import_source: 'csv',
            status: 'pending',
            matching_status: 'unmatched',
            created_by: context.userId
          }])
          .select()
          .single();

        if (invoiceError) {
          // Handle duplicate invoice numbers gracefully
          if (invoiceError.code === '23505') {
            errors.push({
              row_number: i + 1,
              field: 'invoice_number',
              message: 'Duplicate invoice number'
            });
            progress.failed_rows++;
          } else {
            throw invoiceError;
          }
        } else {
          successfulInvoices.push(invoice);
          progress.successful_rows++;
        }

        // Update progress every 10 rows
        if (progress.processed_rows % 10 === 0) {
          await updateJobProgress(supabase, jobId, progress, errors);
        }

      } catch (error) {
        logError(error, context, { jobId, rowNumber: i + 1 });
        errors.push({
          row_number: i + 1,
          field: 'processing',
          message: error.message || 'Row processing failed'
        });
        progress.failed_rows++;
      }
    }

    // Final progress update
    await updateJobProgress(supabase, jobId, progress, errors);

    // Trigger auto-matching if enabled
    if (options.auto_match && successfulInvoices.length > 0) {
      await triggerAutoMatching(supabase, successfulInvoices.map(inv => inv.id), context);
    }

    // Mark job as completed
    await supabase
      .from('import_jobs')
      .update({ 
        status: 'completed',
        completed_at: new Date().toISOString(),
        result_summary: {
          total_invoices: progress.total_rows,
          successful_imports: progress.successful_rows,
          failed_imports: progress.failed_rows,
          warnings: progress.warnings
        }
      })
      .eq('id', jobId);

  } catch (error) {
    logError(error, context, { jobId });

    // Mark job as failed
    await supabase
      .from('import_jobs')
      .update({ 
        status: 'failed',
        completed_at: new Date().toISOString(),
        error_message: error.message
      })
      .eq('id', jobId);
  }
}

// Normalize CSV row to invoice data
async function normalizeInvoiceRow(
  supabase: any,
  row: Record<string, string>,
  context: any
): Promise<any> {
  // Find or create vendor
  let vendorId = null;
  
  if (row.vendor_name) {
    // Try to find existing vendor by normalized name
    const { data: existingVendor } = await supabase
      .from('vendors')
      .select('id')
      .ilike('normalized_name', row.vendor_name.toUpperCase().replace(/[^A-Z0-9\s]/g, ''))
      .limit(1)
      .single();

    if (existingVendor) {
      vendorId = existingVendor.id;
    } else {
      // Create new vendor
      const { data: newVendor, error: vendorError } = await supabase
        .from('vendors')
        .insert([{
          tenant_id: context.tenantId,
          name: row.vendor_name,
          email: row.vendor_email || null,
          phone: row.vendor_phone || null,
          created_by: context.userId
        }])
        .select('id')
        .single();

      if (vendorError) {
        throw new Error(`Failed to create vendor: ${vendorError.message}`);
      }
      
      vendorId = newVendor.id;
    }
  }

  // Parse amount
  const amount = parseFloat(row.amount.replace(/[^0-9.-]/g, ''));
  if (isNaN(amount) || amount <= 0) {
    throw new Error('Invalid amount format');
  }

  // Parse date
  const invoiceDate = new Date(row.invoice_date);
  if (isNaN(invoiceDate.getTime())) {
    throw new Error('Invalid invoice date format');
  }

  // Calculate due date if payment terms provided
  let dueDate = null;
  if (row.payment_terms) {
    const paymentTerms = parseInt(row.payment_terms);
    if (!isNaN(paymentTerms)) {
      dueDate = new Date(invoiceDate);
      dueDate.setDate(dueDate.getDate() + paymentTerms);
    }
  }

  return {
    invoice_number: row.invoice_number.trim(),
    vendor_id: vendorId,
    po_id: row.po_number ? await findPOByNumber(supabase, row.po_number, context.tenantId) : null,
    total_amount: amount,
    subtotal: row.subtotal ? parseFloat(row.subtotal) : amount,
    tax_amount: row.tax_amount ? parseFloat(row.tax_amount) : 0,
    currency: row.currency || 'USD',
    invoice_date: invoiceDate.toISOString().split('T')[0],
    due_date: dueDate ? dueDate.toISOString().split('T')[0] : null,
    reference_number: row.reference_number || null,
    department: row.department || null,
    payment_terms: row.payment_terms ? parseInt(row.payment_terms) : 30
  };
}

// Find PO by number
async function findPOByNumber(
  supabase: any,
  poNumber: string,
  tenantId: string
): Promise<string | null> {
  const { data } = await supabase
    .from('purchase_orders')
    .select('id')
    .eq('po_number', poNumber.trim())
    .eq('tenant_id', tenantId)
    .single();

  return data?.id || null;
}

// Update job progress
async function updateJobProgress(
  supabase: any,
  jobId: string,
  progress: any,
  errors: any[]
): Promise<void> {
  await supabase
    .from('import_jobs')
    .update({
      progress: progress,
      errors: errors.slice(-100), // Keep last 100 errors
      updated_at: new Date().toISOString()
    })
    .eq('id', jobId);
}

// Trigger auto-matching for imported invoices
async function triggerAutoMatching(
  supabase: any,
  invoiceIds: string[],
  context: any
): Promise<void> {
  try {
    // Call matching engine function
    const { error } = await supabase.functions.invoke('matching-engine', {
      body: {
        invoice_ids: invoiceIds,
        auto_approve_threshold: 85
      }
    });

    if (error) {
      logError(new Error('Auto-matching failed'), context, { invoiceIds, error });
    }
  } catch (error) {
    logError(error, context, { invoiceIds });
  }
}

// Get import job status
async function handleGetImportStatus(
  supabase: any,
  jobId: string,
  context: any
): Promise<Response> {
  if (!validateUUID(jobId)) {
    throw new APIError('invalid_job_id', 'Valid job ID required', 400);
  }

  const { data: job, error } = await supabase
    .from('import_jobs')
    .select('*')
    .eq('id', jobId)
    .single();

  if (error || !job) {
    throw new APIError('not_found', 'Import job not found', 404);
  }

  const status: ImportJobStatus = {
    job_id: job.id,
    status: job.status,
    progress: job.progress || {
      total_rows: 0,
      processed_rows: 0,
      successful_rows: 0,
      failed_rows: 0,
      warnings: 0
    },
    errors: job.errors || [],
    started_at: job.started_at,
    completed_at: job.completed_at,
    estimated_completion: job.estimated_completion
  };

  return createSuccessResponse(status);
}