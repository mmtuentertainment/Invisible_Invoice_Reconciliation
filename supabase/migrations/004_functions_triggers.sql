-- Migration: 004_functions_triggers.sql
-- Description: Stored procedures, functions, and triggers for business logic
-- Created: 2025-01-03
-- Dependencies: 003_matching_tables.sql

-- =============================================================================
-- VENDOR NORMALIZATION FUNCTIONS
-- =============================================================================

-- Function to normalize vendor names
CREATE OR REPLACE FUNCTION public.normalize_vendor_name(vendor_name TEXT)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  normalized TEXT;
BEGIN
  -- Start with original name
  normalized := TRIM(vendor_name);
  
  -- Convert to uppercase for consistency
  normalized := UPPER(normalized);
  
  -- Remove common punctuation but keep apostrophes
  normalized := REGEXP_REPLACE(normalized, '[^\w\s'']', '', 'g');
  
  -- Normalize common legal entity suffixes
  normalized := REGEXP_REPLACE(normalized, '\s+(INCORPORATED|INC\.?|CORPORATION|CORP\.?|COMPANY|CO\.?|LIMITED|LTD\.?|LLC|L\.L\.C\.?|LP|L\.P\.?|LLP|L\.L\.P\.?)$', '', 'i');
  
  -- Expand common abbreviations
  normalized := REGEXP_REPLACE(normalized, '\bCO\b', 'COMPANY', 'g');
  normalized := REGEXP_REPLACE(normalized, '\bCORP\b', 'CORPORATION', 'g');
  normalized := REGEXP_REPLACE(normalized, '\bINC\b', 'INCORPORATED', 'g');
  normalized := REGEXP_REPLACE(normalized, '\bLTD\b', 'LIMITED', 'g');
  normalized := REGEXP_REPLACE(normalized, '\b&\b', 'AND', 'g');
  
  -- Remove extra spaces
  normalized := REGEXP_REPLACE(normalized, '\s+', ' ', 'g');
  normalized := TRIM(normalized);
  
  RETURN normalized;
END;
$$;

-- Function to calculate vendor name similarity using Levenshtein distance
CREATE OR REPLACE FUNCTION public.vendor_name_similarity(name1 TEXT, name2 TEXT)
RETURNS DECIMAL(5,2)
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  norm1 TEXT;
  norm2 TEXT;
  max_len INTEGER;
  distance INTEGER;
  similarity DECIMAL(5,2);
BEGIN
  -- Normalize both names
  norm1 := public.normalize_vendor_name(name1);
  norm2 := public.normalize_vendor_name(name2);
  
  -- If names are identical after normalization
  IF norm1 = norm2 THEN
    RETURN 100.00;
  END IF;
  
  -- Calculate maximum length
  max_len := GREATEST(LENGTH(norm1), LENGTH(norm2));
  
  -- Avoid division by zero
  IF max_len = 0 THEN
    RETURN 100.00;
  END IF;
  
  -- Calculate Levenshtein distance
  distance := LEVENSHTEIN(norm1, norm2);
  
  -- Convert to similarity percentage
  similarity := ((max_len - distance)::DECIMAL / max_len) * 100;
  
  -- Ensure result is between 0 and 100
  RETURN GREATEST(0, LEAST(100, similarity));
END;
$$;

-- =============================================================================
-- MATCHING ENGINE FUNCTIONS
-- =============================================================================

-- Function to calculate amount tolerance match
CREATE OR REPLACE FUNCTION public.amount_within_tolerance(
  amount1 DECIMAL(15,4),
  amount2 DECIMAL(15,4),
  tolerance_percentage DECIMAL(5,2) DEFAULT 5.00,
  tolerance_absolute DECIMAL(15,4) DEFAULT 10.00
)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  difference DECIMAL(15,4);
  percentage_diff DECIMAL(8,5);
  base_amount DECIMAL(15,4);
BEGIN
  -- Calculate absolute difference
  difference := ABS(amount1 - amount2);
  
  -- Check absolute tolerance first
  IF difference <= tolerance_absolute THEN
    RETURN TRUE;
  END IF;
  
  -- Use larger amount as base for percentage calculation
  base_amount := GREATEST(ABS(amount1), ABS(amount2));
  
  -- Avoid division by zero
  IF base_amount = 0 THEN
    RETURN amount1 = amount2;
  END IF;
  
  -- Calculate percentage difference
  percentage_diff := (difference / base_amount) * 100;
  
  RETURN percentage_diff <= tolerance_percentage;
END;
$$;

-- Function to calculate date tolerance match
CREATE OR REPLACE FUNCTION public.date_within_tolerance(
  date1 DATE,
  date2 DATE,
  tolerance_days INTEGER DEFAULT 7
)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
  RETURN ABS(date1 - date2) <= tolerance_days;
END;
$$;

-- Function to calculate overall match confidence
CREATE OR REPLACE FUNCTION public.calculate_match_confidence(
  vendor_score DECIMAL(5,2) DEFAULT 0,
  amount_score DECIMAL(5,2) DEFAULT 0,
  date_score DECIMAL(5,2) DEFAULT 0,
  po_number_score DECIMAL(5,2) DEFAULT 0,
  invoice_number_score DECIMAL(5,2) DEFAULT 0
)
RETURNS DECIMAL(5,2)
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  weighted_score DECIMAL(8,5);
BEGIN
  -- Weighted scoring algorithm
  -- Vendor: 25%, Amount: 30%, PO Number: 20%, Invoice Number: 15%, Date: 10%
  weighted_score := 
    (vendor_score * 0.25) +
    (amount_score * 0.30) +
    (po_number_score * 0.20) +
    (invoice_number_score * 0.15) +
    (date_score * 0.10);
  
  RETURN LEAST(100.00, GREATEST(0.00, weighted_score));
END;
$$;

-- =============================================================================
-- INVOICE PROCESSING FUNCTIONS
-- =============================================================================

-- Function to update invoice totals from line items
CREATE OR REPLACE FUNCTION public.update_invoice_totals()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  new_subtotal DECIMAL(15,4);
  new_tax_amount DECIMAL(15,4);
  new_total DECIMAL(15,4);
BEGIN
  -- Calculate totals from line items
  SELECT 
    COALESCE(SUM(line_total), 0),
    COALESCE(SUM(tax_amount), 0)
  INTO 
    new_subtotal,
    new_tax_amount
  FROM public.invoice_line_items
  WHERE invoice_id = COALESCE(NEW.invoice_id, OLD.invoice_id);
  
  new_total := new_subtotal + new_tax_amount;
  
  -- Update the invoice
  UPDATE public.invoices
  SET 
    subtotal = new_subtotal,
    tax_amount = new_tax_amount,
    total_amount = new_total,
    updated_at = NOW()
  WHERE id = COALESCE(NEW.invoice_id, OLD.invoice_id);
  
  RETURN COALESCE(NEW, OLD);
END;
$$;

-- Function to update PO totals from line items
CREATE OR REPLACE FUNCTION public.update_po_totals()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  new_subtotal DECIMAL(15,4);
  new_total DECIMAL(15,4);
BEGIN
  -- Calculate totals from line items
  SELECT 
    COALESCE(SUM(line_total), 0)
  INTO 
    new_subtotal
  FROM public.po_line_items
  WHERE po_id = COALESCE(NEW.po_id, OLD.po_id);
  
  -- For POs, assume tax is calculated separately or included
  new_total := new_subtotal;
  
  -- Update the PO
  UPDATE public.purchase_orders
  SET 
    subtotal = new_subtotal,
    total_amount = new_total,
    updated_at = NOW()
  WHERE id = COALESCE(NEW.po_id, OLD.po_id);
  
  RETURN COALESCE(NEW, OLD);
END;
$$;

-- Function to update received quantities on PO line items
CREATE OR REPLACE FUNCTION public.update_po_received_quantities()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  total_received DECIMAL(10,4);
BEGIN
  -- Calculate total received quantity for the PO line item
  SELECT 
    COALESCE(SUM(quantity_received), 0)
  INTO 
    total_received
  FROM public.receipt_line_items
  WHERE po_line_item_id = COALESCE(NEW.po_line_item_id, OLD.po_line_item_id);
  
  -- Update the PO line item
  UPDATE public.po_line_items
  SET 
    quantity_received = total_received,
    updated_at = NOW()
  WHERE id = COALESCE(NEW.po_line_item_id, OLD.po_line_item_id);
  
  RETURN COALESCE(NEW, OLD);
END;
$$;

-- =============================================================================
-- AUDIT LOGGING FUNCTIONS
-- =============================================================================

-- Function to log matching events
CREATE OR REPLACE FUNCTION public.log_matching_event(
  p_tenant_id UUID,
  p_event_type TEXT,
  p_match_result_id UUID DEFAULT NULL,
  p_exception_id UUID DEFAULT NULL,
  p_invoice_id UUID DEFAULT NULL,
  p_po_id UUID DEFAULT NULL,
  p_receipt_id UUID DEFAULT NULL,
  p_event_data JSONB DEFAULT '{}',
  p_processing_time_ms INTEGER DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  audit_id UUID;
BEGIN
  INSERT INTO public.matching_audit_log (
    tenant_id,
    event_type,
    match_result_id,
    exception_id,
    invoice_id,
    po_id,
    receipt_id,
    user_id,
    event_data,
    processing_time_ms,
    correlation_id
  ) VALUES (
    p_tenant_id,
    p_event_type,
    p_match_result_id,
    p_exception_id,
    p_invoice_id,
    p_po_id,
    p_receipt_id,
    auth.uid(),
    p_event_data,
    p_processing_time_ms,
    uuid_generate_v4()
  ) RETURNING id INTO audit_id;
  
  RETURN audit_id;
END;
$$;

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Triggers for automatic total calculations
CREATE TRIGGER update_invoice_totals_trigger
  AFTER INSERT OR UPDATE OR DELETE ON public.invoice_line_items
  FOR EACH ROW
  EXECUTE FUNCTION public.update_invoice_totals();

CREATE TRIGGER update_po_totals_trigger
  AFTER INSERT OR UPDATE OR DELETE ON public.po_line_items
  FOR EACH ROW
  EXECUTE FUNCTION public.update_po_totals();

CREATE TRIGGER update_po_received_quantities_trigger
  AFTER INSERT OR UPDATE OR DELETE ON public.receipt_line_items
  FOR EACH ROW
  EXECUTE FUNCTION public.update_po_received_quantities();

-- Trigger to automatically normalize vendor names on insert/update
CREATE OR REPLACE FUNCTION public.auto_normalize_vendor_name()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.normalized_name := public.normalize_vendor_name(NEW.name);
  RETURN NEW;
END;
$$;

CREATE TRIGGER auto_normalize_vendor_name_trigger
  BEFORE INSERT OR UPDATE ON public.vendors
  FOR EACH ROW
  EXECUTE FUNCTION public.auto_normalize_vendor_name();

-- =============================================================================
-- UTILITY FUNCTIONS
-- =============================================================================

-- Function to get tenant statistics
CREATE OR REPLACE FUNCTION public.get_tenant_stats(p_tenant_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  stats JSONB;
BEGIN
  SELECT jsonb_build_object(
    'vendors', (SELECT COUNT(*) FROM public.vendors WHERE tenant_id = p_tenant_id),
    'invoices', jsonb_build_object(
      'total', (SELECT COUNT(*) FROM public.invoices WHERE tenant_id = p_tenant_id),
      'pending', (SELECT COUNT(*) FROM public.invoices WHERE tenant_id = p_tenant_id AND status = 'pending'),
      'matched', (SELECT COUNT(*) FROM public.invoices WHERE tenant_id = p_tenant_id AND matching_status = 'matched'),
      'exceptions', (SELECT COUNT(*) FROM public.invoices WHERE tenant_id = p_tenant_id AND matching_status = 'exception')
    ),
    'purchase_orders', (SELECT COUNT(*) FROM public.purchase_orders WHERE tenant_id = p_tenant_id),
    'receipts', (SELECT COUNT(*) FROM public.receipts WHERE tenant_id = p_tenant_id),
    'match_exceptions', jsonb_build_object(
      'open', (SELECT COUNT(*) FROM public.match_exceptions WHERE tenant_id = p_tenant_id AND status = 'open'),
      'in_review', (SELECT COUNT(*) FROM public.match_exceptions WHERE tenant_id = p_tenant_id AND status = 'in_review')
    )
  ) INTO stats;
  
  RETURN stats;
END;
$$;

-- Function to clean up old audit logs (for maintenance)
CREATE OR REPLACE FUNCTION public.cleanup_audit_logs(retention_days INTEGER DEFAULT 90)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM public.matching_audit_log
  WHERE event_timestamp < NOW() - (retention_days || ' days')::INTERVAL;
  
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  
  RETURN deleted_count;
END;
$$;

-- Comment on functions
COMMENT ON FUNCTION public.normalize_vendor_name(TEXT) IS 'Normalizes vendor names for deduplication';
COMMENT ON FUNCTION public.vendor_name_similarity(TEXT, TEXT) IS 'Calculates similarity percentage between vendor names';
COMMENT ON FUNCTION public.amount_within_tolerance(DECIMAL, DECIMAL, DECIMAL, DECIMAL) IS 'Checks if amounts are within tolerance';
COMMENT ON FUNCTION public.date_within_tolerance(DATE, DATE, INTEGER) IS 'Checks if dates are within tolerance';
COMMENT ON FUNCTION public.calculate_match_confidence(DECIMAL, DECIMAL, DECIMAL, DECIMAL, DECIMAL) IS 'Calculates weighted match confidence score';
COMMENT ON FUNCTION public.log_matching_event(UUID, TEXT, UUID, UUID, UUID, UUID, UUID, JSONB, INTEGER) IS 'Logs matching engine events for audit trail';
COMMENT ON FUNCTION public.get_tenant_stats(UUID) IS 'Returns comprehensive statistics for a tenant';
COMMENT ON FUNCTION public.cleanup_audit_logs(INTEGER) IS 'Removes old audit log entries for maintenance';