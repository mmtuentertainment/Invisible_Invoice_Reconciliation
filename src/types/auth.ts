/**
 * TypeScript types for authentication system
 * Defines interfaces for user authentication, authorization, and session management
 */

export interface User {
  id: string;
  tenant_id: string;
  email: string;
  full_name?: string;
  display_name?: string;
  avatar_url?: string;
  phone?: string;
  auth_status: 'active' | 'locked' | 'suspended' | 'inactive';
  last_login?: string;
  mfa_enabled: boolean;
  mfa_methods: string[];
  created_at: string;
  updated_at: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
  mfa_token?: string;
  device_name?: string;
  remember_device?: boolean;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
  requires_mfa: boolean;
  mfa_methods: string[];
}

export interface MfaRequiredResponse {
  requires_mfa: true;
  mfa_methods: string[];
  user_id: string;
  tenant_id: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  expires_at: number;
}

export interface MfaSetupData {
  secret: string;
  qr_code: string;
  backup_codes: string[];
}

export interface UserSession {
  id: string;
  device_name?: string;
  ip_address: string;
  created_at: string;
  last_accessed: string;
  expires_at: string;
  is_trusted_device: boolean;
  status: string;
}

export interface PasswordStrengthResult {
  score: number;
  is_valid: boolean;
  errors: string[];
  suggestions: string[];
}

export interface Role {
  id: string;
  name: string;
  display_name: string;
  description?: string;
  permissions: Record<string, string[]>;
  level: number;
  is_system_role: boolean;
  is_active: boolean;
  created_at: string;
}

export interface UserRole {
  id: string;
  user_id: string;
  role_id: string;
  role: Role;
  granted_at: string;
  granted_by: string;
  expires_at?: string;
  is_active: boolean;
}

export interface PermissionCheck {
  allowed: boolean;
  reason?: string;
  required_permissions: string[];
  user_permissions: string[];
}

// Authentication state
export interface AuthState {
  user: User | null;
  tokens: AuthTokens | null;
  permissions: string[];
  isAuthenticated: boolean;
  isLoading: boolean;
  mfaPending: boolean;
  mfaData: MfaRequiredResponse | null;
}

// Authentication actions
export type AuthAction =
  | { type: 'AUTH_START' }
  | { type: 'AUTH_SUCCESS'; payload: { user: User; tokens: AuthTokens; permissions: string[] } }
  | { type: 'AUTH_FAILURE'; payload: { error: string } }
  | { type: 'AUTH_LOGOUT' }
  | { type: 'MFA_REQUIRED'; payload: MfaRequiredResponse }
  | { type: 'MFA_SUCCESS'; payload: { user: User; tokens: AuthTokens; permissions: string[] } }
  | { type: 'TOKEN_REFRESH'; payload: { tokens: AuthTokens } }
  | { type: 'USER_UPDATE'; payload: { user: User } };

// API Error types
export interface ApiError {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  errors?: Array<{
    field: string;
    message: string;
    value?: any;
  }>;
}

// Form validation types
export interface ValidationError {
  field: string;
  message: string;
}

export interface FormState<T> {
  data: T;
  errors: ValidationError[];
  isSubmitting: boolean;
  isDirty: boolean;
}

// Device information
export interface DeviceInfo {
  fingerprint: string;
  name?: string;
  trusted: boolean;
  last_used: string;
}

// Security settings
export interface SecuritySettings {
  mfa_enabled: boolean;
  trusted_devices: DeviceInfo[];
  password_last_changed: string;
  failed_attempts: number;
  account_locked_until?: string;
}

// Audit log entry
export interface AuditLogEntry {
  id: string;
  event_type: string;
  event_description: string;
  ip_address?: string;
  resource_type?: string;
  resource_id?: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  occurred_at: string;
  event_data: Record<string, any>;
  metadata: Record<string, any>;
}

// Security metrics
export interface SecurityMetrics {
  total_events: number;
  events_by_type: Record<string, number>;
  events_by_risk_level: Record<string, number>;
  failed_logins_24h: number;
  locked_accounts: number;
  suspicious_activities: number;
  top_risk_ips: Array<{
    ip_address: string;
    event_count: number;
    max_risk_level: string;
  }>;
}

// Component prop types
export interface AuthProviderProps {
  children: React.ReactNode;
}

export interface ProtectedRouteProps {
  children: React.ReactNode;
  permissions?: string[];
  roles?: string[];
  fallback?: React.ComponentType;
}

export interface LoginFormProps {
  onSuccess?: (user: User) => void;
  onMfaRequired?: (data: MfaRequiredResponse) => void;
  redirectTo?: string;
}

export interface MfaFormProps {
  mfaData: MfaRequiredResponse;
  onSuccess?: (user: User) => void;
  onCancel?: () => void;
}

export interface PasswordChangeFormProps {
  onSuccess?: () => void;
  onCancel?: () => void;
}

export interface MfaSetupFormProps {
  onSuccess?: () => void;
  onCancel?: () => void;
}

// Hook return types
export interface UseAuthReturn {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  mfaPending: boolean;
  mfaData: MfaRequiredResponse | null;
  permissions: string[];
  login: (credentials: LoginCredentials) => Promise<void>;
  logout: (allDevices?: boolean) => Promise<void>;
  verifyMfa: (token: string) => Promise<void>;
  refreshToken: () => Promise<void>;
  updateProfile: (data: Partial<User>) => Promise<void>;
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (permissions: string[]) => boolean;
  hasAllPermissions: (permissions: string[]) => boolean;
}

export interface UsePasswordReturn {
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  requestReset: (email: string) => Promise<void>;
  confirmReset: (token: string, newPassword: string) => Promise<void>;
  checkStrength: (password: string) => Promise<PasswordStrengthResult>;
  isLoading: boolean;
  error: string | null;
}

export interface UseMfaReturn {
  setup: () => Promise<MfaSetupData>;
  enable: (verificationCode: string) => Promise<void>;
  disable: (password: string, verificationCode: string) => Promise<void>;
  isLoading: boolean;
  error: string | null;
}

export interface UseSessionsReturn {
  sessions: UserSession[];
  terminateSession: (sessionId: string) => Promise<void>;
  terminateAllSessions: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  isLoading: boolean;
  error: string | null;
}