'use client';

import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { 
  CheckCircle, 
  AlertCircle, 
  Clock, 
  Loader2, 
  X,
  FileText,
  Users,
  DollarSign,
  Calendar
} from 'lucide-react';
import { useWebSocketConnection } from '@/hooks/useWebSocketConnection';
import { cn } from '@/lib/utils';

interface UploadedFile {
  file: File;
  batchId?: string;
  status: string;
  progress: number;
  error?: string;
  metadata?: any;
}

interface ImportProgressDialogProps {
  open: boolean;
  onClose: () => void;
  file: UploadedFile | null;
}

interface ProgressData {
  progress_percentage: number;
  processing_stage: string;
  statistics: {
    total_rows: number;
    processed_rows: number;
    successful_rows: number;
    error_rows: number;
    duplicate_rows: number;
    vendors_created: number;
    vendors_matched: number;
  };
  status: string;
  errors?: any[];
}

export function ImportProgressDialog({
  open,
  onClose,
  file
}: ImportProgressDialogProps) {
  const [progressData, setProgressData] = useState<ProgressData | null>(null);
  const [canCancel, setCanCancel] = useState(true);
  const [isCompleted, setIsCompleted] = useState(false);
  const [startTime, setStartTime] = useState<Date | null>(null);
  const [estimatedTimeRemaining, setEstimatedTimeRemaining] = useState<string>('');

  const { subscribe, unsubscribe } = useWebSocketConnection();

  useEffect(() => {
    if (open && file?.batchId) {
      setStartTime(new Date());
      setIsCompleted(false);
      setCanCancel(true);

      // Subscribe to progress updates
      const unsubscribeCallback = subscribe(file.batchId, (data) => {
        setProgressData(data);
        
        // Update completion status
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
          setIsCompleted(true);
          setCanCancel(false);
        }

        // Calculate estimated time remaining
        if (startTime && data.progress_percentage > 0 && data.progress_percentage < 100) {
          const elapsed = Date.now() - startTime.getTime();
          const estimatedTotal = (elapsed / data.progress_percentage) * 100;
          const remaining = estimatedTotal - elapsed;
          
          if (remaining > 0) {
            const minutes = Math.floor(remaining / 60000);
            const seconds = Math.floor((remaining % 60000) / 1000);
            setEstimatedTimeRemaining(
              minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`
            );
          }
        }
      });

      return () => {
        if (file.batchId) {
          unsubscribe(file.batchId);
        }
      };
    }
  }, [open, file?.batchId, subscribe, unsubscribe, startTime]);

  const handleCancel = async () => {
    if (file?.batchId && canCancel) {
      try {
        // Call cancel API
        const response = await fetch(`/api/v1/invoices/upload/${file.batchId}/cancel`, {
          method: 'DELETE',
          headers: {
            'Content-Type': 'application/json',
          },
        });

        if (response.ok) {
          setCanCancel(false);
        }
      } catch (error) {
        console.error('Error cancelling import:', error);
      }
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'failed':
        return <AlertCircle className="h-5 w-5 text-red-600" />;
      case 'cancelled':
        return <X className="h-5 w-5 text-gray-600" />;
      case 'processing':
      default:
        return <Loader2 className="h-5 w-5 text-blue-600 animate-spin" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      case 'cancelled':
        return 'bg-gray-100 text-gray-800';
      case 'processing':
      default:
        return 'bg-blue-100 text-blue-800';
    }
  };

  const stats = progressData?.statistics;

  return (
    <Dialog open={open} onOpenChange={!canCancel ? onClose : undefined}>
      <DialogContent className="max-w-2xl" hideClose={canCancel}>
        <DialogHeader>
          <DialogTitle className="flex items-center space-x-2">
            {getStatusIcon(progressData?.status || 'processing')}
            <span>Import Progress</span>
          </DialogTitle>
          <p className="text-sm text-gray-500">
            Processing file: <span className="font-medium">{file?.file.name}</span>
          </p>
        </DialogHeader>

        <div className="space-y-6">
          {/* Status Badge */}
          <div className="flex items-center justify-center">
            <Badge className={cn('px-3 py-1', getStatusColor(progressData?.status || 'processing'))}>
              {progressData?.status || 'Processing'}
            </Badge>
          </div>

          {/* Progress Bar */}
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-gray-600">
                {progressData?.processing_stage || 'Initializing...'}
              </span>
              <span className="font-medium">
                {Math.round(progressData?.progress_percentage || 0)}%
              </span>
            </div>
            <Progress 
              value={progressData?.progress_percentage || 0} 
              className="h-3"
            />
            {estimatedTimeRemaining && !isCompleted && (
              <div className="flex items-center justify-center text-xs text-gray-500">
                <Clock className="h-3 w-3 mr-1" />
                Estimated time remaining: {estimatedTimeRemaining}
              </div>
            )}
          </div>

          {/* Statistics Cards */}
          {stats && (
            <div className="grid grid-cols-2 gap-4">
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center space-x-3">
                    <FileText className="h-8 w-8 text-blue-600" />
                    <div>
                      <p className="text-2xl font-bold">{stats.processed_rows}</p>
                      <p className="text-sm text-gray-600">of {stats.total_rows} rows</p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center space-x-3">
                    <CheckCircle className="h-8 w-8 text-green-600" />
                    <div>
                      <p className="text-2xl font-bold text-green-600">{stats.successful_rows}</p>
                      <p className="text-sm text-gray-600">successful</p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center space-x-3">
                    <AlertCircle className="h-8 w-8 text-red-600" />
                    <div>
                      <p className="text-2xl font-bold text-red-600">{stats.error_rows}</p>
                      <p className="text-sm text-gray-600">errors</p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center space-x-3">
                    <Users className="h-8 w-8 text-purple-600" />
                    <div>
                      <p className="text-2xl font-bold text-purple-600">
                        {stats.vendors_created + stats.vendors_matched}
                      </p>
                      <p className="text-sm text-gray-600">vendors</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Detailed Statistics */}
          {stats && isCompleted && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Import Summary</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Total Records:</span>
                    <span className="font-medium">{stats.total_rows}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Processed:</span>
                    <span className="font-medium">{stats.processed_rows}</span>
                  </div>
                  <div className="flex justify-between text-green-600">
                    <span>Successful:</span>
                    <span className="font-medium">{stats.successful_rows}</span>
                  </div>
                  <div className="flex justify-between text-red-600">
                    <span>Errors:</span>
                    <span className="font-medium">{stats.error_rows}</span>
                  </div>
                  <div className="flex justify-between text-yellow-600">
                    <span>Duplicates:</span>
                    <span className="font-medium">{stats.duplicate_rows}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Success Rate:</span>
                    <span className="font-medium">
                      {stats.total_rows > 0 
                        ? Math.round((stats.successful_rows / stats.total_rows) * 100)
                        : 0
                      }%
                    </span>
                  </div>
                </div>

                {/* Vendor Statistics */}
                <div className="pt-3 border-t">
                  <p className="text-sm font-medium text-gray-900 mb-2">Vendor Management:</p>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div className="flex justify-between text-green-600">
                      <span>New Vendors Created:</span>
                      <span className="font-medium">{stats.vendors_created}</span>
                    </div>
                    <div className="flex justify-between text-blue-600">
                      <span>Existing Vendors Matched:</span>
                      <span className="font-medium">{stats.vendors_matched}</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Error Alert */}
          {progressData?.status === 'failed' && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Import failed. Please check the error report for details and try again.
              </AlertDescription>
            </Alert>
          )}

          {/* Success Alert */}
          {progressData?.status === 'completed' && (
            <Alert className="border-green-200 bg-green-50">
              <CheckCircle className="h-4 w-4 text-green-600" />
              <AlertDescription className="text-green-800">
                Import completed successfully! {stats?.successful_rows} invoices have been imported.
              </AlertDescription>
            </Alert>
          )}

          {/* Cancelled Alert */}
          {progressData?.status === 'cancelled' && (
            <Alert>
              <X className="h-4 w-4" />
              <AlertDescription>
                Import was cancelled. No changes have been made to your data.
              </AlertDescription>
            </Alert>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex justify-end space-x-3 pt-4 border-t">
          {canCancel && (
            <Button variant="outline" onClick={handleCancel}>
              Cancel Import
            </Button>
          )}
          
          {isCompleted && (
            <Button onClick={onClose}>
              Close
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}