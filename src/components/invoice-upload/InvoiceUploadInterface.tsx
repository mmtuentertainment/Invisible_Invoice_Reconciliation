'use client';

import React, { useState, useCallback, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, FileText, AlertCircle, CheckCircle, X, Eye, Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { cn } from '@/lib/utils';
import { ColumnMappingDialog } from './ColumnMappingDialog';
import { ImportProgressDialog } from './ImportProgressDialog';
import { ErrorReportDialog } from './ErrorReportDialog';
import { useInvoiceUpload } from '@/hooks/useInvoiceUpload';
import { useWebSocketConnection } from '@/hooks/useWebSocketConnection';
import { formatBytes } from '@/lib/utils';

interface UploadedFile {
  file: File;
  batchId?: string;
  status: 'uploading' | 'processing' | 'completed' | 'error' | 'cancelled';
  progress: number;
  error?: string;
  metadata?: any;
}

interface InvoiceUploadInterfaceProps {
  onImportComplete?: (results: any) => void;
  className?: string;
}

export function InvoiceUploadInterface({ 
  onImportComplete, 
  className 
}: InvoiceUploadInterfaceProps) {
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<UploadedFile | null>(null);
  const [showColumnMapping, setShowColumnMapping] = useState(false);
  const [showProgress, setShowProgress] = useState(false);
  const [showErrorReport, setShowErrorReport] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  
  const { uploadFile, getMetadata, startProcessing, cancelImport, downloadErrorReport } = useInvoiceUpload();
  const { isConnected, subscribe, unsubscribe } = useWebSocketConnection();
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;

    setIsUploading(true);
    
    for (const file of acceptedFiles) {
      // Validate file
      if (!file.name.toLowerCase().endsWith('.csv') && !file.name.toLowerCase().endsWith('.txt')) {
        setUploadedFiles(prev => [...prev, {
          file,
          status: 'error',
          progress: 0,
          error: 'Only CSV and TXT files are supported'
        }]);
        continue;
      }

      if (file.size > 50 * 1024 * 1024) { // 50MB limit
        setUploadedFiles(prev => [...prev, {
          file,
          status: 'error', 
          progress: 0,
          error: 'File size exceeds 50MB limit'
        }]);
        continue;
      }

      // Add file to upload list
      const fileEntry: UploadedFile = {
        file,
        status: 'uploading',
        progress: 0
      };
      
      setUploadedFiles(prev => [...prev, fileEntry]);

      try {
        // Upload file
        const uploadResult = await uploadFile(file, (progress) => {
          setUploadedFiles(prev => 
            prev.map(f => 
              f.file === file 
                ? { ...f, progress: progress * 0.3 } // Upload is 30% of total
                : f
            )
          );
        });

        // Update with batch ID and processing status
        setUploadedFiles(prev => 
          prev.map(f => 
            f.file === file 
              ? { 
                  ...f, 
                  batchId: uploadResult.batch_id,
                  status: 'processing',
                  progress: 30
                }
              : f
          )
        );

        // Subscribe to progress updates
        if (uploadResult.batch_id) {
          subscribe(uploadResult.batch_id, (progressData) => {
            setUploadedFiles(prev => 
              prev.map(f => 
                f.batchId === uploadResult.batch_id 
                  ? { 
                      ...f, 
                      progress: 30 + (progressData.progress_percentage || 0) * 0.2, // Metadata is 20%
                      status: progressData.status === 'completed' ? 'completed' : 'processing'
                    }
                  : f
              )
            );
          });
        }

        // Get metadata
        const metadata = await getMetadata(uploadResult.batch_id);
        
        setUploadedFiles(prev => 
          prev.map(f => 
            f.batchId === uploadResult.batch_id 
              ? { 
                  ...f, 
                  metadata,
                  progress: 50,
                  status: 'completed'
                }
              : f
          )
        );

      } catch (error) {
        setUploadedFiles(prev => 
          prev.map(f => 
            f.file === file 
              ? { 
                  ...f, 
                  status: 'error',
                  error: error instanceof Error ? error.message : 'Upload failed'
                }
              : f
          )
        );
      }
    }
    
    setIsUploading(false);
  }, [uploadFile, getMetadata, subscribe]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/csv': ['.csv'],
      'text/plain': ['.txt']
    },
    maxFiles: 5,
    multiple: true,
    disabled: isUploading
  });

  const handleRemoveFile = (index: number) => {
    const file = uploadedFiles[index];
    if (file.batchId) {
      unsubscribe(file.batchId);
      if (file.status === 'processing') {
        cancelImport(file.batchId);
      }
    }
    setUploadedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleConfigureMapping = (file: UploadedFile) => {
    setSelectedFile(file);
    setShowColumnMapping(true);
  };

  const handleStartProcessing = async (columnMapping: Record<string, string>) => {
    if (!selectedFile?.batchId) return;

    setShowColumnMapping(false);
    setShowProgress(true);

    try {
      // Subscribe to processing updates
      subscribe(selectedFile.batchId, (progressData) => {
        setUploadedFiles(prev => 
          prev.map(f => 
            f.batchId === selectedFile.batchId 
              ? { 
                  ...f, 
                  progress: 50 + (progressData.progress_percentage || 0) * 0.5, // Processing is 50%
                  status: progressData.status
                }
              : f
          )
        );

        // Close progress dialog when complete
        if (progressData.status === 'completed' || progressData.status === 'failed') {
          setShowProgress(false);
          if (progressData.status === 'completed' && onImportComplete) {
            onImportComplete(progressData);
          }
        }
      });

      await startProcessing(selectedFile.batchId, { column_mapping: columnMapping });
    } catch (error) {
      console.error('Error starting processing:', error);
      setShowProgress(false);
    }
  };

  const handleViewErrors = (file: UploadedFile) => {
    setSelectedFile(file);
    setShowErrorReport(true);
  };

  const handleDownloadErrors = async (file: UploadedFile) => {
    if (!file.batchId) return;
    
    try {
      await downloadErrorReport(file.batchId);
    } catch (error) {
      console.error('Error downloading error report:', error);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'error':
      case 'failed':
        return 'bg-red-100 text-red-800';
      case 'processing':
      case 'uploading':
        return 'bg-blue-100 text-blue-800';
      case 'cancelled':
        return 'bg-gray-100 text-gray-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4" />;
      case 'error':
      case 'failed':
        return <AlertCircle className="h-4 w-4" />;
      default:
        return <FileText className="h-4 w-4" />;
    }
  };

  return (
    <div className={cn('space-y-6', className)}>
      {/* Connection Status */}
      {!isConnected && (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Real-time updates are not available. Progress tracking may be limited.
          </AlertDescription>
        </Alert>
      )}

      {/* Drop Zone */}
      <Card>
        <CardContent className="p-6">
          <div
            {...getRootProps()}
            className={cn(
              'border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors',
              isDragActive 
                ? 'border-blue-500 bg-blue-50' 
                : 'border-gray-300 hover:border-gray-400',
              isUploading && 'opacity-50 cursor-not-allowed'
            )}
          >
            <input {...getInputProps()} ref={fileInputRef} />
            
            <div className="flex flex-col items-center space-y-4">
              <Upload className={cn(
                'h-12 w-12',
                isDragActive ? 'text-blue-500' : 'text-gray-400'
              )} />
              
              {isDragActive ? (
                <p className="text-lg font-medium text-blue-600">
                  Drop your files here...
                </p>
              ) : (
                <>
                  <p className="text-lg font-medium text-gray-900">
                    Drag & drop invoice files here
                  </p>
                  <p className="text-sm text-gray-500">
                    Or click to select files (CSV, TXT • Max 50MB each • Up to 5 files)
                  </p>
                </>
              )}
              
              {!isUploading && (
                <Button 
                  variant="outline" 
                  onClick={() => fileInputRef.current?.click()}
                >
                  Select Files
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* File List */}
      {uploadedFiles.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Uploaded Files ({uploadedFiles.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {uploadedFiles.map((fileEntry, index) => (
              <div 
                key={index} 
                className="flex items-center space-x-4 p-4 border rounded-lg"
              >
                {/* File Icon */}
                <div className="flex-shrink-0">
                  {getStatusIcon(fileEntry.status)}
                </div>

                {/* File Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center space-x-3">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {fileEntry.file.name}
                    </p>
                    <Badge className={getStatusColor(fileEntry.status)}>
                      {fileEntry.status}
                    </Badge>
                  </div>
                  
                  <div className="flex items-center space-x-4 mt-1">
                    <p className="text-xs text-gray-500">
                      {formatBytes(fileEntry.file.size)}
                    </p>
                    {fileEntry.metadata && (
                      <p className="text-xs text-gray-500">
                        ~{fileEntry.metadata.estimated_rows} rows • 
                        {fileEntry.metadata.column_count} columns
                      </p>
                    )}
                    {fileEntry.error && (
                      <p className="text-xs text-red-600">
                        {fileEntry.error}
                      </p>
                    )}
                  </div>

                  {/* Progress Bar */}
                  {(fileEntry.status === 'uploading' || fileEntry.status === 'processing') && (
                    <div className="mt-2">
                      <Progress value={fileEntry.progress} className="h-2" />
                      <p className="text-xs text-gray-500 mt-1">
                        {fileEntry.progress.toFixed(0)}% complete
                      </p>
                    </div>
                  )}
                </div>

                {/* Actions */}
                <div className="flex items-center space-x-2">
                  {fileEntry.status === 'completed' && fileEntry.metadata && (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleConfigureMapping(fileEntry)}
                      >
                        <Eye className="h-4 w-4 mr-1" />
                        Configure
                      </Button>
                    </>
                  )}
                  
                  {(fileEntry.status === 'failed' || fileEntry.status === 'error') && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleViewErrors(fileEntry)}
                    >
                      View Errors
                    </Button>
                  )}

                  {fileEntry.batchId && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleDownloadErrors(fileEntry)}
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                  )}

                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleRemoveFile(index)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Column Mapping Dialog */}
      <ColumnMappingDialog
        open={showColumnMapping}
        onClose={() => setShowColumnMapping(false)}
        file={selectedFile}
        onStartProcessing={handleStartProcessing}
      />

      {/* Import Progress Dialog */}
      <ImportProgressDialog
        open={showProgress}
        onClose={() => setShowProgress(false)}
        file={selectedFile}
      />

      {/* Error Report Dialog */}
      <ErrorReportDialog
        open={showErrorReport}
        onClose={() => setShowErrorReport(false)}
        file={selectedFile}
      />
    </div>
  );
}