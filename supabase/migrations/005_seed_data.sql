-- Migration: 005_seed_data.sql
-- Description: Seed data for development and testing
-- Created: 2025-01-03
-- Dependencies: 004_functions_triggers.sql

-- =============================================================================
-- DEVELOPMENT TENANT SETUP
-- =============================================================================

-- Insert demo tenants (already done in 001_tenant_setup.sql, but adding more detail)
UPDATE public.tenants 
SET 
  settings = jsonb_build_object(
    'theme', 'light',
    'timezone', 'America/New_York',
    'currency', 'USD',
    'date_format', 'MM/DD/YYYY',
    'fiscal_year_start', '01-01',
    'auto_matching_enabled', true,
    'require_po_matching', true,
    'approval_workflow_enabled', true
  ),
  metadata = jsonb_build_object(
    'industry', 'Technology',
    'company_size', 'Medium',
    'invoice_volume_monthly', 350
  )
WHERE slug = 'demo-corp';

UPDATE public.tenants 
SET 
  settings = jsonb_build_object(
    'theme', 'dark',
    'timezone', 'America/Los_Angeles', 
    'currency', 'USD',
    'date_format', 'YYYY-MM-DD',
    'fiscal_year_start', '07-01',
    'auto_matching_enabled', false,
    'require_po_matching', false,
    'approval_workflow_enabled', false
  ),
  metadata = jsonb_build_object(
    'industry', 'Manufacturing',
    'company_size', 'Small', 
    'invoice_volume_monthly', 125
  )
WHERE slug = 'test-company';

-- =============================================================================
-- DEMO VENDORS
-- =============================================================================

-- Insert demo vendors for demo-corp tenant
INSERT INTO public.vendors (tenant_id, name, email, phone, address_line_1, city, state_province, postal_code, tax_id, business_type, default_payment_terms, metadata) 
SELECT 
  t.id,
  vendor_data.name,
  vendor_data.email,
  vendor_data.phone,
  vendor_data.address_line_1,
  vendor_data.city,
  vendor_data.state_province,
  vendor_data.postal_code,
  vendor_data.tax_id,
  vendor_data.business_type,
  vendor_data.default_payment_terms,
  vendor_data.metadata
FROM public.tenants t
CROSS JOIN (
  VALUES 
    ('Acme Office Supplies Inc', 'accounting@acmeoffice.com', '+1-555-0101', '123 Business Ave', 'New York', 'NY', '10001', '12-3456789', 'corporation', 30, '{"category": "office_supplies", "preferred_contact": "email"}'),
    ('TechFlow Solutions LLC', 'billing@techflow.com', '+1-555-0102', '456 Innovation Dr', 'San Francisco', 'CA', '94105', '98-7654321', 'llc', 15, '{"category": "technology", "preferred_contact": "phone"}'),
    ('Global Logistics Corp', 'ap@globallogistics.com', '+1-555-0103', '789 Warehouse Blvd', 'Chicago', 'IL', '60601', '55-1234567', 'corporation', 45, '{"category": "logistics", "preferred_contact": "email"}'),
    ('Premier Marketing Group', 'invoices@premiermarketing.com', '+1-555-0104', '321 Creative St', 'Austin', 'TX', '78701', '44-9876543', 'llc', 30, '{"category": "marketing", "preferred_contact": "email"}'),
    ('Midwest Manufacturing Co', 'finance@midwestmfg.com', '+1-555-0105', '654 Industrial Way', 'Detroit', 'MI', '48201', '33-5678901', 'corporation', 60, '{"category": "manufacturing", "preferred_contact": "phone"}')
) AS vendor_data(name, email, phone, address_line_1, city, state_province, postal_code, tax_id, business_type, default_payment_terms, metadata)
WHERE t.slug = 'demo-corp';

-- =============================================================================
-- DEMO MATCHING RULES
-- =============================================================================

-- Insert default matching rules for demo-corp
INSERT INTO public.matching_rules (tenant_id, name, description, rule_type, field_name, tolerance_percentage, tolerance_absolute, priority, applies_to, auto_approve_threshold, metadata)
SELECT 
  t.id,
  rule_data.name,
  rule_data.description,
  rule_data.rule_type,
  rule_data.field_name,
  rule_data.tolerance_percentage,
  rule_data.tolerance_absolute,
  rule_data.priority,
  rule_data.applies_to,
  rule_data.auto_approve_threshold,
  rule_data.metadata
FROM public.tenants t
CROSS JOIN (
  VALUES 
    ('Exact Amount Match', 'Require exact amount matching for all documents', 'exact', 'amount', NULL, NULL, 1, ARRAY['invoice', 'po', 'receipt'], 100.0, '{"strict_matching": true}'),
    ('Standard Amount Tolerance', 'Allow 5% or $10 variance in amounts', 'tolerance', 'amount', 5.0, 10.0, 2, ARRAY['invoice', 'po'], 95.0, '{"applies_above_amount": 100.0}'),
    ('Date Tolerance - 7 Days', 'Allow 7-day variance in document dates', 'tolerance', 'date', NULL, NULL, 3, ARRAY['invoice', 'po', 'receipt'], 90.0, '{"tolerance_days": 7}'),
    ('Vendor Name Fuzzy Match', 'Allow fuzzy matching for vendor names', 'fuzzy', 'vendor_name', NULL, NULL, 4, ARRAY['invoice', 'po'], 85.0, '{"similarity_threshold": 80.0, "algorithm": "levenshtein"}'),
    ('PO Number Exact Match', 'Require exact PO number matching', 'exact', 'po_number', NULL, NULL, 5, ARRAY['invoice', 'po', 'receipt'], 100.0, '{"case_sensitive": false}'),
    ('Quantity Tolerance - 10%', 'Allow 10% variance in quantities', 'tolerance', 'quantity', 10.0, 5.0, 6, ARRAY['invoice', 'receipt'], 90.0, '{"applies_to_line_items": true}')
) AS rule_data(name, description, rule_type, field_name, tolerance_percentage, tolerance_absolute, priority, applies_to, auto_approve_threshold, metadata)
WHERE t.slug = 'demo-corp';

-- =============================================================================
-- DEMO PURCHASE ORDERS
-- =============================================================================

-- Insert demo purchase orders
DO $$
DECLARE
  demo_tenant_id UUID;
  vendor_ids UUID[];
  po_id UUID;
BEGIN
  -- Get demo tenant ID
  SELECT id INTO demo_tenant_id FROM public.tenants WHERE slug = 'demo-corp';
  
  -- Get vendor IDs for demo tenant
  SELECT ARRAY_AGG(id) INTO vendor_ids FROM public.vendors WHERE tenant_id = demo_tenant_id LIMIT 3;
  
  -- Insert PO 1
  INSERT INTO public.purchase_orders (tenant_id, po_number, vendor_id, po_date, expected_delivery_date, status, department, metadata)
  VALUES (demo_tenant_id, 'PO-2024-001', vendor_ids[1], '2024-12-01', '2024-12-15', 'approved', 'IT', '{"urgency": "normal", "project": "Office Upgrade"}')
  RETURNING id INTO po_id;
  
  -- Insert line items for PO 1
  INSERT INTO public.po_line_items (po_id, line_number, description, sku, quantity, unit_price, line_total)
  VALUES 
    (po_id, 1, 'Ergonomic Office Chairs', 'CHAIR-ERG-001', 10, 250.00, 2500.00),
    (po_id, 2, 'Standing Desks', 'DESK-STAND-002', 5, 600.00, 3000.00),
    (po_id, 3, 'Monitor Arms', 'ARM-MON-003', 10, 75.00, 750.00);
  
  -- Insert PO 2
  INSERT INTO public.purchase_orders (tenant_id, po_number, vendor_id, po_date, expected_delivery_date, status, department, metadata)
  VALUES (demo_tenant_id, 'PO-2024-002', vendor_ids[2], '2024-12-05', '2024-12-20', 'approved', 'Marketing', '{"urgency": "high", "campaign": "Q1 Launch"}')
  RETURNING id INTO po_id;
  
  -- Insert line items for PO 2
  INSERT INTO public.po_line_items (po_id, line_number, description, sku, quantity, unit_price, line_total)
  VALUES 
    (po_id, 1, 'Cloud Hosting Services', 'HOST-CLOUD-001', 3, 299.00, 897.00),
    (po_id, 2, 'SSL Certificates', 'SSL-CERT-002', 2, 99.00, 198.00);
    
  -- Insert PO 3
  INSERT INTO public.purchase_orders (tenant_id, po_number, vendor_id, po_date, expected_delivery_date, status, department, metadata)
  VALUES (demo_tenant_id, 'PO-2024-003', vendor_ids[3], '2024-12-10', '2024-12-25', 'pending', 'Operations', '{"urgency": "low", "budget_code": "OP-2024-Q4"}')
  RETURNING id INTO po_id;
  
  -- Insert line items for PO 3
  INSERT INTO public.po_line_items (po_id, line_number, description, sku, quantity, unit_price, line_total)
  VALUES 
    (po_id, 1, 'Shipping Labels', 'SHIP-LABEL-001', 1000, 0.15, 150.00),
    (po_id, 2, 'Packaging Materials', 'PKG-MAT-002', 50, 12.50, 625.00),
    (po_id, 3, 'Warehouse Equipment', 'WH-EQUIP-003', 2, 1250.00, 2500.00);
END $$;

-- =============================================================================
-- DEMO RECEIPTS
-- =============================================================================

-- Insert demo receipts for some of the POs
DO $$
DECLARE
  demo_tenant_id UUID;
  po_record RECORD;
  receipt_id UUID;
  line_record RECORD;
BEGIN
  -- Get demo tenant ID
  SELECT id INTO demo_tenant_id FROM public.tenants WHERE slug = 'demo-corp';
  
  -- Create receipts for approved POs
  FOR po_record IN 
    SELECT id, po_number, vendor_id FROM public.purchase_orders 
    WHERE tenant_id = demo_tenant_id AND status = 'approved'
    LIMIT 2
  LOOP
    -- Insert receipt
    INSERT INTO public.receipts (tenant_id, receipt_number, po_id, vendor_id, receipt_date, status, metadata)
    VALUES (
      demo_tenant_id, 
      'REC-' || REPLACE(po_record.po_number, 'PO-', ''), 
      po_record.id, 
      po_record.vendor_id, 
      CURRENT_DATE - INTERVAL '5 days',
      'accepted',
      '{"delivery_method": "truck", "condition": "good"}'
    )
    RETURNING id INTO receipt_id;
    
    -- Insert receipt line items based on PO line items
    FOR line_record IN
      SELECT line_number, description, sku, quantity, unit_price, line_total
      FROM public.po_line_items
      WHERE po_id = po_record.id
    LOOP
      INSERT INTO public.receipt_line_items (
        receipt_id, 
        line_number, 
        description, 
        sku, 
        quantity_received, 
        quantity_accepted,
        unit_price,
        line_total
      )
      VALUES (
        receipt_id,
        line_record.line_number,
        line_record.description,
        line_record.sku,
        line_record.quantity, -- Full quantity received
        line_record.quantity, -- Full quantity accepted
        line_record.unit_price,
        line_record.line_total
      );
    END LOOP;
  END LOOP;
END $$;

-- =============================================================================
-- DEMO INVOICES
-- =============================================================================

-- Insert demo invoices
DO $$
DECLARE
  demo_tenant_id UUID;
  po_record RECORD;
  invoice_id UUID;
  line_record RECORD;
BEGIN
  -- Get demo tenant ID
  SELECT id INTO demo_tenant_id FROM public.tenants WHERE slug = 'demo-corp';
  
  -- Create invoices for POs with receipts
  FOR po_record IN 
    SELECT DISTINCT po.id, po.po_number, po.vendor_id, po.total_amount
    FROM public.purchase_orders po
    INNER JOIN public.receipts r ON r.po_id = po.id
    WHERE po.tenant_id = demo_tenant_id
  LOOP
    -- Insert invoice
    INSERT INTO public.invoices (
      tenant_id, 
      invoice_number, 
      vendor_id, 
      po_id, 
      invoice_date, 
      due_date,
      received_date,
      status,
      matching_status,
      import_source,
      metadata
    )
    VALUES (
      demo_tenant_id,
      'INV-' || REPLACE(po_record.po_number, 'PO-', '') || '-001',
      po_record.vendor_id,
      po_record.id,
      CURRENT_DATE - INTERVAL '3 days',
      CURRENT_DATE + INTERVAL '27 days',
      CURRENT_DATE - INTERVAL '1 day',
      'pending',
      'unmatched',
      'manual',
      '{"payment_method": "check", "terms": "Net 30"}'
    )
    RETURNING id INTO invoice_id;
    
    -- Insert invoice line items based on PO line items with slight variations
    FOR line_record IN
      SELECT line_number, description, sku, quantity, unit_price, line_total
      FROM public.po_line_items
      WHERE po_id = po_record.id
    LOOP
      INSERT INTO public.invoice_line_items (
        invoice_id,
        line_number,
        description,
        sku,
        quantity,
        unit_price,
        line_total
      )
      VALUES (
        invoice_id,
        line_record.line_number,
        line_record.description,
        line_record.sku,
        line_record.quantity,
        -- Add small random variance to unit price for testing tolerances
        line_record.unit_price + (RANDOM() - 0.5) * line_record.unit_price * 0.02,
        -- Recalculate line total
        line_record.quantity * (line_record.unit_price + (RANDOM() - 0.5) * line_record.unit_price * 0.02)
      );
    END LOOP;
  END LOOP;
END $$;

-- =============================================================================
-- SAMPLE EXCEPTIONS FOR TESTING
-- =============================================================================

-- Create some sample exceptions for demo purposes
DO $$
DECLARE
  demo_tenant_id UUID;
  sample_invoice_id UUID;
  sample_po_id UUID;
  match_result_id UUID;
  exception_id UUID;
BEGIN
  -- Get demo tenant ID
  SELECT id INTO demo_tenant_id FROM public.tenants WHERE slug = 'demo-corp';
  
  -- Get a sample invoice and PO
  SELECT i.id, i.po_id INTO sample_invoice_id, sample_po_id 
  FROM public.invoices i 
  WHERE i.tenant_id = demo_tenant_id 
  LIMIT 1;
  
  IF sample_invoice_id IS NOT NULL THEN
    -- Create a match result with exception
    INSERT INTO public.match_results (
      tenant_id,
      invoice_id,
      po_id,
      match_type,
      match_status,
      overall_confidence,
      exception_type,
      variance_amount,
      approval_status,
      field_scores
    )
    VALUES (
      demo_tenant_id,
      sample_invoice_id,
      sample_po_id,
      '2way_po_invoice',
      'exception',
      75.50,
      'amount_variance',
      15.75,
      'pending',
      '{"vendor_score": 100, "amount_score": 65, "date_score": 90, "po_number_score": 100}'
    )
    RETURNING id INTO match_result_id;
    
    -- Create corresponding exception
    INSERT INTO public.match_exceptions (
      tenant_id,
      match_result_id,
      exception_type,
      severity,
      title,
      description,
      expected_value,
      actual_value,
      field_name,
      variance_amount,
      priority,
      status
    )
    VALUES (
      demo_tenant_id,
      match_result_id,
      'amount_variance',
      'medium',
      'Invoice Amount Variance',
      'Invoice total exceeds PO total by more than configured tolerance',
      '6250.00',
      '6265.75', 
      'total_amount',
      15.75,
      2,
      'open'
    );
  END IF;
END $$;

-- =============================================================================
-- UPDATE STATISTICS
-- =============================================================================

-- Refresh table statistics for better query planning
ANALYZE public.tenants;
ANALYZE public.vendors;
ANALYZE public.purchase_orders;
ANALYZE public.po_line_items;
ANALYZE public.receipts;
ANALYZE public.receipt_line_items;
ANALYZE public.invoices;
ANALYZE public.invoice_line_items;
ANALYZE public.matching_rules;
ANALYZE public.match_results;
ANALYZE public.match_exceptions;

-- Comment on seed data
COMMENT ON TABLE public.tenants IS 'Seeded with demo-corp and test-company for development';
COMMENT ON TABLE public.vendors IS 'Seeded with realistic vendor data for testing';
COMMENT ON TABLE public.matching_rules IS 'Seeded with standard matching rules for demo tenant';