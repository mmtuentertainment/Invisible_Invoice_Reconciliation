// Dashboard Analytics Edge Function
// Provides dashboard statistics and reports
// Created: 2025-01-03

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts';
import {
  createSupabaseClient,
  getUserContext,
  setTenantContext,
  APIError,
  createSuccessResponse,
  validateDate,
  addCORSHeaders,
  createCORSResponse,
  logRequest,
  logError
} from '../_shared/utils.ts';

serve(async (req: Request) => {
  const startTime = Date.now();

  try {
    // Handle CORS
    if (req.method === 'OPTIONS') {
      return createCORSResponse();
    }

    if (req.method !== 'GET') {
      throw new APIError('method_not_allowed', 'Only GET method allowed', 405);
    }

    // Get user context and setup
    const context = await getUserContext(req);
    const supabase = createSupabaseClient();
    await setTenantContext(supabase, context.tenantId);

    const url = new URL(req.url);
    const pathParts = url.pathname.split('/').filter(Boolean);

    let response: Response;

    // Route handling
    if (pathParts.includes('stats')) {
      response = await handleDashboardStats(supabase, url, context);
    } else if (pathParts.includes('matching-performance')) {
      response = await handleMatchingReport(supabase, url, context);
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

// Get dashboard statistics
async function handleDashboardStats(
  supabase: any,
  url: URL,
  context: any
): Promise<Response> {
  const period = url.searchParams.get('period') || 'month';
  
  // Calculate date range based on period
  const dateRange = getDateRange(period);
  
  // Run all stats queries in parallel for better performance
  const [
    invoiceStats,
    matchingStats,
    processingStats,
    vendorStats
  ] = await Promise.all([
    getInvoiceStats(supabase, dateRange),
    getMatchingStats(supabase, dateRange),
    getProcessingStats(supabase, dateRange),
    getVendorStats(supabase)
  ]);

  const dashboardStats = {
    invoices: invoiceStats,
    matching: matchingStats,
    processing: processingStats,
    vendors: vendorStats
  };

  return createSuccessResponse(dashboardStats);
}

// Get invoice statistics
async function getInvoiceStats(supabase: any, dateRange: { start: string; end: string }): Promise<any> {
  // Total invoices
  const { count: totalInvoices } = await supabase
    .from('invoices')
    .select('*', { count: 'exact', head: true })
    .gte('created_at', dateRange.start)
    .lte('created_at', dateRange.end);

  // Pending invoices
  const { count: pendingInvoices } = await supabase
    .from('invoices')
    .select('*', { count: 'exact', head: true })
    .eq('status', 'pending')
    .gte('created_at', dateRange.start)
    .lte('created_at', dateRange.end);

  // Matched invoices
  const { count: matchedInvoices } = await supabase
    .from('invoices')
    .select('*', { count: 'exact', head: true })
    .eq('matching_status', 'matched')
    .gte('created_at', dateRange.start)
    .lte('created_at', dateRange.end);

  // Exception invoices
  const { count: exceptionInvoices } = await supabase
    .from('invoices')
    .select('*', { count: 'exact', head: true })
    .eq('matching_status', 'exception')
    .gte('created_at', dateRange.start)
    .lte('created_at', dateRange.end);

  return {
    total: totalInvoices || 0,
    pending: pendingInvoices || 0,
    matched: matchedInvoices || 0,
    exceptions: exceptionInvoices || 0
  };
}

// Get matching statistics
async function getMatchingStats(supabase: any, dateRange: { start: string; end: string }): Promise<any> {
  // Get match results for the period
  const { data: matchResults, error } = await supabase
    .from('match_results')
    .select('overall_confidence, match_status, approval_status')
    .gte('created_at', dateRange.start)
    .lte('created_at', dateRange.end);

  if (error || !matchResults || matchResults.length === 0) {
    return {
      first_pass_rate: 0,
      auto_approval_rate: 0,
      avg_confidence: 0,
      exceptions_open: 0
    };
  }

  // Calculate first pass rate (matched on first attempt)
  const firstPassMatches = matchResults.filter(mr => mr.match_status === 'matched').length;
  const firstPassRate = (firstPassMatches / matchResults.length) * 100;

  // Calculate auto-approval rate
  const autoApprovedMatches = matchResults.filter(mr => mr.approval_status === 'auto_approved').length;
  const autoApprovalRate = (autoApprovedMatches / matchResults.length) * 100;

  // Calculate average confidence
  const totalConfidence = matchResults.reduce((sum, mr) => sum + (mr.overall_confidence || 0), 0);
  const avgConfidence = totalConfidence / matchResults.length;

  // Get open exceptions count
  const { count: openExceptions } = await supabase
    .from('match_exceptions')
    .select('*', { count: 'exact', head: true })
    .eq('status', 'open');

  return {
    first_pass_rate: Math.round(firstPassRate * 100) / 100,
    auto_approval_rate: Math.round(autoApprovalRate * 100) / 100,
    avg_confidence: Math.round(avgConfidence * 100) / 100,
    exceptions_open: openExceptions || 0
  };
}

// Get processing statistics
async function getProcessingStats(supabase: any, dateRange: { start: string; end: string }): Promise<any> {
  // Get match results with processing times
  const { data: processingTimes } = await supabase
    .from('match_results')
    .select('processing_time_ms')
    .not('processing_time_ms', 'is', null)
    .gte('created_at', dateRange.start)
    .lte('created_at', dateRange.end);

  let avgProcessingTime = 0;
  if (processingTimes && processingTimes.length > 0) {
    const totalTime = processingTimes.reduce((sum, pt) => sum + (pt.processing_time_ms || 0), 0);
    avgProcessingTime = totalTime / processingTimes.length / 1000; // Convert to seconds
  }

  // Get today's invoice count
  const today = new Date().toISOString().split('T')[0];
  const { count: invoicesToday } = await supabase
    .from('invoices')
    .select('*', { count: 'exact', head: true })
    .gte('created_at', `${today}T00:00:00.000Z`)
    .lte('created_at', `${today}T23:59:59.999Z`);

  // Estimated cost per invoice (based on processing time and serverless costs)
  const estimatedCostPerInvoice = 0.007; // $0.007 based on our serverless architecture

  return {
    avg_processing_time_seconds: Math.round(avgProcessingTime * 100) / 100,
    cost_per_invoice: estimatedCostPerInvoice,
    invoices_processed_today: invoicesToday || 0
  };
}

// Get vendor statistics
async function getVendorStats(supabase: any): Promise<any> {
  // Total vendors
  const { count: totalVendors } = await supabase
    .from('vendors')
    .select('*', { count: 'exact', head: true })
    .eq('status', 'active');

  // Potential duplicates (from normalization table)
  const { count: duplicatesDetected } = await supabase
    .from('vendor_normalization')
    .select('*', { count: 'exact', head: true })
    .eq('status', 'pending');

  return {
    total: totalVendors || 0,
    duplicates_detected: duplicatesDetected || 0
  };
}

// Generate matching performance report
async function handleMatchingReport(
  supabase: any,
  url: URL,
  context: any
): Promise<Response> {
  const startDateStr = url.searchParams.get('start_date');
  const endDateStr = url.searchParams.get('end_date');
  const format = url.searchParams.get('format') || 'json';

  if (!startDateStr || !endDateStr) {
    throw new APIError('validation_failed', 'start_date and end_date are required', 400);
  }

  if (!validateDate(startDateStr) || !validateDate(endDateStr)) {
    throw new APIError('validation_failed', 'Invalid date format. Use YYYY-MM-DD', 400);
  }

  const startDate = new Date(startDateStr);
  const endDate = new Date(endDateStr);

  if (startDate > endDate) {
    throw new APIError('validation_failed', 'start_date must be before end_date', 400);
  }

  // Get comprehensive matching data
  const reportData = await generateMatchingPerformanceReport(supabase, startDate, endDate);

  // Return different formats
  switch (format) {
    case 'csv':
      return generateCSVReport(reportData);
    case 'pdf':
      return generatePDFReport(reportData);
    default:
      return createSuccessResponse(reportData);
  }
}

// Generate detailed matching performance report
async function generateMatchingPerformanceReport(
  supabase: any,
  startDate: Date,
  endDate: Date
): Promise<any> {
  const startDateStr = startDate.toISOString();
  const endDateStr = endDate.toISOString();

  // Get match results for the period
  const { data: matchResults } = await supabase
    .from('match_results')
    .select(`
      *,
      invoice:invoices(invoice_number, total_amount, invoice_date),
      match_exceptions(status, created_at, resolved_at)
    `)
    .gte('created_at', startDateStr)
    .lte('created_at', endDateStr)
    .order('created_at', { ascending: true });

  // Calculate summary metrics
  const totalInvoices = matchResults?.length || 0;
  const matchedInvoices = matchResults?.filter(mr => mr.match_status === 'matched').length || 0;
  const matchRate = totalInvoices > 0 ? (matchedInvoices / totalInvoices) * 100 : 0;
  
  const confidenceScores = matchResults?.map(mr => mr.overall_confidence).filter(Boolean) || [];
  const avgConfidence = confidenceScores.length > 0 
    ? confidenceScores.reduce((sum, score) => sum + score, 0) / confidenceScores.length
    : 0;

  const totalExceptions = matchResults?.flatMap(mr => mr.match_exceptions || []).length || 0;
  
  // Calculate resolution times for exceptions
  const resolvedExceptions = matchResults
    ?.flatMap(mr => mr.match_exceptions || [])
    .filter(ex => ex.resolved_at) || [];

  let avgResolutionTimeHours = 0;
  if (resolvedExceptions.length > 0) {
    const totalResolutionTime = resolvedExceptions.reduce((sum, ex) => {
      const createdAt = new Date(ex.created_at);
      const resolvedAt = new Date(ex.resolved_at);
      return sum + (resolvedAt.getTime() - createdAt.getTime());
    }, 0);
    avgResolutionTimeHours = totalResolutionTime / resolvedExceptions.length / (1000 * 60 * 60);
  }

  // Generate daily metrics
  const dailyMetrics = generateDailyMetrics(matchResults || [], startDate, endDate);

  return {
    period: {
      start_date: startDate.toISOString().split('T')[0],
      end_date: endDate.toISOString().split('T')[0]
    },
    summary: {
      total_invoices: totalInvoices,
      matched_invoices: matchedInvoices,
      match_rate: Math.round(matchRate * 100) / 100,
      avg_confidence: Math.round(avgConfidence * 100) / 100,
      total_exceptions: totalExceptions,
      avg_resolution_time_hours: Math.round(avgResolutionTimeHours * 100) / 100
    },
    daily_metrics: dailyMetrics
  };
}

// Generate daily metrics breakdown
function generateDailyMetrics(matchResults: any[], startDate: Date, endDate: Date): any[] {
  const dailyData: Record<string, any> = {};
  
  // Initialize all dates in range
  for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
    const dateStr = d.toISOString().split('T')[0];
    dailyData[dateStr] = {
      date: dateStr,
      invoices_processed: 0,
      match_rate: 0,
      exceptions_created: 0,
      exceptions_resolved: 0
    };
  }

  // Populate with actual data
  matchResults.forEach(mr => {
    const date = mr.created_at.split('T')[0];
    if (dailyData[date]) {
      dailyData[date].invoices_processed++;
      
      if (mr.match_status === 'matched') {
        dailyData[date].match_rate++;
      }
      
      if (mr.match_exceptions) {
        mr.match_exceptions.forEach((ex: any) => {
          const exDate = ex.created_at.split('T')[0];
          if (dailyData[exDate]) {
            dailyData[exDate].exceptions_created++;
          }
          
          if (ex.resolved_at) {
            const resolvedDate = ex.resolved_at.split('T')[0];
            if (dailyData[resolvedDate]) {
              dailyData[resolvedDate].exceptions_resolved++;
            }
          }
        });
      }
    }
  });

  // Calculate match rates
  Object.values(dailyData).forEach((day: any) => {
    if (day.invoices_processed > 0) {
      day.match_rate = Math.round((day.match_rate / day.invoices_processed) * 10000) / 100;
    }
  });

  return Object.values(dailyData);
}

// Generate CSV report
function generateCSVReport(reportData: any): Response {
  const csvHeader = 'Date,Invoices Processed,Match Rate %,Exceptions Created,Exceptions Resolved\n';
  const csvRows = reportData.daily_metrics
    .map((day: any) => 
      `${day.date},${day.invoices_processed},${day.match_rate},${day.exceptions_created},${day.exceptions_resolved}`
    )
    .join('\n');
  
  const csvContent = csvHeader + csvRows;

  return new Response(csvContent, {
    status: 200,
    headers: {
      'Content-Type': 'text/csv',
      'Content-Disposition': `attachment; filename="matching-report-${reportData.period.start_date}-to-${reportData.period.end_date}.csv"`
    }
  });
}

// Generate PDF report (placeholder - would use a PDF library in production)
function generatePDFReport(reportData: any): Response {
  // In production, this would generate an actual PDF using a library like jsPDF
  // For now, return a placeholder response
  
  const pdfContent = `Matching Performance Report
Period: ${reportData.period.start_date} to ${reportData.period.end_date}

Summary:
- Total Invoices: ${reportData.summary.total_invoices}
- Matched Invoices: ${reportData.summary.matched_invoices}
- Match Rate: ${reportData.summary.match_rate}%
- Average Confidence: ${reportData.summary.avg_confidence}%
- Total Exceptions: ${reportData.summary.total_exceptions}
- Average Resolution Time: ${reportData.summary.avg_resolution_time_hours} hours

[Daily metrics would be included in a table format]
`;

  return new Response(pdfContent, {
    status: 200,
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="matching-report-${reportData.period.start_date}-to-${reportData.period.end_date}.pdf"`
    }
  });
}

// Get date range based on period
function getDateRange(period: string): { start: string; end: string } {
  const now = new Date();
  const end = now.toISOString();
  let start: Date;

  switch (period) {
    case 'today':
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      break;
    case 'week':
      start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      break;
    case 'quarter':
      start = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
      break;
    case 'year':
      start = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
      break;
    default: // month
      start = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      break;
  }

  return {
    start: start.toISOString(),
    end
  };
}