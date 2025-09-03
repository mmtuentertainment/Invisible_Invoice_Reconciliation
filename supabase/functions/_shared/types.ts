// Shared TypeScript types for Supabase Edge Functions
// Created: 2025-01-03

// Database record types
export interface Database {
  public: {
    Tables: {
      tenants: {
        Row: {
          id: string;
          name: string;
          slug: string;
          created_at: string;
          updated_at: string;
          settings: Record<string, any>;
          status: 'active' | 'suspended' | 'inactive';
          plan: 'starter' | 'professional' | 'enterprise';
          max_invoices_per_month: number;
          max_users: number;
          metadata: Record<string, any>;
        };
        Insert: Omit<Database['public']['Tables']['tenants']['Row'], 'id' | 'created_at' | 'updated_at'>;
        Update: Partial<Database['public']['Tables']['tenants']['Insert']>;
      };
      vendors: {
        Row: {
          id: string;
          tenant_id: string;
          name: string;
          normalized_name: string;
          display_name: string | null;
          email: string | null;
          phone: string | null;
          website: string | null;
          address_line_1: string | null;
          address_line_2: string | null;
          city: string | null;
          state_province: string | null;
          postal_code: string | null;
          country: string;
          tax_id: string | null;
          business_type: 'corporation' | 'llc' | 'partnership' | 'sole_proprietorship' | 'other' | null;
          default_payment_terms: number;
          preferred_payment_method: 'check' | 'ach' | 'wire' | 'card' | 'other';
          status: 'active' | 'inactive' | 'blocked';
          is_1099_vendor: boolean;
          created_at: string;
          updated_at: string;
          created_by: string | null;
          metadata: Record<string, any>;
        };
        Insert: Omit<Database['public']['Tables']['vendors']['Row'], 'id' | 'created_at' | 'updated_at' | 'normalized_name'>;
        Update: Partial<Database['public']['Tables']['vendors']['Insert']>;
      };
      invoices: {
        Row: {
          id: string;
          tenant_id: string;
          invoice_number: string;
          vendor_id: string | null;
          po_id: string | null;
          subtotal: number;
          tax_amount: number;
          total_amount: number;
          currency: string;
          invoice_date: string;
          due_date: string | null;
          received_date: string;
          payment_terms: number;
          payment_status: 'unpaid' | 'partially_paid' | 'paid' | 'overpaid';
          payment_amount: number;
          payment_date: string | null;
          status: 'draft' | 'pending' | 'approved' | 'rejected' | 'paid' | 'cancelled';
          approval_status: 'pending' | 'approved' | 'rejected' | 'requires_review';
          matching_status: 'unmatched' | 'matched' | 'partially_matched' | 'exception';
          match_confidence: number | null;
          document_url: string | null;
          ocr_text: string | null;
          extraction_confidence: number | null;
          reference_number: string | null;
          department: string | null;
          project_code: string | null;
          approved_by: string | null;
          approved_at: string | null;
          approval_notes: string | null;
          import_batch_id: string | null;
          import_source: 'manual' | 'csv' | 'email' | 'api' | 'ocr' | null;
          created_at: string;
          updated_at: string;
          created_by: string | null;
          metadata: Record<string, any>;
        };
        Insert: Omit<Database['public']['Tables']['invoices']['Row'], 'id' | 'created_at' | 'updated_at'>;
        Update: Partial<Database['public']['Tables']['invoices']['Insert']>;
      };
      purchase_orders: {
        Row: {
          id: string;
          tenant_id: string;
          po_number: string;
          vendor_id: string | null;
          subtotal: number;
          tax_amount: number;
          total_amount: number;
          currency: string;
          po_date: string;
          expected_delivery_date: string | null;
          status: 'draft' | 'pending' | 'approved' | 'partially_received' | 'received' | 'closed' | 'cancelled';
          requisition_number: string | null;
          department: string | null;
          project_code: string | null;
          approved_by: string | null;
          approved_at: string | null;
          created_at: string;
          updated_at: string;
          created_by: string | null;
          metadata: Record<string, any>;
        };
        Insert: Omit<Database['public']['Tables']['purchase_orders']['Row'], 'id' | 'created_at' | 'updated_at'>;
        Update: Partial<Database['public']['Tables']['purchase_orders']['Insert']>;
      };
      match_results: {
        Row: {
          id: string;
          tenant_id: string;
          invoice_id: string | null;
          po_id: string | null;
          receipt_id: string | null;
          match_type: '2way_po_invoice' | '2way_po_receipt' | '2way_invoice_receipt' | '3way_full';
          match_status: 'matched' | 'exception' | 'partial' | 'failed';
          overall_confidence: number;
          field_scores: Record<string, any>;
          exception_type: string | null;
          exception_details: Record<string, any>;
          variance_amount: number | null;
          variance_percentage: number | null;
          approval_status: 'pending' | 'approved' | 'rejected' | 'auto_approved';
          approved_by: string | null;
          approved_at: string | null;
          approval_notes: string | null;
          matching_engine_version: string | null;
          processing_time_ms: number | null;
          rules_applied: string[];
          created_at: string;
          updated_at: string;
          metadata: Record<string, any>;
        };
        Insert: Omit<Database['public']['Tables']['match_results']['Row'], 'id' | 'created_at' | 'updated_at'>;
        Update: Partial<Database['public']['Tables']['match_results']['Insert']>;
      };
      match_exceptions: {
        Row: {
          id: string;
          tenant_id: string;
          match_result_id: string;
          exception_type: 'amount_variance' | 'quantity_variance' | 'date_variance' | 'vendor_mismatch' | 'missing_document' | 'duplicate' | 'approval_required' | 'system_error';
          severity: 'low' | 'medium' | 'high' | 'critical';
          title: string;
          description: string;
          expected_value: string | null;
          actual_value: string | null;
          field_name: string | null;
          variance_amount: number | null;
          variance_percentage: number | null;
          status: 'open' | 'in_review' | 'resolved' | 'dismissed' | 'escalated';
          resolution: 'approved' | 'rejected' | 'adjusted' | 'investigate' | null;
          resolution_notes: string | null;
          resolved_by: string | null;
          resolved_at: string | null;
          assigned_to: string | null;
          priority: number;
          due_date: string | null;
          escalated_from: string | null;
          escalated_to: string | null;
          escalation_reason: string | null;
          created_at: string;
          updated_at: string;
          metadata: Record<string, any>;
        };
        Insert: Omit<Database['public']['Tables']['match_exceptions']['Row'], 'id' | 'created_at' | 'updated_at'>;
        Update: Partial<Database['public']['Tables']['match_exceptions']['Insert']>;
      };
    };
  };
}

// API Request/Response types
export interface APIResponse<T = any> {
  data?: T;
  error?: APIError;
  pagination?: Pagination;
}

export interface APIError {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  correlationId: string;
  errors?: ValidationError[];
}

export interface ValidationError {
  field: string;
  message: string;
}

export interface Pagination {
  page: number;
  limit: number;
  total_pages: number;
  total_items: number;
  has_next: boolean;
  has_prev: boolean;
}

// Request types
export interface PaginationParams {
  page?: number;
  limit?: number;
  sort?: string;
}

export interface CreateInvoiceRequest {
  invoice_number: string;
  vendor_id: string;
  po_id?: string;
  subtotal?: number;
  tax_amount?: number;
  total_amount: number;
  currency?: string;
  invoice_date: string;
  due_date?: string;
  reference_number?: string;
  department?: string;
  line_items?: CreateInvoiceLineItemRequest[];
}

export interface CreateInvoiceLineItemRequest {
  line_number: number;
  description: string;
  sku?: string;
  quantity: number;
  unit_price: number;
  tax_rate?: number;
}

export interface CreateVendorRequest {
  name: string;
  email?: string;
  phone?: string;
  website?: string;
  address?: {
    line_1?: string;
    line_2?: string;
    city?: string;
    state_province?: string;
    postal_code?: string;
    country?: string;
  };
  tax_id?: string;
  business_type?: 'corporation' | 'llc' | 'partnership' | 'sole_proprietorship' | 'other';
  default_payment_terms?: number;
}

export interface CSVImportOptions {
  has_header?: boolean;
  delimiter?: ',' | ';' | '\t' | '|';
  skip_validation?: boolean;
  auto_match?: boolean;
}

export interface MatchingRequest {
  invoice_ids?: string[];
  auto_approve_threshold?: number;
}

export interface ResolveExceptionRequest {
  resolution: 'approved' | 'rejected' | 'investigate';
  notes?: string;
}

// Utility types
export type InvoiceStatus = 'draft' | 'pending' | 'approved' | 'rejected' | 'paid' | 'cancelled';
export type MatchingStatus = 'unmatched' | 'matched' | 'partially_matched' | 'exception';
export type VendorStatus = 'active' | 'inactive' | 'blocked';
export type ExceptionStatus = 'open' | 'in_review' | 'resolved' | 'dismissed' | 'escalated';
export type ExceptionSeverity = 'low' | 'medium' | 'high' | 'critical';

// Job status types
export interface ImportJob {
  job_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

export interface ImportJobStatus extends ImportJob {
  progress: {
    total_rows: number;
    processed_rows: number;
    successful_rows: number;
    failed_rows: number;
    warnings: number;
  };
  errors: Array<{
    row_number: number;
    field: string;
    message: string;
  }>;
  estimated_completion?: string;
}

// Context types
export interface FunctionContext {
  tenantId: string;
  userId: string;
  userRole: 'admin' | 'manager' | 'member' | 'viewer';
}

// ML Enhancement types
export interface MLMatchRequest {
  invoice_data: any;
  po_data: any;
  receipt_data?: any;
}

export interface MLMatchResponse {
  confidence_score: number;
  field_matches: Record<string, number>;
  recommendations: string[];
}

// Webhook types
export interface WebhookEvent {
  event_type: string;
  tenant_id: string;
  payload: any;
  timestamp: string;
}

// Health check types
export interface HealthCheck {
  status: 'healthy' | 'degraded' | 'unhealthy';
  timestamp: string;
  version: string;
  services: {
    database: ServiceHealth;
    functions: ServiceHealth;
    storage: ServiceHealth;
    auth: ServiceHealth;
  };
}

export interface ServiceHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  response_time_ms: number;
  last_check: string;
}