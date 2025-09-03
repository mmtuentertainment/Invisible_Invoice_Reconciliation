'use client';

import { useState, useCallback } from 'react';
import { toast } from 'sonner';

interface UploadResponse {
  batch_id: string;
  filename: string;
  file_size: number;
  status: string;
  message: string;
  metadata?: any;
}

interface ProcessingRequest {
  column_mapping: Record<string, string>;
  processing_options?: Record<string, any>;
}

export function useInvoiceUpload() {
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState(false);

  const uploadFile = useCallback(async (
    file: File, 
    onProgress?: (progress: number) => void
  ): Promise<UploadResponse> => {
    setUploading(true);
    
    try {
      const formData = new FormData();
      formData.append('file', file);

      // Use XMLHttpRequest for progress tracking
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (event) => {
          if (event.lengthComputable && onProgress) {
            const progress = (event.loaded / event.total) * 100;
            onProgress(progress / 100); // Normalize to 0-1
          }
        });

        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              const response = JSON.parse(xhr.responseText);
              resolve(response);
            } catch (error) {
              reject(new Error('Invalid response format'));
            }
          } else {
            try {
              const errorResponse = JSON.parse(xhr.responseText);
              reject(new Error(errorResponse.detail || `Upload failed with status ${xhr.status}`));
            } catch {
              reject(new Error(`Upload failed with status ${xhr.status}`));
            }
          }
        });

        xhr.addEventListener('error', () => {
          reject(new Error('Network error occurred during upload'));
        });

        xhr.addEventListener('abort', () => {
          reject(new Error('Upload was aborted'));
        });

        xhr.open('POST', '/api/v1/invoices/upload');
        
        // Add auth header if available
        const token = localStorage.getItem('access_token');
        if (token) {
          xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        }

        xhr.send(formData);
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Upload failed';
      toast.error(message);
      throw error;
    } finally {
      setUploading(false);
    }
  }, []);

  const uploadFileChunked = useCallback(async (
    file: File,
    onProgress?: (progress: number) => void,
    chunkSize: number = 5 * 1024 * 1024 // 5MB chunks
  ): Promise<UploadResponse> => {
    setUploading(true);
    
    try {
      const totalChunks = Math.ceil(file.size / chunkSize);
      let uploadedChunks = 0;

      // Calculate file hash (simplified - in production use Web Crypto API)
      const fileHash = await calculateFileHash(file);

      for (let i = 0; i < totalChunks; i++) {
        const start = i * chunkSize;
        const end = Math.min(start + chunkSize, file.size);
        const chunk = file.slice(start, end);

        const chunkFormData = new FormData();
        chunkFormData.append('chunk', chunk);
        chunkFormData.append('chunk_info', JSON.stringify({
          chunk_number: i,
          total_chunks: totalChunks,
          chunk_size: chunkSize,
          total_size: file.size,
          filename: file.name,
          file_hash: fileHash
        }));

        const response = await fetch('/api/v1/invoices/upload/chunked', {
          method: 'POST',
          body: chunkFormData,
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `Chunk upload failed`);
        }

        uploadedChunks++;
        if (onProgress) {
          onProgress(uploadedChunks / totalChunks);
        }

        const result = await response.json();
        
        // If this was the final chunk and file is complete
        if (result.status !== 'uploading') {
          return result;
        }
      }

      throw new Error('Chunked upload completed but no final response received');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Chunked upload failed';
      toast.error(message);
      throw error;
    } finally {
      setUploading(false);
    }
  }, []);

  const getMetadata = useCallback(async (batchId: string): Promise<any> => {
    try {
      const response = await fetch(`/api/v1/invoices/upload/${batchId}/metadata`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch metadata');
      }

      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch metadata';
      toast.error(message);
      throw error;
    }
  }, []);

  const getImportStatus = useCallback(async (batchId: string): Promise<any> => {
    try {
      const response = await fetch(`/api/v1/invoices/upload/${batchId}/status`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch import status');
      }

      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch import status';
      toast.error(message);
      throw error;
    }
  }, []);

  const startProcessing = useCallback(async (
    batchId: string, 
    processingRequest: ProcessingRequest
  ): Promise<any> => {
    setProcessing(true);
    
    try {
      const response = await fetch(`/api/v1/invoices/upload/${batchId}/process`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify(processingRequest),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Failed to start processing');
      }

      const result = await response.json();
      toast.success('Processing started successfully');
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to start processing';
      toast.error(message);
      throw error;
    } finally {
      setProcessing(false);
    }
  }, []);

  const cancelImport = useCallback(async (batchId: string): Promise<void> => {
    try {
      const response = await fetch(`/api/v1/invoices/upload/${batchId}/cancel`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Failed to cancel import');
      }

      toast.success('Import cancelled successfully');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to cancel import';
      toast.error(message);
      throw error;
    }
  }, []);

  const getImportErrors = useCallback(async (
    batchId: string,
    options?: {
      skip?: number;
      limit?: number;
      error_type?: string;
    }
  ): Promise<any> => {
    try {
      const params = new URLSearchParams();
      if (options?.skip) params.append('skip', options.skip.toString());
      if (options?.limit) params.append('limit', options.limit.toString());
      if (options?.error_type) params.append('error_type', options.error_type);

      const response = await fetch(`/api/v1/invoices/upload/${batchId}/errors?${params}`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch import errors');
      }

      return await response.json();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch import errors';
      toast.error(message);
      throw error;
    }
  }, []);

  const downloadErrorReport = useCallback(async (batchId: string): Promise<void> => {
    try {
      const response = await fetch(`/api/v1/invoices/upload/${batchId}/errors/download`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to download error report');
      }

      // Create download
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `import_errors_${batchId}_${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      toast.success('Error report downloaded');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to download error report';
      toast.error(message);
      throw error;
    }
  }, []);

  return {
    uploading,
    processing,
    uploadFile,
    uploadFileChunked,
    getMetadata,
    getImportStatus,
    startProcessing,
    cancelImport,
    getImportErrors,
    downloadErrorReport,
  };
}

// Utility function to calculate file hash (simplified)
async function calculateFileHash(file: File): Promise<string> {
  try {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  } catch {
    // Fallback to a simple hash based on file properties
    return btoa(`${file.name}-${file.size}-${file.lastModified}`).replace(/[^a-zA-Z0-9]/g, '').substring(0, 32);
  }
}