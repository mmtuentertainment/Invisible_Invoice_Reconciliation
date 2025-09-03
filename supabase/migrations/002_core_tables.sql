-- Migration: 002_core_tables.sql
-- Description: Core business tables (invoices, vendors, POs, receipts)
-- Created: 2025-01-03
-- Dependencies: 001_tenant_setup.sql

-- Vendors table
CREATE TABLE public.vendors (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Basic information
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL, -- For deduplication
  display_name TEXT, -- User-preferred display name
  
  -- Contact information
  email TEXT,
  phone TEXT,
  website TEXT,
  
  -- Address
  address_line_1 TEXT,
  address_line_2 TEXT,
  city TEXT,
  state_province TEXT,
  postal_code TEXT,
  country TEXT DEFAULT 'US',
  
  -- Business information
  tax_id TEXT, -- EIN, VAT, etc.
  business_type TEXT CHECK (business_type IN ('corporation', 'llc', 'partnership', 'sole_proprietorship', 'other')),
  
  -- Payment terms
  default_payment_terms INTEGER DEFAULT 30, -- Days
  preferred_payment_method TEXT DEFAULT 'check' CHECK (preferred_payment_method IN ('check', 'ach', 'wire', 'card', 'other')),
  
  -- Status and settings
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'blocked')),
  is_1099_vendor BOOLEAN DEFAULT false,
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_by UUID, -- References auth.users
  metadata JSONB DEFAULT '{}'
);

-- Purchase Orders table
CREATE TABLE public.purchase_orders (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- PO Information
  po_number TEXT NOT NULL,
  vendor_id UUID REFERENCES public.vendors(id) ON DELETE RESTRICT,
  
  -- Amounts
  subtotal DECIMAL(15,4) NOT NULL DEFAULT 0,
  tax_amount DECIMAL(15,4) NOT NULL DEFAULT 0,
  total_amount DECIMAL(15,4) NOT NULL DEFAULT 0,
  currency TEXT DEFAULT 'USD',
  
  -- Dates
  po_date DATE NOT NULL,
  expected_delivery_date DATE,
  
  -- Status
  status TEXT DEFAULT 'pending' CHECK (status IN ('draft', 'pending', 'approved', 'partially_received', 'received', 'closed', 'cancelled')),
  
  -- Reference information
  requisition_number TEXT,
  department TEXT,
  project_code TEXT,
  
  -- Approval workflow
  approved_by UUID, -- References auth.users
  approved_at TIMESTAMP WITH TIME ZONE,
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_by UUID, -- References auth.users
  metadata JSONB DEFAULT '{}',
  
  -- Constraints
  UNIQUE(tenant_id, po_number)
);

-- Purchase Order Line Items
CREATE TABLE public.po_line_items (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  po_id UUID NOT NULL REFERENCES public.purchase_orders(id) ON DELETE CASCADE,
  
  -- Line item details
  line_number INTEGER NOT NULL,
  description TEXT NOT NULL,
  sku TEXT,
  
  -- Quantities and pricing
  quantity DECIMAL(10,4) NOT NULL DEFAULT 0,
  unit_price DECIMAL(15,4) NOT NULL DEFAULT 0,
  line_total DECIMAL(15,4) NOT NULL DEFAULT 0,
  
  -- Receiving tracking
  quantity_received DECIMAL(10,4) NOT NULL DEFAULT 0,
  quantity_billed DECIMAL(10,4) NOT NULL DEFAULT 0,
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  metadata JSONB DEFAULT '{}',
  
  -- Constraints
  UNIQUE(po_id, line_number)
);

-- Receipts table
CREATE TABLE public.receipts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Receipt information
  receipt_number TEXT NOT NULL,
  po_id UUID REFERENCES public.purchase_orders(id) ON DELETE RESTRICT,
  vendor_id UUID REFERENCES public.vendors(id) ON DELETE RESTRICT,
  
  -- Dates
  receipt_date DATE NOT NULL,
  
  -- Status
  status TEXT DEFAULT 'received' CHECK (status IN ('received', 'inspected', 'accepted', 'rejected', 'returned')),
  
  -- Reference information
  delivery_note_number TEXT,
  carrier TEXT,
  tracking_number TEXT,
  
  -- Quality control
  inspection_notes TEXT,
  inspected_by UUID, -- References auth.users
  inspected_at TIMESTAMP WITH TIME ZONE,
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_by UUID, -- References auth.users
  metadata JSONB DEFAULT '{}',
  
  -- Constraints
  UNIQUE(tenant_id, receipt_number)
);

-- Receipt Line Items
CREATE TABLE public.receipt_line_items (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  receipt_id UUID NOT NULL REFERENCES public.receipts(id) ON DELETE CASCADE,
  po_line_item_id UUID REFERENCES public.po_line_items(id) ON DELETE RESTRICT,
  
  -- Line item details
  line_number INTEGER NOT NULL,
  description TEXT NOT NULL,
  sku TEXT,
  
  -- Quantities
  quantity_received DECIMAL(10,4) NOT NULL DEFAULT 0,
  quantity_accepted DECIMAL(10,4) NOT NULL DEFAULT 0,
  quantity_rejected DECIMAL(10,4) NOT NULL DEFAULT 0,
  
  -- Unit price for verification
  unit_price DECIMAL(15,4),
  line_total DECIMAL(15,4),
  
  -- Quality notes
  condition_notes TEXT,
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  metadata JSONB DEFAULT '{}',
  
  -- Constraints
  UNIQUE(receipt_id, line_number)
);

-- Invoices table
CREATE TABLE public.invoices (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Invoice information
  invoice_number TEXT NOT NULL,
  vendor_id UUID REFERENCES public.vendors(id) ON DELETE RESTRICT,
  po_id UUID REFERENCES public.purchase_orders(id) ON DELETE RESTRICT,
  
  -- Amounts
  subtotal DECIMAL(15,4) NOT NULL DEFAULT 0,
  tax_amount DECIMAL(15,4) NOT NULL DEFAULT 0,
  total_amount DECIMAL(15,4) NOT NULL DEFAULT 0,
  currency TEXT DEFAULT 'USD',
  
  -- Dates
  invoice_date DATE NOT NULL,
  due_date DATE,
  received_date DATE DEFAULT CURRENT_DATE,
  
  -- Payment information
  payment_terms INTEGER DEFAULT 30, -- Days
  payment_status TEXT DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid', 'partially_paid', 'paid', 'overpaid')),
  payment_amount DECIMAL(15,4) DEFAULT 0,
  payment_date DATE,
  
  -- Status and workflow
  status TEXT DEFAULT 'pending' CHECK (status IN ('draft', 'pending', 'approved', 'rejected', 'paid', 'cancelled')),
  approval_status TEXT DEFAULT 'pending' CHECK (approval_status IN ('pending', 'approved', 'rejected', 'requires_review')),
  
  -- Matching information
  matching_status TEXT DEFAULT 'unmatched' CHECK (matching_status IN ('unmatched', 'matched', 'partially_matched', 'exception')),
  match_confidence DECIMAL(5,2), -- 0.00 to 100.00
  
  -- Document handling
  document_url TEXT,
  ocr_text TEXT,
  extraction_confidence DECIMAL(5,2),
  
  -- Reference information
  reference_number TEXT,
  department TEXT,
  project_code TEXT,
  
  -- Approval workflow
  approved_by UUID, -- References auth.users
  approved_at TIMESTAMP WITH TIME ZONE,
  approval_notes TEXT,
  
  -- Import tracking
  import_batch_id UUID,
  import_source TEXT CHECK (import_source IN ('manual', 'csv', 'email', 'api', 'ocr')),
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_by UUID, -- References auth.users
  metadata JSONB DEFAULT '{}',
  
  -- Constraints
  UNIQUE(tenant_id, invoice_number, vendor_id)
);

-- Invoice Line Items
CREATE TABLE public.invoice_line_items (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  invoice_id UUID NOT NULL REFERENCES public.invoices(id) ON DELETE CASCADE,
  po_line_item_id UUID REFERENCES public.po_line_items(id) ON DELETE RESTRICT,
  
  -- Line item details
  line_number INTEGER NOT NULL,
  description TEXT NOT NULL,
  sku TEXT,
  
  -- Quantities and pricing
  quantity DECIMAL(10,4) NOT NULL DEFAULT 0,
  unit_price DECIMAL(15,4) NOT NULL DEFAULT 0,
  line_total DECIMAL(15,4) NOT NULL DEFAULT 0,
  
  -- Tax information
  tax_rate DECIMAL(8,5) DEFAULT 0,
  tax_amount DECIMAL(15,4) DEFAULT 0,
  
  -- Metadata
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  metadata JSONB DEFAULT '{}',
  
  -- Constraints
  UNIQUE(invoice_id, line_number)
);

-- Add updated_at triggers for all tables
CREATE TRIGGER update_vendors_updated_at
  BEFORE UPDATE ON public.vendors
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_purchase_orders_updated_at
  BEFORE UPDATE ON public.purchase_orders
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_po_line_items_updated_at
  BEFORE UPDATE ON public.po_line_items
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_receipts_updated_at
  BEFORE UPDATE ON public.receipts
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_receipt_line_items_updated_at
  BEFORE UPDATE ON public.receipt_line_items
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_invoices_updated_at
  BEFORE UPDATE ON public.invoices
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_invoice_line_items_updated_at
  BEFORE UPDATE ON public.invoice_line_items
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

-- Enable RLS on all tables
ALTER TABLE public.vendors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.po_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.receipt_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_line_items ENABLE ROW LEVEL SECURITY;

-- Performance indexes
CREATE INDEX idx_vendors_tenant_id ON public.vendors(tenant_id);
CREATE INDEX idx_vendors_normalized_name ON public.vendors(normalized_name);
CREATE INDEX idx_vendors_tax_id ON public.vendors(tax_id) WHERE tax_id IS NOT NULL;

CREATE INDEX idx_purchase_orders_tenant_id ON public.purchase_orders(tenant_id);
CREATE INDEX idx_purchase_orders_po_number ON public.purchase_orders(tenant_id, po_number);
CREATE INDEX idx_purchase_orders_vendor_id ON public.purchase_orders(vendor_id);
CREATE INDEX idx_purchase_orders_status ON public.purchase_orders(status);

CREATE INDEX idx_po_line_items_po_id ON public.po_line_items(po_id);

CREATE INDEX idx_receipts_tenant_id ON public.receipts(tenant_id);
CREATE INDEX idx_receipts_po_id ON public.receipts(po_id);
CREATE INDEX idx_receipts_vendor_id ON public.receipts(vendor_id);

CREATE INDEX idx_receipt_line_items_receipt_id ON public.receipt_line_items(receipt_id);
CREATE INDEX idx_receipt_line_items_po_line_item_id ON public.receipt_line_items(po_line_item_id);

CREATE INDEX idx_invoices_tenant_id ON public.invoices(tenant_id);
CREATE INDEX idx_invoices_invoice_number ON public.invoices(tenant_id, invoice_number, vendor_id);
CREATE INDEX idx_invoices_vendor_id ON public.invoices(vendor_id);
CREATE INDEX idx_invoices_po_id ON public.invoices(po_id);
CREATE INDEX idx_invoices_status ON public.invoices(status);
CREATE INDEX idx_invoices_matching_status ON public.invoices(matching_status);
CREATE INDEX idx_invoices_due_date ON public.invoices(due_date);
CREATE INDEX idx_invoices_import_batch ON public.invoices(import_batch_id) WHERE import_batch_id IS NOT NULL;

CREATE INDEX idx_invoice_line_items_invoice_id ON public.invoice_line_items(invoice_id);
CREATE INDEX idx_invoice_line_items_po_line_item_id ON public.invoice_line_items(po_line_item_id);

-- Comment on tables
COMMENT ON TABLE public.vendors IS 'Vendor master data with normalization';
COMMENT ON TABLE public.purchase_orders IS 'Purchase orders with approval workflow';
COMMENT ON TABLE public.po_line_items IS 'Purchase order line items';
COMMENT ON TABLE public.receipts IS 'Receipt records for goods received';
COMMENT ON TABLE public.receipt_line_items IS 'Receipt line items with quantity tracking';
COMMENT ON TABLE public.invoices IS 'Vendor invoices with matching status';
COMMENT ON TABLE public.invoice_line_items IS 'Invoice line items for detailed matching';