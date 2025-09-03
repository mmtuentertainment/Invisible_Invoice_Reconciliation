/**
 * Login form component with comprehensive security features
 * Supports email/password authentication and MFA
 */

'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Eye, EyeOff, Loader2, Shield, AlertCircle } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { LoginFormProps } from '@/types/auth';

// Form validation schema
const loginSchema = z.object({
  email: z
    .string()
    .email('Please enter a valid email address')
    .min(1, 'Email is required'),
  password: z
    .string()
    .min(1, 'Password is required'),
  device_name: z
    .string()
    .optional(),
  remember_device: z
    .boolean()
    .default(false),
});

type LoginFormData = z.infer<typeof loginSchema>;

export function LoginForm({ 
  onSuccess, 
  onMfaRequired, 
  redirectTo = '/dashboard' 
}: LoginFormProps) {
  const { login, isLoading, mfaPending } = useAuth();
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string>('');

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    watch,
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      device_name: '',
      remember_device: false,
    },
  });

  const handleLogin = async (data: LoginFormData) => {
    try {
      setError('');
      
      // Add device name if not provided
      if (!data.device_name) {
        data.device_name = `${navigator.platform} - ${new Date().toLocaleDateString()}`;
      }

      await login({
        email: data.email,
        password: data.password,
        device_name: data.device_name,
        remember_device: data.remember_device,
      });

      // Success callback
      if (onSuccess) {
        onSuccess({ id: '', email: data.email } as any); // Simplified
      }

      // Redirect on success (handled by AuthContext)
    } catch (err) {
      if (err instanceof Error) {
        if (err.message.includes('MFA')) {
          if (onMfaRequired) {
            // This would be called from AuthContext when MFA is required
            onMfaRequired({
              requires_mfa: true,
              mfa_methods: ['totp'],
              user_id: '',
              tenant_id: '',
            });
          }
        } else {
          setError(err.message);
        }
      } else {
        setError('An unexpected error occurred');
      }
    }
  };

  const getDeviceName = (): string => {
    const platform = navigator.platform || 'Unknown Device';
    const date = new Date().toLocaleDateString();
    return `${platform} - ${date}`;
  };

  if (mfaPending) {
    return (
      <div className="w-full max-w-md mx-auto">
        <div className="bg-white shadow-lg rounded-lg p-8">
          <div className="flex items-center justify-center mb-4">
            <Shield className="w-8 h-8 text-blue-600" />
          </div>
          <h2 className="text-2xl font-bold text-center text-gray-900 mb-2">
            Two-Factor Authentication Required
          </h2>
          <p className="text-sm text-gray-600 text-center mb-4">
            Please complete MFA verification to continue.
          </p>
          {/* MFA form would be rendered here */}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md mx-auto">
      <div className="bg-white shadow-lg rounded-lg p-8">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">
            Welcome Back
          </h1>
          <p className="text-sm text-gray-600">
            Sign in to your account to continue
          </p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
            <div className="flex items-center">
              <AlertCircle className="w-4 h-4 text-red-500 mr-2" />
              <span className="text-sm text-red-700">{error}</span>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit(handleLogin)} className="space-y-4">
          {/* Email Field */}
          <div>
            <label 
              htmlFor="email" 
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Email Address
            </label>
            <input
              {...register('email')}
              type="email"
              id="email"
              autoComplete="email"
              className={`
                w-full px-3 py-2 border rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500
                ${errors.email ? 'border-red-300' : 'border-gray-300'}
              `}
              placeholder="Enter your email"
              disabled={isLoading || isSubmitting}
            />
            {errors.email && (
              <p className="mt-1 text-sm text-red-600">
                {errors.email.message}
              </p>
            )}
          </div>

          {/* Password Field */}
          <div>
            <label 
              htmlFor="password" 
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Password
            </label>
            <div className="relative">
              <input
                {...register('password')}
                type={showPassword ? 'text' : 'password'}
                id="password"
                autoComplete="current-password"
                className={`
                  w-full px-3 py-2 pr-10 border rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500
                  ${errors.password ? 'border-red-300' : 'border-gray-300'}
                `}
                placeholder="Enter your password"
                disabled={isLoading || isSubmitting}
              />
              <button
                type="button"
                className="absolute inset-y-0 right-0 pr-3 flex items-center"
                onClick={() => setShowPassword(!showPassword)}
                disabled={isLoading || isSubmitting}
              >
                {showPassword ? (
                  <EyeOff className="w-4 h-4 text-gray-400" />
                ) : (
                  <Eye className="w-4 h-4 text-gray-400" />
                )}
              </button>
            </div>
            {errors.password && (
              <p className="mt-1 text-sm text-red-600">
                {errors.password.message}
              </p>
            )}
          </div>

          {/* Device Name Field */}
          <div>
            <label 
              htmlFor="device_name" 
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Device Name (Optional)
            </label>
            <input
              {...register('device_name')}
              type="text"
              id="device_name"
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder={getDeviceName()}
              disabled={isLoading || isSubmitting}
            />
            <p className="mt-1 text-xs text-gray-500">
              Help identify this device in your security settings
            </p>
          </div>

          {/* Remember Device Checkbox */}
          <div className="flex items-center">
            <input
              {...register('remember_device')}
              type="checkbox"
              id="remember_device"
              className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
              disabled={isLoading || isSubmitting}
            />
            <label 
              htmlFor="remember_device" 
              className="ml-2 block text-sm text-gray-700"
            >
              Trust this device for 30 days
            </label>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={isLoading || isSubmitting}
            className={`
              w-full flex justify-center items-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white
              ${isLoading || isSubmitting
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500'
              }
            `}
          >
            {isLoading || isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Signing in...
              </>
            ) : (
              'Sign In'
            )}
          </button>
        </form>

        {/* Footer Links */}
        <div className="mt-6 text-center">
          <button
            type="button"
            onClick={() => router.push('/forgot-password')}
            className="text-sm text-blue-600 hover:text-blue-500"
            disabled={isLoading || isSubmitting}
          >
            Forgot your password?
          </button>
        </div>

        {/* Security Notice */}
        <div className="mt-4 p-3 bg-gray-50 rounded-md">
          <div className="flex items-start">
            <Shield className="w-4 h-4 text-gray-400 mr-2 mt-0.5 flex-shrink-0" />
            <div className="text-xs text-gray-600">
              <p className="font-medium mb-1">Security Notice</p>
              <p>
                Your login is protected by enterprise-grade security including 
                rate limiting, device tracking, and audit logging.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}