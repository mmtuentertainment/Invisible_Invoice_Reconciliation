-- Migration: 006_authentication_system.sql
-- Description: Comprehensive authentication and authorization system
-- Created: 2025-01-03
-- Dependencies: 001_tenant_setup.sql
-- Story: 1.2 - User Authentication & Authorization

-- Enable required extensions for authentication
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create enum types for authentication system
CREATE TYPE auth_status AS ENUM ('active', 'locked', 'suspended', 'inactive');
CREATE TYPE session_status AS ENUM ('active', 'expired', 'revoked');
CREATE TYPE mfa_method AS ENUM ('totp', 'sms', 'email');
CREATE TYPE auth_event_type AS ENUM (
  'login_success', 'login_failed', 'logout', 'password_changed', 
  'mfa_enabled', 'mfa_disabled', 'account_locked', 'account_unlocked',
  'session_created', 'session_expired', 'password_reset_requested',
  'password_reset_completed', 'suspicious_activity'
);

-- User authentication profiles (extends Supabase auth.users)
CREATE TABLE public.user_profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Profile information
  full_name TEXT,
  display_name TEXT,
  avatar_url TEXT,
  phone TEXT,
  
  -- Authentication settings
  auth_status auth_status DEFAULT 'active',
  password_changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  last_login TIMESTAMP WITH TIME ZONE,
  failed_login_attempts INTEGER DEFAULT 0,
  account_locked_until TIMESTAMP WITH TIME ZONE,
  
  -- Password history tracking
  password_history JSONB DEFAULT '[]', -- Store hashed password history
  
  -- MFA settings
  mfa_enabled BOOLEAN DEFAULT FALSE,
  mfa_secret TEXT, -- TOTP secret (encrypted)
  mfa_backup_codes TEXT[], -- Encrypted recovery codes
  mfa_methods mfa_method[] DEFAULT '{}',
  mfa_verified_at TIMESTAMP WITH TIME ZONE,
  
  -- Device trust
  trusted_devices JSONB DEFAULT '[]',
  
  -- Audit trail
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_by UUID REFERENCES auth.users(id),
  updated_by UUID REFERENCES auth.users(id),
  
  -- Constraints
  UNIQUE(tenant_id, id),
  CHECK (char_length(full_name) <= 255),
  CHECK (char_length(display_name) <= 100),
  CHECK (failed_login_attempts >= 0),
  CHECK (array_length(password_history::TEXT[], 1) <= 5) -- Max 5 password history
);

-- Roles and permissions system
CREATE TABLE public.roles (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  
  -- Role definition
  name TEXT NOT NULL,
  display_name TEXT NOT NULL,
  description TEXT,
  
  -- Permissions (JSONB for flexibility)
  permissions JSONB NOT NULL DEFAULT '{}',
  
  -- Hierarchy
  parent_role_id UUID REFERENCES public.roles(id),
  level INTEGER DEFAULT 0, -- For hierarchy ordering
  
  -- System roles vs custom roles
  is_system_role BOOLEAN DEFAULT FALSE,
  is_active BOOLEAN DEFAULT TRUE,
  
  -- Audit trail
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_by UUID REFERENCES auth.users(id),
  updated_by UUID REFERENCES auth.users(id),
  
  -- Constraints
  UNIQUE(tenant_id, name),
  CHECK (char_length(name) <= 50),
  CHECK (char_length(display_name) <= 100),
  CHECK (level >= 0 AND level <= 10)
);

-- User role assignments
CREATE TABLE public.user_roles (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  role_id UUID NOT NULL REFERENCES public.roles(id) ON DELETE CASCADE,
  
  -- Assignment details
  granted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  granted_by UUID NOT NULL REFERENCES auth.users(id),
  expires_at TIMESTAMP WITH TIME ZONE, -- Optional role expiration
  
  -- Status
  is_active BOOLEAN DEFAULT TRUE,
  
  -- Audit trail
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  revoked_at TIMESTAMP WITH TIME ZONE,
  revoked_by UUID REFERENCES auth.users(id),
  
  -- Constraints
  UNIQUE(tenant_id, user_id, role_id),
  CHECK (expires_at IS NULL OR expires_at > granted_at)
);

-- User sessions management
CREATE TABLE public.user_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  
  -- Session details
  session_token TEXT NOT NULL UNIQUE,
  refresh_token TEXT UNIQUE,
  
  -- Session metadata
  ip_address INET NOT NULL,
  user_agent TEXT,
  device_fingerprint TEXT,
  device_name TEXT,
  location JSONB, -- Country, city, etc.
  
  -- Session timing
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
  last_accessed TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Session status
  status session_status DEFAULT 'active',
  terminated_at TIMESTAMP WITH TIME ZONE,
  terminated_by UUID REFERENCES auth.users(id),
  termination_reason TEXT,
  
  -- Security flags
  is_trusted_device BOOLEAN DEFAULT FALSE,
  requires_mfa BOOLEAN DEFAULT TRUE,
  mfa_verified BOOLEAN DEFAULT FALSE,
  
  -- Constraints
  CHECK (expires_at > created_at),
  CHECK (status = 'active' OR terminated_at IS NOT NULL)
);

-- Authentication attempts tracking
CREATE TABLE public.auth_attempts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- Attempt details
  user_id UUID REFERENCES public.user_profiles(id),
  email TEXT,
  ip_address INET NOT NULL,
  user_agent TEXT,
  
  -- Attempt result
  success BOOLEAN NOT NULL,
  failure_reason TEXT,
  
  -- MFA details
  mfa_required BOOLEAN DEFAULT FALSE,
  mfa_success BOOLEAN,
  mfa_method mfa_method,
  
  -- Timing
  attempted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Location and risk scoring
  location JSONB,
  risk_score INTEGER DEFAULT 0 CHECK (risk_score >= 0 AND risk_score <= 100),
  
  -- Additional metadata
  metadata JSONB DEFAULT '{}'
);

-- Security audit log
CREATE TABLE public.security_audit_log (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID REFERENCES public.tenants(id),
  user_id UUID REFERENCES public.user_profiles(id),
  
  -- Event details
  event_type auth_event_type NOT NULL,
  event_description TEXT NOT NULL,
  
  -- Context
  ip_address INET,
  user_agent TEXT,
  resource_type TEXT,
  resource_id TEXT,
  
  -- Event data
  event_data JSONB DEFAULT '{}',
  
  -- Risk assessment
  risk_level TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
  
  -- Timing
  occurred_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Additional metadata
  metadata JSONB DEFAULT '{}'
);

-- Password reset tokens
CREATE TABLE public.password_reset_tokens (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  
  -- Token details
  token_hash TEXT NOT NULL UNIQUE,
  
  -- Timing
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
  used_at TIMESTAMP WITH TIME ZONE,
  
  -- Request context
  ip_address INET NOT NULL,
  user_agent TEXT,
  
  -- Status
  is_used BOOLEAN DEFAULT FALSE,
  
  -- Constraints
  CHECK (expires_at > created_at),
  CHECK (NOT is_used OR used_at IS NOT NULL)
);

-- Rate limiting tracking
CREATE TABLE public.rate_limits (
  id TEXT PRIMARY KEY, -- Composite key: endpoint:identifier
  
  -- Rate limit details
  endpoint TEXT NOT NULL,
  identifier TEXT NOT NULL, -- IP, user_id, etc.
  
  -- Counts and timing
  request_count INTEGER DEFAULT 1,
  window_start TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Rate limit status
  is_blocked BOOLEAN DEFAULT FALSE,
  blocked_until TIMESTAMP WITH TIME ZONE,
  
  -- Metadata
  last_request TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  metadata JSONB DEFAULT '{}'
);

-- Create updated_at triggers for all tables
CREATE TRIGGER update_user_profiles_updated_at
  BEFORE UPDATE ON public.user_profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_roles_updated_at
  BEFORE UPDATE ON public.roles
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

-- Enable RLS on all authentication tables
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auth_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.security_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.password_reset_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rate_limits ENABLE ROW LEVEL SECURITY;

-- RLS Policies for user_profiles
CREATE POLICY "Users can view own profile" ON public.user_profiles
  FOR SELECT
  USING (id = auth.uid());

CREATE POLICY "Users can update own profile" ON public.user_profiles
  FOR UPDATE
  USING (id = auth.uid());

CREATE POLICY "Tenant admins can view tenant user profiles" ON public.user_profiles
  FOR SELECT
  USING (
    tenant_id IN (
      SELECT ur.tenant_id FROM public.user_roles ur
      JOIN public.roles r ON ur.role_id = r.id
      WHERE ur.user_id = auth.uid()
      AND ur.is_active = TRUE
      AND r.name IN ('admin', 'manager')
      AND ur.tenant_id = user_profiles.tenant_id
    )
  );

-- RLS Policies for roles
CREATE POLICY "Users can view roles in their tenants" ON public.roles
  FOR SELECT
  USING (
    tenant_id IN (
      SELECT tenant_id FROM public.user_profiles
      WHERE id = auth.uid()
    )
  );

-- RLS Policies for user_roles
CREATE POLICY "Users can view their own roles" ON public.user_roles
  FOR SELECT
  USING (user_id = auth.uid());

-- RLS Policies for user_sessions
CREATE POLICY "Users can view own sessions" ON public.user_sessions
  FOR SELECT
  USING (user_id = auth.uid());

-- Service role bypass for all tables
CREATE POLICY "Service role bypass user_profiles" ON public.user_profiles
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role bypass roles" ON public.roles
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role bypass user_roles" ON public.user_roles
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role bypass user_sessions" ON public.user_sessions
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role bypass auth_attempts" ON public.auth_attempts
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role bypass security_audit_log" ON public.security_audit_log
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role bypass password_reset_tokens" ON public.password_reset_tokens
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role bypass rate_limits" ON public.rate_limits
  FOR ALL USING (auth.role() = 'service_role');

-- Create performance indexes
CREATE INDEX idx_user_profiles_tenant_id ON public.user_profiles(tenant_id);
CREATE INDEX idx_user_profiles_auth_status ON public.user_profiles(auth_status);
CREATE INDEX idx_user_profiles_last_login ON public.user_profiles(last_login);
CREATE INDEX idx_user_profiles_mfa_enabled ON public.user_profiles(mfa_enabled);

CREATE INDEX idx_roles_tenant_id ON public.roles(tenant_id);
CREATE INDEX idx_roles_name ON public.roles(tenant_id, name);
CREATE INDEX idx_roles_parent ON public.roles(parent_role_id);
CREATE INDEX idx_roles_system ON public.roles(is_system_role) WHERE is_system_role = TRUE;

CREATE INDEX idx_user_roles_tenant_user ON public.user_roles(tenant_id, user_id);
CREATE INDEX idx_user_roles_role ON public.user_roles(role_id);
CREATE INDEX idx_user_roles_active ON public.user_roles(is_active) WHERE is_active = TRUE;

CREATE INDEX idx_user_sessions_user ON public.user_sessions(user_id);
CREATE INDEX idx_user_sessions_token ON public.user_sessions(session_token);
CREATE INDEX idx_user_sessions_status ON public.user_sessions(status) WHERE status = 'active';
CREATE INDEX idx_user_sessions_expires ON public.user_sessions(expires_at);
CREATE INDEX idx_user_sessions_ip ON public.user_sessions(ip_address);

CREATE INDEX idx_auth_attempts_user ON public.auth_attempts(user_id);
CREATE INDEX idx_auth_attempts_ip ON public.auth_attempts(ip_address);
CREATE INDEX idx_auth_attempts_time ON public.auth_attempts(attempted_at);
CREATE INDEX idx_auth_attempts_success ON public.auth_attempts(success);

CREATE INDEX idx_security_audit_tenant ON public.security_audit_log(tenant_id);
CREATE INDEX idx_security_audit_user ON public.security_audit_log(user_id);
CREATE INDEX idx_security_audit_type ON public.security_audit_log(event_type);
CREATE INDEX idx_security_audit_time ON public.security_audit_log(occurred_at);
CREATE INDEX idx_security_audit_risk ON public.security_audit_log(risk_level);

CREATE INDEX idx_password_reset_user ON public.password_reset_tokens(user_id);
CREATE INDEX idx_password_reset_token ON public.password_reset_tokens(token_hash);
CREATE INDEX idx_password_reset_expires ON public.password_reset_tokens(expires_at);

CREATE INDEX idx_rate_limits_endpoint ON public.rate_limits(endpoint);
CREATE INDEX idx_rate_limits_identifier ON public.rate_limits(identifier);
CREATE INDEX idx_rate_limits_window ON public.rate_limits(window_start);
CREATE INDEX idx_rate_limits_blocked ON public.rate_limits(is_blocked) WHERE is_blocked = TRUE;

-- Insert default system roles for each existing tenant
INSERT INTO public.roles (tenant_id, name, display_name, description, permissions, is_system_role, level)
SELECT 
  t.id,
  'admin',
  'Administrator',
  'Full system access with all permissions',
  '{"system": ["*"], "invoice": ["*"], "vendor": ["*"], "report": ["*"], "user": ["*"], "tenant": ["*"]}',
  TRUE,
  0
FROM public.tenants t;

INSERT INTO public.roles (tenant_id, name, display_name, description, permissions, is_system_role, level)
SELECT 
  t.id,
  'manager',
  'Manager',
  'Management access to invoices, vendors, and reports',
  '{"invoice": ["*"], "vendor": ["manage"], "report": ["*"], "user": ["view", "manage"]}',
  TRUE,
  1
FROM public.tenants t;

INSERT INTO public.roles (tenant_id, name, display_name, description, permissions, is_system_role, level)
SELECT 
  t.id,
  'processor',
  'Processor',
  'Process invoices and manage vendor data',
  '{"invoice": ["create", "read", "update"], "vendor": ["create", "read", "update"], "report": ["view"]}',
  TRUE,
  2
FROM public.tenants t;

INSERT INTO public.roles (tenant_id, name, display_name, description, permissions, is_system_role, level)
SELECT 
  t.id,
  'viewer',
  'Viewer',
  'Read-only access to invoices and reports',
  '{"invoice": ["read"], "vendor": ["read"], "report": ["view"]}',
  TRUE,
  3
FROM public.tenants t;

-- Create helper functions for authentication

-- Function to get user permissions
CREATE OR REPLACE FUNCTION public.get_user_permissions(user_uuid UUID, tenant_uuid UUID)
RETURNS JSONB
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
DECLARE
  permissions JSONB := '{}';
  role_permissions JSONB;
BEGIN
  -- Aggregate permissions from all active roles
  FOR role_permissions IN
    SELECT r.permissions
    FROM public.user_roles ur
    JOIN public.roles r ON ur.role_id = r.id
    WHERE ur.user_id = user_uuid
    AND ur.tenant_id = tenant_uuid
    AND ur.is_active = TRUE
    AND r.is_active = TRUE
    AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
  LOOP
    -- Merge permissions (simple union for now)
    permissions := permissions || role_permissions;
  END LOOP;
  
  RETURN permissions;
END;
$$;

-- Function to check specific permission
CREATE OR REPLACE FUNCTION public.has_permission(
  user_uuid UUID,
  tenant_uuid UUID,
  resource TEXT,
  action TEXT
)
RETURNS BOOLEAN
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
DECLARE
  user_permissions JSONB;
  resource_permissions JSONB;
BEGIN
  -- Get user permissions
  user_permissions := public.get_user_permissions(user_uuid, tenant_uuid);
  
  -- Check if user has system-level access
  IF user_permissions->>'system' = '*' OR user_permissions->'system' ? '*' THEN
    RETURN TRUE;
  END IF;
  
  -- Get resource-specific permissions
  resource_permissions := user_permissions->resource;
  
  -- Check for wildcard or specific action
  RETURN (
    resource_permissions = '"*"' OR
    resource_permissions ? '*' OR
    resource_permissions ? action
  );
END;
$$;

-- Function to clean expired sessions
CREATE OR REPLACE FUNCTION public.cleanup_expired_sessions()
RETURNS INTEGER
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
DECLARE
  cleaned_count INTEGER;
BEGIN
  UPDATE public.user_sessions 
  SET status = 'expired',
      terminated_at = NOW(),
      termination_reason = 'expired'
  WHERE status = 'active' 
  AND expires_at < NOW();
  
  GET DIAGNOSTICS cleaned_count = ROW_COUNT;
  RETURN cleaned_count;
END;
$$;

-- Function to clean old audit logs (keep last 90 days)
CREATE OR REPLACE FUNCTION public.cleanup_old_audit_logs()
RETURNS INTEGER
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM public.security_audit_log
  WHERE occurred_at < NOW() - INTERVAL '90 days';
  
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$;

-- Add table comments
COMMENT ON TABLE public.user_profiles IS 'User authentication profiles extending Supabase auth.users';
COMMENT ON TABLE public.roles IS 'Role-based access control roles with hierarchical permissions';
COMMENT ON TABLE public.user_roles IS 'User to role assignments with expiration support';
COMMENT ON TABLE public.user_sessions IS 'Session management with device tracking and security controls';
COMMENT ON TABLE public.auth_attempts IS 'Authentication attempt tracking for security monitoring';
COMMENT ON TABLE public.security_audit_log IS 'Comprehensive security event audit log';
COMMENT ON TABLE public.password_reset_tokens IS 'Secure password reset token management';
COMMENT ON TABLE public.rate_limits IS 'Rate limiting tracking for abuse prevention';

COMMENT ON FUNCTION public.get_user_permissions(UUID, UUID) IS 'Get aggregated permissions for user in tenant';
COMMENT ON FUNCTION public.has_permission(UUID, UUID, TEXT, TEXT) IS 'Check if user has specific permission';
COMMENT ON FUNCTION public.cleanup_expired_sessions() IS 'Clean up expired user sessions';
COMMENT ON FUNCTION public.cleanup_old_audit_logs() IS 'Clean up audit logs older than 90 days';