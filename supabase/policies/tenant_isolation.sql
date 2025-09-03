-- Tenant Isolation Policies
-- Description: Comprehensive RLS policies for multi-tenant security
-- Created: 2025-01-03
-- Depends on: All migration files

-- =============================================================================
-- VENDORS TABLE POLICIES
-- =============================================================================

-- Select policy: Users can view vendors from their tenants
CREATE POLICY "tenant_vendors_select" ON public.vendors
  FOR SELECT
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Insert policy: Users can create vendors in their tenants
CREATE POLICY "tenant_vendors_insert" ON public.vendors
  FOR INSERT
  WITH CHECK (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
    )
  );

-- Update policy: Users can update vendors in their tenants
CREATE POLICY "tenant_vendors_update" ON public.vendors
  FOR UPDATE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
    )
  );

-- Delete policy: Only admins can delete vendors
CREATE POLICY "tenant_vendors_delete" ON public.vendors
  FOR DELETE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role = 'admin'
    )
  );

-- =============================================================================
-- PURCHASE ORDERS TABLE POLICIES
-- =============================================================================

-- Select policy
CREATE POLICY "tenant_purchase_orders_select" ON public.purchase_orders
  FOR SELECT
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Insert policy
CREATE POLICY "tenant_purchase_orders_insert" ON public.purchase_orders
  FOR INSERT
  WITH CHECK (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
    )
  );

-- Update policy
CREATE POLICY "tenant_purchase_orders_update" ON public.purchase_orders
  FOR UPDATE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
    )
  );

-- Delete policy
CREATE POLICY "tenant_purchase_orders_delete" ON public.purchase_orders
  FOR DELETE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
    )
  );

-- =============================================================================
-- PO LINE ITEMS TABLE POLICIES
-- =============================================================================

-- Select policy: Users can view line items for POs they can access
CREATE POLICY "tenant_po_line_items_select" ON public.po_line_items
  FOR SELECT
  USING (
    po_id IN (
      SELECT id FROM public.purchase_orders 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid()
      )
    )
  );

-- Insert policy
CREATE POLICY "tenant_po_line_items_insert" ON public.po_line_items
  FOR INSERT
  WITH CHECK (
    po_id IN (
      SELECT id FROM public.purchase_orders 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
      )
    )
  );

-- Update policy
CREATE POLICY "tenant_po_line_items_update" ON public.po_line_items
  FOR UPDATE
  USING (
    po_id IN (
      SELECT id FROM public.purchase_orders 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
      )
    )
  );

-- Delete policy
CREATE POLICY "tenant_po_line_items_delete" ON public.po_line_items
  FOR DELETE
  USING (
    po_id IN (
      SELECT id FROM public.purchase_orders 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
      )
    )
  );

-- =============================================================================
-- RECEIPTS TABLE POLICIES
-- =============================================================================

-- Select policy
CREATE POLICY "tenant_receipts_select" ON public.receipts
  FOR SELECT
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Insert policy
CREATE POLICY "tenant_receipts_insert" ON public.receipts
  FOR INSERT
  WITH CHECK (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
    )
  );

-- Update policy
CREATE POLICY "tenant_receipts_update" ON public.receipts
  FOR UPDATE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
    )
  );

-- Delete policy
CREATE POLICY "tenant_receipts_delete" ON public.receipts
  FOR DELETE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
    )
  );

-- =============================================================================
-- RECEIPT LINE ITEMS TABLE POLICIES
-- =============================================================================

-- Select policy
CREATE POLICY "tenant_receipt_line_items_select" ON public.receipt_line_items
  FOR SELECT
  USING (
    receipt_id IN (
      SELECT id FROM public.receipts 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid()
      )
    )
  );

-- Insert policy
CREATE POLICY "tenant_receipt_line_items_insert" ON public.receipt_line_items
  FOR INSERT
  WITH CHECK (
    receipt_id IN (
      SELECT id FROM public.receipts 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
      )
    )
  );

-- Update policy
CREATE POLICY "tenant_receipt_line_items_update" ON public.receipt_line_items
  FOR UPDATE
  USING (
    receipt_id IN (
      SELECT id FROM public.receipts 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
      )
    )
  );

-- Delete policy
CREATE POLICY "tenant_receipt_line_items_delete" ON public.receipt_line_items
  FOR DELETE
  USING (
    receipt_id IN (
      SELECT id FROM public.receipts 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
      )
    )
  );

-- =============================================================================
-- INVOICES TABLE POLICIES
-- =============================================================================

-- Select policy
CREATE POLICY "tenant_invoices_select" ON public.invoices
  FOR SELECT
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Insert policy
CREATE POLICY "tenant_invoices_insert" ON public.invoices
  FOR INSERT
  WITH CHECK (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
    )
  );

-- Update policy
CREATE POLICY "tenant_invoices_update" ON public.invoices
  FOR UPDATE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
    )
  );

-- Delete policy
CREATE POLICY "tenant_invoices_delete" ON public.invoices
  FOR DELETE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
    )
  );

-- =============================================================================
-- INVOICE LINE ITEMS TABLE POLICIES
-- =============================================================================

-- Select policy
CREATE POLICY "tenant_invoice_line_items_select" ON public.invoice_line_items
  FOR SELECT
  USING (
    invoice_id IN (
      SELECT id FROM public.invoices 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid()
      )
    )
  );

-- Insert policy
CREATE POLICY "tenant_invoice_line_items_insert" ON public.invoice_line_items
  FOR INSERT
  WITH CHECK (
    invoice_id IN (
      SELECT id FROM public.invoices 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
      )
    )
  );

-- Update policy
CREATE POLICY "tenant_invoice_line_items_update" ON public.invoice_line_items
  FOR UPDATE
  USING (
    invoice_id IN (
      SELECT id FROM public.invoices 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
      )
    )
  );

-- Delete policy
CREATE POLICY "tenant_invoice_line_items_delete" ON public.invoice_line_items
  FOR DELETE
  USING (
    invoice_id IN (
      SELECT id FROM public.invoices 
      WHERE tenant_id = public.get_current_tenant_id()
      AND tenant_id IN (
        SELECT tenant_id FROM public.tenant_users 
        WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
      )
    )
  );

-- =============================================================================
-- MATCHING RULES TABLE POLICIES
-- =============================================================================

-- Select policy
CREATE POLICY "tenant_matching_rules_select" ON public.matching_rules
  FOR SELECT
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Insert policy
CREATE POLICY "tenant_matching_rules_insert" ON public.matching_rules
  FOR INSERT
  WITH CHECK (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
    )
  );

-- Update policy
CREATE POLICY "tenant_matching_rules_update" ON public.matching_rules
  FOR UPDATE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
    )
  );

-- Delete policy
CREATE POLICY "tenant_matching_rules_delete" ON public.matching_rules
  FOR DELETE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role = 'admin'
    )
  );

-- =============================================================================
-- MATCH RESULTS TABLE POLICIES
-- =============================================================================

-- Select policy
CREATE POLICY "tenant_match_results_select" ON public.match_results
  FOR SELECT
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Insert policy (system only)
CREATE POLICY "tenant_match_results_insert" ON public.match_results
  FOR INSERT
  WITH CHECK (
    tenant_id = public.get_current_tenant_id()
  );

-- Update policy (for approval workflow)
CREATE POLICY "tenant_match_results_update" ON public.match_results
  FOR UPDATE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
    )
  );

-- =============================================================================
-- MATCH EXCEPTIONS TABLE POLICIES
-- =============================================================================

-- Select policy
CREATE POLICY "tenant_match_exceptions_select" ON public.match_exceptions
  FOR SELECT
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Insert policy
CREATE POLICY "tenant_match_exceptions_insert" ON public.match_exceptions
  FOR INSERT
  WITH CHECK (
    tenant_id = public.get_current_tenant_id()
  );

-- Update policy
CREATE POLICY "tenant_match_exceptions_update" ON public.match_exceptions
  FOR UPDATE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager', 'member')
    )
  );

-- =============================================================================
-- MATCHING AUDIT LOG TABLE POLICIES
-- =============================================================================

-- Select policy (read-only access)
CREATE POLICY "tenant_matching_audit_log_select" ON public.matching_audit_log
  FOR SELECT
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Insert policy (system only)
CREATE POLICY "tenant_matching_audit_log_insert" ON public.matching_audit_log
  FOR INSERT
  WITH CHECK (
    tenant_id = public.get_current_tenant_id()
  );

-- No update or delete policies for audit log (immutable)

-- =============================================================================
-- VENDOR NORMALIZATION TABLE POLICIES
-- =============================================================================

-- Select policy
CREATE POLICY "tenant_vendor_normalization_select" ON public.vendor_normalization
  FOR SELECT
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Insert policy
CREATE POLICY "tenant_vendor_normalization_insert" ON public.vendor_normalization
  FOR INSERT
  WITH CHECK (
    tenant_id = public.get_current_tenant_id()
  );

-- Update policy
CREATE POLICY "tenant_vendor_normalization_update" ON public.vendor_normalization
  FOR UPDATE
  USING (
    tenant_id = public.get_current_tenant_id()
    AND tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
    )
  );

-- =============================================================================
-- SERVICE ROLE BYPASS POLICIES
-- =============================================================================

-- Service role can bypass all RLS policies for system operations
CREATE POLICY "service_role_vendors_all" ON public.vendors
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_purchase_orders_all" ON public.purchase_orders
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_po_line_items_all" ON public.po_line_items
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_receipts_all" ON public.receipts
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_receipt_line_items_all" ON public.receipt_line_items
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_invoices_all" ON public.invoices
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_invoice_line_items_all" ON public.invoice_line_items
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_matching_rules_all" ON public.matching_rules
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_match_results_all" ON public.match_results
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_match_exceptions_all" ON public.match_exceptions
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_matching_audit_log_all" ON public.matching_audit_log
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "service_role_vendor_normalization_all" ON public.vendor_normalization
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');