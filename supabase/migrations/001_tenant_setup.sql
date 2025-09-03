-- Migration: 001_tenant_setup.sql
-- Description: Multi-tenant foundation with RLS setup
-- Created: 2025-01-03
-- Dependencies: None

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create tenant management table
CREATE TABLE public.tenants (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  settings JSONB DEFAULT '{}',
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'inactive')),
  
  -- Subscription and limits
  plan TEXT DEFAULT 'starter' CHECK (plan IN ('starter', 'professional', 'enterprise')),
  max_invoices_per_month INTEGER DEFAULT 500,
  max_users INTEGER DEFAULT 5,
  
  -- Metadata
  metadata JSONB DEFAULT '{}'
);

-- Create tenant users table
CREATE TABLE public.tenant_users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL, -- References auth.users
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'manager', 'member', 'viewer')),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Permissions
  permissions JSONB DEFAULT '{}',
  
  -- Constraints
  UNIQUE(tenant_id, user_id)
);

-- Create function to get current tenant ID from JWT
CREATE OR REPLACE FUNCTION public.get_current_tenant_id()
RETURNS UUID
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
DECLARE
  tenant_id UUID;
BEGIN
  -- Get tenant_id from JWT claims
  tenant_id := (auth.jwt() ->> 'tenant_id')::UUID;
  
  -- Fallback to app.current_tenant setting if available
  IF tenant_id IS NULL THEN
    BEGIN
      tenant_id := current_setting('app.current_tenant')::UUID;
    EXCEPTION WHEN OTHERS THEN
      tenant_id := NULL;
    END;
  END IF;
  
  RETURN tenant_id;
END;
$$;

-- Create function to set tenant context (for admin operations)
CREATE OR REPLACE FUNCTION public.set_tenant_context(tenant_uuid UUID)
RETURNS VOID
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM set_config('app.current_tenant', tenant_uuid::TEXT, true);
END;
$$;

-- Create function to check if user has access to tenant
CREATE OR REPLACE FUNCTION public.user_has_tenant_access(user_uuid UUID, tenant_uuid UUID)
RETURNS BOOLEAN
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM public.tenant_users 
    WHERE user_id = user_uuid AND tenant_id = tenant_uuid
  );
END;
$$;

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

-- Add updated_at triggers
CREATE TRIGGER update_tenants_updated_at
  BEFORE UPDATE ON public.tenants
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_tenant_users_updated_at
  BEFORE UPDATE ON public.tenant_users
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

-- Enable RLS on all tenant tables
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_users ENABLE ROW LEVEL SECURITY;

-- Basic RLS policies for tenants table
CREATE POLICY "Users can view their tenants" ON public.tenants
  FOR SELECT
  USING (
    id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Basic RLS policies for tenant_users table
CREATE POLICY "Users can view tenant users for their tenants" ON public.tenant_users
  FOR SELECT
  USING (
    tenant_id IN (
      SELECT tenant_id FROM public.tenant_users 
      WHERE user_id = auth.uid()
    )
  );

-- Service role bypass (for admin operations)
CREATE POLICY "Service role can manage tenants" ON public.tenants
  FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Service role can manage tenant users" ON public.tenant_users
  FOR ALL
  USING (auth.role() = 'service_role');

-- Create indexes for performance
CREATE INDEX idx_tenants_slug ON public.tenants(slug);
CREATE INDEX idx_tenants_status ON public.tenants(status);
CREATE INDEX idx_tenant_users_tenant_id ON public.tenant_users(tenant_id);
CREATE INDEX idx_tenant_users_user_id ON public.tenant_users(user_id);
CREATE INDEX idx_tenant_users_role ON public.tenant_users(role);

-- Insert seed data for development
INSERT INTO public.tenants (name, slug, settings, plan, max_invoices_per_month, max_users) VALUES
('Demo Corporation', 'demo-corp', '{"theme": "light", "timezone": "America/New_York"}', 'professional', 1000, 10),
('Test Company LLC', 'test-company', '{"theme": "dark", "timezone": "America/Los_Angeles"}', 'starter', 500, 5);

-- Comment on tables and functions
COMMENT ON TABLE public.tenants IS 'Multi-tenant organization management';
COMMENT ON TABLE public.tenant_users IS 'User access control per tenant';
COMMENT ON FUNCTION public.get_current_tenant_id() IS 'Gets current tenant ID from JWT or session';
COMMENT ON FUNCTION public.set_tenant_context(UUID) IS 'Sets tenant context for admin operations';
COMMENT ON FUNCTION public.user_has_tenant_access(UUID, UUID) IS 'Checks if user has access to specific tenant';