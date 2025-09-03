/**
 * Authentication API service
 * Handles all authentication-related API calls with comprehensive error handling
 */

import { 
  User, 
  LoginCredentials, 
  LoginResponse, 
  MfaRequiredResponse, 
  AuthTokens, 
  MfaSetupData,
  UserSession,
  PasswordStrengthResult,
  ApiError
} from '@/types/auth';

class AuthService {
  private baseUrl: string;
  private tokenRefreshPromise: Promise<AuthTokens> | null = null;

  constructor() {
    this.baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  }

  /**
   * Get authentication headers with bearer token
   */
  private getAuthHeaders(): Record<string, string> {
    const token = this.getAccessToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    
    return headers;
  }

  /**
   * Get device fingerprint for security tracking
   */
  private getDeviceFingerprint(): string {
    // Simple device fingerprinting based on browser characteristics
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx?.fillText('fingerprint', 10, 10);
    
    const fingerprint = btoa(
      navigator.userAgent +
      screen.width + screen.height +
      new Date().getTimezoneOffset() +
      (canvas.toDataURL?.() || '')
    );
    
    return fingerprint.slice(0, 16);
  }

  /**
   * Handle API response with error parsing
   */
  private async handleResponse<T>(response: Response): Promise<T> {
    if (response.status === 401) {
      // Token expired, try to refresh
      await this.refreshTokens();
      throw new Error('Token expired, please retry');
    }

    if (!response.ok) {
      const error: ApiError = await response.json().catch(() => ({
        type: 'unknown_error',
        title: 'Unknown Error',
        status: response.status,
        detail: response.statusText,
        instance: response.url,
      }));
      
      throw new Error(error.detail || `HTTP ${response.status}: ${response.statusText}`);
    }

    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      return response.json();
    }

    return response.text() as unknown as T;
  }

  /**
   * Make authenticated API request with automatic token refresh
   */
  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}/api/v1${endpoint}`;
    
    const config: RequestInit = {
      ...options,
      headers: {
        ...this.getAuthHeaders(),
        'X-Device-Fingerprint': this.getDeviceFingerprint(),
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);
      return await this.handleResponse<T>(response);
    } catch (error) {
      if (error instanceof Error && error.message === 'Token expired, please retry') {
        // Retry the request with new token
        const retryConfig = {
          ...config,
          headers: {
            ...this.getAuthHeaders(),
            ...options.headers,
          },
        };
        const retryResponse = await fetch(url, retryConfig);
        return await this.handleResponse<T>(retryResponse);
      }
      throw error;
    }
  }

  /**
   * Store authentication tokens
   */
  private storeTokens(tokens: AuthTokens): void {
    localStorage.setItem('access_token', tokens.access_token);
    localStorage.setItem('refresh_token', tokens.refresh_token);
    localStorage.setItem('expires_at', tokens.expires_at.toString());
  }

  /**
   * Get stored access token
   */
  getAccessToken(): string | null {
    return localStorage.getItem('access_token');
  }

  /**
   * Get stored refresh token
   */
  private getRefreshToken(): string | null {
    return localStorage.getItem('refresh_token');
  }

  /**
   * Check if token is expired
   */
  isTokenExpired(): boolean {
    const expiresAt = localStorage.getItem('expires_at');
    if (!expiresAt) return true;
    
    return Date.now() >= parseInt(expiresAt, 10);
  }

  /**
   * Clear stored tokens
   */
  clearTokens(): void {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('expires_at');
  }

  /**
   * Login user with credentials
   */
  async login(credentials: LoginCredentials): Promise<LoginResponse | MfaRequiredResponse> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Device-Fingerprint': this.getDeviceFingerprint(),
      },
      body: JSON.stringify(credentials),
    });

    if (response.status === 202) {
      // MFA required
      return await this.handleResponse<MfaRequiredResponse>(response);
    }

    const loginResponse = await this.handleResponse<LoginResponse>(response);
    
    // Store tokens
    const tokens: AuthTokens = {
      access_token: loginResponse.access_token,
      refresh_token: loginResponse.refresh_token,
      expires_at: Date.now() + (loginResponse.expires_in * 1000),
    };
    
    this.storeTokens(tokens);
    
    return loginResponse;
  }

  /**
   * Verify MFA token
   */
  async verifyMfa(
    credentials: LoginCredentials & { user_id: string; tenant_id: string }
  ): Promise<LoginResponse> {
    const loginResponse = await this.handleResponse<LoginResponse>(
      await fetch(`${this.baseUrl}/api/v1/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Device-Fingerprint': this.getDeviceFingerprint(),
        },
        body: JSON.stringify(credentials),
      })
    );
    
    // Store tokens
    const tokens: AuthTokens = {
      access_token: loginResponse.access_token,
      refresh_token: loginResponse.refresh_token,
      expires_at: Date.now() + (loginResponse.expires_in * 1000),
    };
    
    this.storeTokens(tokens);
    
    return loginResponse;
  }

  /**
   * Refresh authentication tokens
   */
  async refreshTokens(): Promise<AuthTokens> {
    // Prevent multiple concurrent refresh requests
    if (this.tokenRefreshPromise) {
      return this.tokenRefreshPromise;
    }

    const refreshToken = this.getRefreshToken();
    if (!refreshToken) {
      throw new Error('No refresh token available');
    }

    this.tokenRefreshPromise = (async () => {
      try {
        const response = await fetch(`${this.baseUrl}/api/v1/auth/refresh`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Device-Fingerprint': this.getDeviceFingerprint(),
          },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });

        const result = await this.handleResponse<{
          access_token: string;
          expires_in: number;
        }>(response);

        const tokens: AuthTokens = {
          access_token: result.access_token,
          refresh_token: refreshToken, // Keep existing refresh token
          expires_at: Date.now() + (result.expires_in * 1000),
        };

        this.storeTokens(tokens);
        return tokens;
      } finally {
        this.tokenRefreshPromise = null;
      }
    })();

    return this.tokenRefreshPromise;
  }

  /**
   * Logout user
   */
  async logout(allDevices: boolean = false): Promise<void> {
    try {
      await this.request('/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ all_sessions: allDevices }),
      });
    } catch (error) {
      // Log error but continue with local logout
      console.warn('Logout request failed:', error);
    } finally {
      this.clearTokens();
    }
  }

  /**
   * Get current user profile
   */
  async getCurrentUser(): Promise<User> {
    return this.request<User>('/auth/me');
  }

  /**
   * Update user profile
   */
  async updateProfile(data: {
    full_name?: string;
    display_name?: string;
    phone?: string;
  }): Promise<User> {
    return this.request<User>('/auth/me', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Change password
   */
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await this.request('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
  }

  /**
   * Request password reset
   */
  async requestPasswordReset(email: string): Promise<void> {
    await fetch(`${this.baseUrl}/api/v1/auth/reset-password`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email }),
    });
  }

  /**
   * Confirm password reset
   */
  async confirmPasswordReset(token: string, newPassword: string): Promise<void> {
    await fetch(`${this.baseUrl}/api/v1/auth/reset-password/confirm`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        token,
        new_password: newPassword,
      }),
    });
  }

  /**
   * Check password strength
   */
  async checkPasswordStrength(password: string): Promise<PasswordStrengthResult> {
    return fetch(`${this.baseUrl}/api/v1/auth/password/strength`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ password }),
    }).then(this.handleResponse<PasswordStrengthResult>);
  }

  /**
   * Setup MFA
   */
  async setupMfa(): Promise<MfaSetupData> {
    return this.request<MfaSetupData>('/auth/mfa/setup', {
      method: 'POST',
    });
  }

  /**
   * Enable MFA
   */
  async enableMfa(verificationCode: string): Promise<void> {
    await this.request('/auth/mfa/enable', {
      method: 'POST',
      body: JSON.stringify({ verification_code: verificationCode }),
    });
  }

  /**
   * Disable MFA
   */
  async disableMfa(password: string, verificationCode: string): Promise<void> {
    await this.request('/auth/mfa/disable', {
      method: 'POST',
      body: JSON.stringify({
        password,
        verification_code: verificationCode,
      }),
    });
  }

  /**
   * Get user sessions
   */
  async getSessions(): Promise<UserSession[]> {
    return this.request<UserSession[]>('/auth/sessions');
  }

  /**
   * Terminate specific session
   */
  async terminateSession(sessionId: string): Promise<void> {
    await this.request('/auth/sessions/terminate', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
  }

  /**
   * Terminate all sessions
   */
  async terminateAllSessions(): Promise<void> {
    await this.request('/auth/sessions/terminate', {
      method: 'POST',
      body: JSON.stringify({ all_sessions: true }),
    });
  }

  /**
   * Check if user has permission
   */
  hasPermission(userPermissions: string[], requiredPermission: string): boolean {
    // Check for system admin permission
    if (userPermissions.includes('system:*')) {
      return true;
    }

    // Check for exact permission or wildcard
    const [resource, action] = requiredPermission.split(':');
    return (
      userPermissions.includes(requiredPermission) ||
      userPermissions.includes(`${resource}:*`)
    );
  }

  /**
   * Check if user has any of the specified permissions
   */
  hasAnyPermission(userPermissions: string[], requiredPermissions: string[]): boolean {
    return requiredPermissions.some(permission => 
      this.hasPermission(userPermissions, permission)
    );
  }

  /**
   * Check if user has all specified permissions
   */
  hasAllPermissions(userPermissions: string[], requiredPermissions: string[]): boolean {
    return requiredPermissions.every(permission => 
      this.hasPermission(userPermissions, permission)
    );
  }
}

// Export singleton instance
export const authService = new AuthService();
export default authService;