-- Migration: 003_matching_tables.sql
-- Description: 3-way matching engine tables and audit trail
-- Created: 2025-01-03
-- Dependencies: 002_core_tables.sql

-- Matching rules configuration table
CREATE TABLE public.matching_rules (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Rule identification
  name TEXT NOT NULL,
  description TEXT,
  rule_type TEXT NOT NULL CHECK (rule_type IN ('exact', 'tolerance', 'fuzzy')),
  
  -- Rule configuration
  field_name TEXT NOT NULL, -- 'amount', 'quantity', 'date', 'vendor_name', etc.
  tolerance_percentage DECIMAL(5,2), -- For percentage-based tolerances
  tolerance_absolute DECIMAL(15,4), -- For absolute tolerances
  tolerance_days INTEGER, -- For date tolerances
  
  -- Fuzzy matching configuration
  similarity_threshold DECIMAL(5,2), -- 0.00 to 100.00
  algorithm TEXT CHECK (algorithm IN ('levenshtein', 'soundex', 'metaphone', 'jaro_winkler')),
  
  -- Rule priority and application
  priority INTEGER DEFAULT 10, -- Lower numbers = higher priority
  is_active BOOLEAN DEFAULT true,
  applies_to TEXT[] DEFAULT '{}', -- Array of document types: 'invoice', 'po', 'receipt'
  
  -- Vendor-specific overrides
  vendor_id UUID REFERENCES public.vendors(id) ON DELETE CASCADE, -- NULL = global rule
  vendor_category TEXT, -- For category-based rules
  
  -- Amount thresholds
  min_amount DECIMAL(15,4), -- Rule only applies above this amount
  max_amount DECIMAL(15,4), -- Rule only applies below this amount
  
  -- Auto-approval settings
  auto_approve_threshold DECIMAL(5,2) DEFAULT 85.00, -- Auto-approve if confidence above this
  requires_review_threshold DECIMAL(5,2) DEFAULT 70.00, -- Require review if below this
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_by UUID, -- References auth.users
  metadata JSONB DEFAULT '{}',
  
  -- Constraints
  UNIQUE(tenant_id, name)
);

-- Match results table
CREATE TABLE public.match_results (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Documents being matched
  invoice_id UUID REFERENCES public.invoices(id) ON DELETE CASCADE,
  po_id UUID REFERENCES public.purchase_orders(id) ON DELETE CASCADE,
  receipt_id UUID REFERENCES public.receipts(id) ON DELETE CASCADE,
  
  -- Match type and result
  match_type TEXT NOT NULL CHECK (match_type IN ('2way_po_invoice', '2way_po_receipt', '2way_invoice_receipt', '3way_full')),
  match_status TEXT NOT NULL CHECK (match_status IN ('matched', 'exception', 'partial', 'failed')),
  
  -- Confidence and scoring
  overall_confidence DECIMAL(5,2) NOT NULL, -- 0.00 to 100.00
  field_scores JSONB DEFAULT '{}', -- Individual field match scores
  
  -- Exception information
  exception_type TEXT CHECK (exception_type IN ('amount_variance', 'quantity_variance', 'date_variance', 'vendor_mismatch', 'missing_document', 'duplicate', 'other')),
  exception_details JSONB DEFAULT '{}',
  variance_amount DECIMAL(15,4), -- Amount variance (positive or negative)
  variance_percentage DECIMAL(8,5), -- Percentage variance
  
  -- Approval workflow
  approval_status TEXT DEFAULT 'pending' CHECK (approval_status IN ('pending', 'approved', 'rejected', 'auto_approved')),
  approved_by UUID, -- References auth.users
  approved_at TIMESTAMP WITH TIME ZONE,
  approval_notes TEXT,
  
  -- Processing information
  matching_engine_version TEXT,
  processing_time_ms INTEGER, -- Time taken to process this match
  rules_applied UUID[], -- Array of matching_rules.id that were applied
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  metadata JSONB DEFAULT '{}'
);

-- Match exceptions queue
CREATE TABLE public.match_exceptions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Related match result
  match_result_id UUID NOT NULL REFERENCES public.match_results(id) ON DELETE CASCADE,
  
  -- Exception details
  exception_type TEXT NOT NULL CHECK (exception_type IN ('amount_variance', 'quantity_variance', 'date_variance', 'vendor_mismatch', 'missing_document', 'duplicate', 'approval_required', 'system_error')),
  severity TEXT DEFAULT 'medium' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  
  -- Exception data
  expected_value TEXT,
  actual_value TEXT,
  field_name TEXT,
  variance_amount DECIMAL(15,4),
  variance_percentage DECIMAL(8,5),
  
  -- Resolution
  status TEXT DEFAULT 'open' CHECK (status IN ('open', 'in_review', 'resolved', 'dismissed', 'escalated')),
  resolution TEXT CHECK (resolution IN ('approved', 'rejected', 'adjusted', 'investigate')),
  resolution_notes TEXT,
  resolved_by UUID, -- References auth.users
  resolved_at TIMESTAMP WITH TIME ZONE,
  
  -- Assignment and priority
  assigned_to UUID, -- References auth.users
  priority INTEGER DEFAULT 3 CHECK (priority BETWEEN 1 AND 5), -- 1 = highest, 5 = lowest
  due_date TIMESTAMP WITH TIME ZONE,
  
  -- Escalation
  escalated_from UUID REFERENCES public.match_exceptions(id) ON DELETE SET NULL,
  escalated_to UUID REFERENCES public.match_exceptions(id) ON DELETE SET NULL,
  escalation_reason TEXT,
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  metadata JSONB DEFAULT '{}'
);

-- Audit trail for all matching activities
CREATE TABLE public.matching_audit_log (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Event information
  event_type TEXT NOT NULL CHECK (event_type IN ('match_attempt', 'match_success', 'match_failure', 'exception_created', 'exception_resolved', 'approval_granted', 'approval_denied', 'rule_applied', 'manual_override')),
  event_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Related records
  match_result_id UUID REFERENCES public.match_results(id) ON DELETE CASCADE,
  exception_id UUID REFERENCES public.match_exceptions(id) ON DELETE CASCADE,
  invoice_id UUID REFERENCES public.invoices(id) ON DELETE CASCADE,
  po_id UUID REFERENCES public.purchase_orders(id) ON DELETE CASCADE,
  receipt_id UUID REFERENCES public.receipts(id) ON DELETE CASCADE,
  
  -- User and system information
  user_id UUID, -- References auth.users (NULL for system events)
  session_id TEXT,
  ip_address INET,
  user_agent TEXT,
  
  -- Event details
  event_data JSONB DEFAULT '{}',
  before_values JSONB DEFAULT '{}',
  after_values JSONB DEFAULT '{}',
  
  -- Processing metadata
  processing_time_ms INTEGER,
  system_version TEXT,
  correlation_id UUID, -- For tracking related events
  
  -- Metadata
  metadata JSONB DEFAULT '{}'
);

-- Vendor normalization table for deduplication
CREATE TABLE public.vendor_normalization (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Original and normalized names
  original_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  confidence DECIMAL(5,2) NOT NULL, -- 0.00 to 100.00
  
  -- Normalization details
  normalization_rules TEXT[], -- Rules applied: 'remove_punctuation', 'expand_abbreviations', etc.
  similarity_score DECIMAL(5,2), -- If matched to existing vendor
  
  -- Canonical vendor
  canonical_vendor_id UUID REFERENCES public.vendors(id) ON DELETE CASCADE,
  
  -- Status
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'merged')),
  reviewed_by UUID, -- References auth.users
  reviewed_at TIMESTAMP WITH TIME ZONE,
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  metadata JSONB DEFAULT '{}',
  
  -- Constraints
  UNIQUE(tenant_id, original_name)
);

-- Add updated_at triggers
CREATE TRIGGER update_matching_rules_updated_at
  BEFORE UPDATE ON public.matching_rules
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_match_results_updated_at
  BEFORE UPDATE ON public.match_results
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_match_exceptions_updated_at
  BEFORE UPDATE ON public.match_exceptions
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_vendor_normalization_updated_at
  BEFORE UPDATE ON public.vendor_normalization
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

-- Enable RLS
ALTER TABLE public.matching_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.match_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.match_exceptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.matching_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vendor_normalization ENABLE ROW LEVEL SECURITY;

-- Performance indexes
CREATE INDEX idx_matching_rules_tenant_id ON public.matching_rules(tenant_id);
CREATE INDEX idx_matching_rules_active ON public.matching_rules(tenant_id, is_active) WHERE is_active = true;
CREATE INDEX idx_matching_rules_priority ON public.matching_rules(priority);
CREATE INDEX idx_matching_rules_vendor_id ON public.matching_rules(vendor_id) WHERE vendor_id IS NOT NULL;

CREATE INDEX idx_match_results_tenant_id ON public.match_results(tenant_id);
CREATE INDEX idx_match_results_invoice_id ON public.match_results(invoice_id);
CREATE INDEX idx_match_results_po_id ON public.match_results(po_id);
CREATE INDEX idx_match_results_receipt_id ON public.match_results(receipt_id);
CREATE INDEX idx_match_results_status ON public.match_results(match_status);
CREATE INDEX idx_match_results_approval_status ON public.match_results(approval_status);
CREATE INDEX idx_match_results_confidence ON public.match_results(overall_confidence);

CREATE INDEX idx_match_exceptions_tenant_id ON public.match_exceptions(tenant_id);
CREATE INDEX idx_match_exceptions_match_result_id ON public.match_exceptions(match_result_id);
CREATE INDEX idx_match_exceptions_status ON public.match_exceptions(status);
CREATE INDEX idx_match_exceptions_priority ON public.match_exceptions(priority);
CREATE INDEX idx_match_exceptions_assigned_to ON public.match_exceptions(assigned_to) WHERE assigned_to IS NOT NULL;
CREATE INDEX idx_match_exceptions_due_date ON public.match_exceptions(due_date) WHERE due_date IS NOT NULL;

CREATE INDEX idx_matching_audit_log_tenant_id ON public.matching_audit_log(tenant_id);
CREATE INDEX idx_matching_audit_log_timestamp ON public.matching_audit_log(event_timestamp);
CREATE INDEX idx_matching_audit_log_event_type ON public.matching_audit_log(event_type);
CREATE INDEX idx_matching_audit_log_match_result_id ON public.matching_audit_log(match_result_id) WHERE match_result_id IS NOT NULL;
CREATE INDEX idx_matching_audit_log_user_id ON public.matching_audit_log(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_matching_audit_log_correlation_id ON public.matching_audit_log(correlation_id) WHERE correlation_id IS NOT NULL;

CREATE INDEX idx_vendor_normalization_tenant_id ON public.vendor_normalization(tenant_id);
CREATE INDEX idx_vendor_normalization_original_name ON public.vendor_normalization(tenant_id, original_name);
CREATE INDEX idx_vendor_normalization_normalized_name ON public.vendor_normalization(normalized_name);
CREATE INDEX idx_vendor_normalization_canonical_vendor_id ON public.vendor_normalization(canonical_vendor_id) WHERE canonical_vendor_id IS NOT NULL;
CREATE INDEX idx_vendor_normalization_status ON public.vendor_normalization(status);

-- Full-text search index for vendor names
CREATE INDEX idx_vendors_name_fts ON public.vendors USING gin(to_tsvector('english', name || ' ' || COALESCE(normalized_name, '')));

-- Comment on tables
COMMENT ON TABLE public.matching_rules IS 'Configurable rules for 3-way matching engine';
COMMENT ON TABLE public.match_results IS 'Results of matching attempts with confidence scores';
COMMENT ON TABLE public.match_exceptions IS 'Exception queue for manual review and resolution';
COMMENT ON TABLE public.matching_audit_log IS 'Complete audit trail of all matching activities';
COMMENT ON TABLE public.vendor_normalization IS 'Vendor name normalization for deduplication';