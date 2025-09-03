/**
 * Authentication context provider for React application
 * Manages global authentication state with comprehensive security features
 */

'use client';

import React, { createContext, useContext, useReducer, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { 
  User, 
  AuthState, 
  AuthAction, 
  LoginCredentials, 
  MfaRequiredResponse,
  AuthTokens,
  UseAuthReturn,
  AuthProviderProps
} from '@/types/auth';
import { authService } from '@/services/auth';

// Initial state
const initialState: AuthState = {
  user: null,
  tokens: null,
  permissions: [],
  isAuthenticated: false,
  isLoading: true,
  mfaPending: false,
  mfaData: null,
};

// Auth reducer
function authReducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case 'AUTH_START':
      return {
        ...state,
        isLoading: true,
        mfaPending: false,
        mfaData: null,
      };

    case 'AUTH_SUCCESS':
      return {
        ...state,
        user: action.payload.user,
        tokens: action.payload.tokens,
        permissions: action.payload.permissions,
        isAuthenticated: true,
        isLoading: false,
        mfaPending: false,
        mfaData: null,
      };

    case 'AUTH_FAILURE':
      return {
        ...state,
        user: null,
        tokens: null,
        permissions: [],
        isAuthenticated: false,
        isLoading: false,
        mfaPending: false,
        mfaData: null,
      };

    case 'MFA_REQUIRED':
      return {
        ...state,
        isLoading: false,
        mfaPending: true,
        mfaData: action.payload,
      };

    case 'MFA_SUCCESS':
      return {
        ...state,
        user: action.payload.user,
        tokens: action.payload.tokens,
        permissions: action.payload.permissions,
        isAuthenticated: true,
        isLoading: false,
        mfaPending: false,
        mfaData: null,
      };

    case 'TOKEN_REFRESH':
      return {
        ...state,
        tokens: action.payload.tokens,
      };

    case 'USER_UPDATE':
      return {
        ...state,
        user: action.payload.user,
      };

    case 'AUTH_LOGOUT':
      return {
        ...initialState,
        isLoading: false,
      };

    default:
      return state;
  }
}

// Create context
const AuthContext = createContext<UseAuthReturn | undefined>(undefined);

// Provider component
export function AuthProvider({ children }: AuthProviderProps) {
  const [state, dispatch] = useReducer(authReducer, initialState);
  const router = useRouter();

  /**
   * Initialize authentication state on mount
   */
  const initializeAuth = useCallback(async () => {
    try {
      const accessToken = authService.getAccessToken();
      
      if (!accessToken) {
        dispatch({ type: 'AUTH_FAILURE', payload: { error: 'No token found' } });
        return;
      }

      // Check if token is expired
      if (authService.isTokenExpired()) {
        try {
          const tokens = await authService.refreshTokens();
          dispatch({ type: 'TOKEN_REFRESH', payload: { tokens } });
        } catch (error) {
          console.warn('Token refresh failed:', error);
          authService.clearTokens();
          dispatch({ type: 'AUTH_FAILURE', payload: { error: 'Token refresh failed' } });
          return;
        }
      }

      // Get current user
      const user = await authService.getCurrentUser();
      
      // Extract permissions from user data (simplified)
      const permissions: string[] = []; // Would be populated from user roles/permissions
      
      const tokens: AuthTokens = {
        access_token: authService.getAccessToken() || '',
        refresh_token: '', // Not exposed to context
        expires_at: parseInt(localStorage.getItem('expires_at') || '0', 10),
      };

      dispatch({
        type: 'AUTH_SUCCESS',
        payload: { user, tokens, permissions },
      });
    } catch (error) {
      console.error('Auth initialization failed:', error);
      authService.clearTokens();
      dispatch({ type: 'AUTH_FAILURE', payload: { error: 'Auth initialization failed' } });
    }
  }, []);

  /**
   * Login user with credentials
   */
  const login = useCallback(async (credentials: LoginCredentials) => {
    dispatch({ type: 'AUTH_START' });

    try {
      const result = await authService.login(credentials);

      // Check if MFA is required
      if ('requires_mfa' in result && result.requires_mfa) {
        dispatch({
          type: 'MFA_REQUIRED',
          payload: result as MfaRequiredResponse,
        });
        return;
      }

      // Login successful
      const loginResponse = result as any; // Type assertion for successful login
      const permissions: string[] = []; // Would extract from response

      const tokens: AuthTokens = {
        access_token: loginResponse.access_token,
        refresh_token: loginResponse.refresh_token,
        expires_at: Date.now() + (loginResponse.expires_in * 1000),
      };

      dispatch({
        type: 'AUTH_SUCCESS',
        payload: {
          user: loginResponse.user,
          tokens,
          permissions,
        },
      });

      // Redirect after successful login
      router.push('/dashboard');
    } catch (error) {
      dispatch({
        type: 'AUTH_FAILURE',
        payload: { error: error instanceof Error ? error.message : 'Login failed' },
      });
      throw error;
    }
  }, [router]);

  /**
   * Verify MFA token
   */
  const verifyMfa = useCallback(async (token: string) => {
    if (!state.mfaData) {
      throw new Error('No MFA data available');
    }

    try {
      const credentials: LoginCredentials = {
        email: '', // Would be stored from initial login attempt
        password: '', // Would be stored from initial login attempt
        mfa_token: token,
      };

      const result = await authService.verifyMfa({
        ...credentials,
        user_id: state.mfaData.user_id,
        tenant_id: state.mfaData.tenant_id,
      });

      const permissions: string[] = []; // Would extract from response

      const tokens: AuthTokens = {
        access_token: result.access_token,
        refresh_token: result.refresh_token,
        expires_at: Date.now() + (result.expires_in * 1000),
      };

      dispatch({
        type: 'MFA_SUCCESS',
        payload: {
          user: result.user,
          tokens,
          permissions,
        },
      });

      router.push('/dashboard');
    } catch (error) {
      throw error;
    }
  }, [state.mfaData, router]);

  /**
   * Logout user
   */
  const logout = useCallback(async (allDevices: boolean = false) => {
    try {
      await authService.logout(allDevices);
    } catch (error) {
      console.warn('Logout request failed:', error);
    } finally {
      dispatch({ type: 'AUTH_LOGOUT' });
      router.push('/login');
    }
  }, [router]);

  /**
   * Refresh authentication token
   */
  const refreshToken = useCallback(async () => {
    try {
      const tokens = await authService.refreshTokens();
      dispatch({ type: 'TOKEN_REFRESH', payload: { tokens } });
    } catch (error) {
      console.error('Token refresh failed:', error);
      await logout();
      throw error;
    }
  }, [logout]);

  /**
   * Update user profile
   */
  const updateProfile = useCallback(async (data: Partial<User>) => {
    try {
      const updatedUser = await authService.updateProfile({
        full_name: data.full_name,
        display_name: data.display_name,
        phone: data.phone,
      });

      dispatch({ type: 'USER_UPDATE', payload: { user: updatedUser } });
    } catch (error) {
      throw error;
    }
  }, []);

  /**
   * Check if user has specific permission
   */
  const hasPermission = useCallback((permission: string): boolean => {
    return authService.hasPermission(state.permissions, permission);
  }, [state.permissions]);

  /**
   * Check if user has any of the specified permissions
   */
  const hasAnyPermission = useCallback((permissions: string[]): boolean => {
    return authService.hasAnyPermission(state.permissions, permissions);
  }, [state.permissions]);

  /**
   * Check if user has all specified permissions
   */
  const hasAllPermissions = useCallback((permissions: string[]): boolean => {
    return authService.hasAllPermissions(state.permissions, permissions);
  }, [state.permissions]);

  /**
   * Auto-refresh token before expiration
   */
  useEffect(() => {
    if (!state.tokens || !state.isAuthenticated) return;

    const refreshInterval = setInterval(() => {
      const timeUntilExpiry = state.tokens!.expires_at - Date.now();
      const fiveMinutes = 5 * 60 * 1000;

      // Refresh token 5 minutes before expiry
      if (timeUntilExpiry <= fiveMinutes) {
        refreshToken().catch(console.error);
      }
    }, 60000); // Check every minute

    return () => clearInterval(refreshInterval);
  }, [state.tokens, state.isAuthenticated, refreshToken]);

  /**
   * Initialize auth on mount
   */
  useEffect(() => {
    initializeAuth();
  }, [initializeAuth]);

  /**
   * Handle storage events (logout from other tabs)
   */
  useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === 'access_token' && !event.newValue) {
        // Token was removed, logout
        dispatch({ type: 'AUTH_LOGOUT' });
      }
    };

    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, []);

  const contextValue: UseAuthReturn = {
    user: state.user,
    isAuthenticated: state.isAuthenticated,
    isLoading: state.isLoading,
    mfaPending: state.mfaPending,
    mfaData: state.mfaData,
    permissions: state.permissions,
    login,
    logout,
    verifyMfa,
    refreshToken,
    updateProfile,
    hasPermission,
    hasAnyPermission,
    hasAllPermissions,
  };

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}

// Hook to use auth context
export function useAuth(): UseAuthReturn {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

// Export context for testing
export { AuthContext };