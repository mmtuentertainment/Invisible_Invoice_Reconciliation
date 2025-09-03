/**
 * Multi-Factor Authentication form component
 * Supports TOTP verification and backup codes
 */

'use client';

import React, { useState, useRef, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { 
  Shield, 
  Loader2, 
  AlertCircle, 
  Clock, 
  Key,
  ChevronLeft 
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { MfaFormProps } from '@/types/auth';

// Form validation schema
const mfaSchema = z.object({
  code: z
    .string()
    .min(6, 'Code must be 6 digits')
    .max(9, 'Code must be 6 digits or backup code format')
    .regex(/^(\d{6}|\d{4}-\d{4})$/, 'Enter a 6-digit code or backup code (####-####)'),
});

type MfaFormData = z.infer<typeof mfaSchema>;

export function MfaForm({ mfaData, onSuccess, onCancel }: MfaFormProps) {
  const { verifyMfa, isLoading } = useAuth();
  const [error, setError] = useState<string>('');
  const [isBackupCode, setIsBackupCode] = useState(false);
  const [timeRemaining, setTimeRemaining] = useState(30);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
    reset,
  } = useForm<MfaFormData>({
    resolver: zodResolver(mfaSchema),
  });

  const codeValue = watch('code');

  // Timer for TOTP refresh
  useEffect(() => {
    const timer = setInterval(() => {
      setTimeRemaining(prev => {
        if (prev <= 1) {
          return 30; // Reset to 30 seconds
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  // Auto-focus and format input
  useEffect(() => {
    if (codeValue) {
      // Detect if user is entering backup code format
      if (codeValue.includes('-') || codeValue.length > 6) {
        setIsBackupCode(true);
      } else if (codeValue.length <= 6 && !codeValue.includes('-')) {
        setIsBackupCode(false);
      }
    }
  }, [codeValue]);

  const handleMfaVerification = async (data: MfaFormData) => {
    try {
      setError('');
      await verifyMfa(data.code);
      
      if (onSuccess) {
        onSuccess({ id: '', email: '' } as any); // Simplified
      }
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Verification failed. Please try again.');
      }
    }
  };

  const handleInputChange = (value: string) => {
    // Format backup code automatically
    if (value.length > 6) {
      const cleanValue = value.replace(/\D/g, '');
      if (cleanValue.length === 8) {
        const formatted = `${cleanValue.slice(0, 4)}-${cleanValue.slice(4, 8)}`;
        setValue('code', formatted);
      } else {
        setValue('code', cleanValue);
      }
    } else {
      // Regular 6-digit code
      const numericValue = value.replace(/\D/g, '');
      setValue('code', numericValue);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    // Only allow numbers and dash for backup codes
    if (!/[\d-]/.test(e.key) && e.key !== 'Backspace' && e.key !== 'Delete' && e.key !== 'Tab') {
      e.preventDefault();
    }
  };

  const switchToBackupCode = () => {
    setIsBackupCode(true);
    reset();
  };

  const switchToTotp = () => {
    setIsBackupCode(false);
    reset();
  };

  return (
    <div className="w-full max-w-md mx-auto">
      <div className="bg-white shadow-lg rounded-lg p-8">
        {/* Header */}
        <div className="mb-8 text-center">
          <div className="flex items-center justify-center mb-4">
            <Shield className="w-8 h-8 text-blue-600" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">
            Two-Factor Authentication
          </h1>
          <p className="text-sm text-gray-600">
            {isBackupCode
              ? 'Enter one of your backup recovery codes'
              : 'Enter the 6-digit code from your authenticator app'
            }
          </p>
        </div>

        {/* Error Message */}
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
            <div className="flex items-center">
              <AlertCircle className="w-4 h-4 text-red-500 mr-2" />
              <span className="text-sm text-red-700">{error}</span>
            </div>
          </div>
        )}

        {/* TOTP Timer */}
        {!isBackupCode && (
          <div className="mb-4 flex items-center justify-center">
            <div className="flex items-center text-sm text-gray-600">
              <Clock className="w-4 h-4 mr-1" />
              <span>New code in {timeRemaining}s</span>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit(handleMfaVerification)} className="space-y-4">
          {/* Code Input */}
          <div>
            <label 
              htmlFor="code" 
              className="block text-sm font-medium text-gray-700 mb-2"
            >
              {isBackupCode ? 'Backup Code' : 'Verification Code'}
            </label>
            
            <input
              {...register('code')}
              type="text"
              id="code"
              autoComplete="one-time-code"
              className={`
                w-full px-4 py-3 text-center text-lg font-mono border rounded-md shadow-sm 
                focus:outline-none focus:ring-2 focus:ring-blue-500
                ${errors.code ? 'border-red-300' : 'border-gray-300'}
                ${isBackupCode ? 'tracking-wider' : 'tracking-widest'}
              `}
              placeholder={isBackupCode ? '1234-5678' : '123456'}
              maxLength={isBackupCode ? 9 : 6}
              disabled={isLoading || isSubmitting}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyPress={handleKeyPress}
              autoFocus
            />
            
            {errors.code && (
              <p className="mt-1 text-sm text-red-600">
                {errors.code.message}
              </p>
            )}
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={isLoading || isSubmitting || !codeValue}
            className={`
              w-full flex justify-center items-center py-3 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white
              ${isLoading || isSubmitting || !codeValue
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500'
              }
            `}
          >
            {isLoading || isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Verifying...
              </>
            ) : (
              'Verify'
            )}
          </button>
        </form>

        {/* Alternative Options */}
        <div className="mt-6 space-y-4">
          {/* Switch between TOTP and backup code */}
          <div className="text-center">
            {isBackupCode ? (
              <button
                type="button"
                onClick={switchToTotp}
                className="text-sm text-blue-600 hover:text-blue-500"
                disabled={isLoading || isSubmitting}
              >
                Use authenticator app instead
              </button>
            ) : (
              <button
                type="button"
                onClick={switchToBackupCode}
                className="text-sm text-blue-600 hover:text-blue-500 flex items-center justify-center mx-auto"
                disabled={isLoading || isSubmitting}
              >
                <Key className="w-4 h-4 mr-1" />
                Use backup code instead
              </button>
            )}
          </div>

          {/* Cancel/Back Button */}
          {onCancel && (
            <div className="text-center">
              <button
                type="button"
                onClick={onCancel}
                className="text-sm text-gray-600 hover:text-gray-500 flex items-center justify-center mx-auto"
                disabled={isLoading || isSubmitting}
              >
                <ChevronLeft className="w-4 h-4 mr-1" />
                Back to login
              </button>
            </div>
          )}
        </div>

        {/* Help Text */}
        <div className="mt-6 p-3 bg-gray-50 rounded-md">
          <div className="text-xs text-gray-600">
            <p className="font-medium mb-1">Having trouble?</p>
            {isBackupCode ? (
              <p>
                Backup codes are 8 digits in ####-#### format. Each code can only be used once.
              </p>
            ) : (
              <p>
                Open your authenticator app (Google Authenticator, Authy, etc.) and enter the current 6-digit code.
              </p>
            )}
          </div>
        </div>

        {/* Security Notice */}
        <div className="mt-4 p-3 bg-blue-50 rounded-md">
          <div className="flex items-start">
            <Shield className="w-4 h-4 text-blue-500 mr-2 mt-0.5 flex-shrink-0" />
            <div className="text-xs text-blue-700">
              <p className="font-medium mb-1">Security Active</p>
              <p>
                This extra security step helps protect your account from unauthorized access.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}