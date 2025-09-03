'use client';

import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { 
  AlertCircle, 
  Download, 
  Filter, 
  Search,
  FileText,
  ChevronRight,
  ChevronDown
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface UploadedFile {
  file: File;
  batchId?: string;
  status: string;
  progress: number;
  error?: string;
  metadata?: any;
}

interface ErrorReportDialogProps {
  open: boolean;
  onClose: () => void;
  file: UploadedFile | null;
}

interface ImportError {
  id: string;
  row_number: number;
  column_name: string;
  error_type: string;
  error_code: string;
  error_message: string;
  severity: 'error' | 'warning';
  raw_value: string;
  expected_format: string;
  suggested_fix: string;
  created_at: string;
}

interface ErrorSummary {
  total_errors: number;
  error_breakdown: Record<string, number>;
  warning_breakdown: Record<string, number>;
}

export function ErrorReportDialog({
  open,
  onClose,
  file
}: ErrorReportDialogProps) {
  const [errors, setErrors] = useState<ImportError[]>([]);
  const [errorSummary, setErrorSummary] = useState<ErrorSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [filterType, setFilterType] = useState<string>('all');
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(new Set());
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const errorsPerPage = 20;

  useEffect(() => {
    if (open && file?.batchId) {
      fetchErrors();
    }
  }, [open, file?.batchId, currentPage, filterType, filterSeverity, searchTerm]);

  const fetchErrors = async () => {
    if (!file?.batchId) return;

    setLoading(true);
    try {
      const params = new URLSearchParams({
        skip: ((currentPage - 1) * errorsPerPage).toString(),
        limit: errorsPerPage.toString(),
      });

      if (filterType !== 'all') {
        params.append('error_type', filterType);
      }

      const response = await fetch(`/api/v1/invoices/upload/${file.batchId}/errors?${params}`);
      
      if (response.ok) {
        const data = await response.json();
        setErrors(data.errors || []);
        setTotalPages(Math.ceil(data.total_errors / errorsPerPage));
        
        // Create error summary
        const summary = {
          total_errors: data.total_errors,
          error_breakdown: {},
          warning_breakdown: {}
        };

        data.errors.forEach((error: ImportError) => {
          const breakdown = error.severity === 'error' ? summary.error_breakdown : summary.warning_breakdown;
          breakdown[error.error_code] = (breakdown[error.error_code] || 0) + 1;
        });

        setErrorSummary(summary);
      } else {
        console.error('Failed to fetch errors');
      }
    } catch (error) {
      console.error('Error fetching import errors:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadReport = async () => {
    if (!file?.batchId) return;

    try {
      const response = await fetch(`/api/v1/invoices/upload/${file.batchId}/errors/download`);
      
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `import_errors_${file.batchId}_${new Date().toISOString().split('T')[0]}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      }
    } catch (error) {
      console.error('Error downloading error report:', error);
    }
  };

  const toggleErrorExpansion = (errorId: string) => {
    const newExpanded = new Set(expandedErrors);
    if (newExpanded.has(errorId)) {
      newExpanded.delete(errorId);
    } else {
      newExpanded.add(errorId);
    }
    setExpandedErrors(newExpanded);
  };

  const filteredErrors = errors.filter(error => {
    if (filterSeverity !== 'all' && error.severity !== filterSeverity) {
      return false;
    }
    
    if (searchTerm && !error.error_message.toLowerCase().includes(searchTerm.toLowerCase()) &&
        !error.column_name?.toLowerCase().includes(searchTerm.toLowerCase())) {
      return false;
    }
    
    return true;
  });

  const getSeverityColor = (severity: string) => {
    return severity === 'error' 
      ? 'bg-red-100 text-red-800' 
      : 'bg-yellow-100 text-yellow-800';
  };

  const getTypeColor = (errorType: string) => {
    const colors: Record<string, string> = {
      validation: 'bg-blue-100 text-blue-800',
      parsing: 'bg-purple-100 text-purple-800',
      business_rule: 'bg-orange-100 text-orange-800',
      duplicate: 'bg-gray-100 text-gray-800',
      system: 'bg-red-100 text-red-800'
    };
    return colors[errorType] || 'bg-gray-100 text-gray-800';
  };

  if (!file?.batchId) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-hidden">
        <DialogHeader>
          <DialogTitle>Error Report</DialogTitle>
          <p className="text-sm text-gray-500">
            Import errors for: <span className="font-medium">{file.file.name}</span>
          </p>
        </DialogHeader>

        <div className="flex-1 overflow-hidden">
          {/* Error Summary */}
          {errorSummary && (
            <div className="mb-6">
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg flex items-center">
                    <AlertCircle className="h-5 w-5 mr-2 text-red-600" />
                    Error Summary
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="text-center">
                      <div className="text-2xl font-bold text-red-600">
                        {errorSummary.total_errors}
                      </div>
                      <div className="text-sm text-gray-600">Total Issues</div>
                    </div>
                    
                    <div className="text-center">
                      <div className="text-2xl font-bold text-red-600">
                        {Object.values(errorSummary.error_breakdown).reduce((a, b) => a + b, 0)}
                      </div>
                      <div className="text-sm text-gray-600">Errors</div>
                    </div>
                    
                    <div className="text-center">
                      <div className="text-2xl font-bold text-yellow-600">
                        {Object.values(errorSummary.warning_breakdown).reduce((a, b) => a + b, 0)}
                      </div>
                      <div className="text-sm text-gray-600">Warnings</div>
                    </div>
                  </div>
                  
                  {/* Top Error Types */}
                  <div className="mt-4 pt-4 border-t">
                    <p className="text-sm font-medium text-gray-900 mb-2">Most Common Issues:</p>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries({...errorSummary.error_breakdown, ...errorSummary.warning_breakdown})
                        .sort(([,a], [,b]) => b - a)
                        .slice(0, 5)
                        .map(([errorCode, count]) => (
                          <Badge key={errorCode} variant="outline">
                            {errorCode}: {count}
                          </Badge>
                        ))}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Filters and Search */}
          <div className="mb-4">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center space-x-2">
                <Filter className="h-4 w-4 text-gray-500" />
                <Select value={filterSeverity} onValueChange={setFilterSeverity}>
                  <SelectTrigger className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Severity</SelectItem>
                    <SelectItem value="error">Errors</SelectItem>
                    <SelectItem value="warning">Warnings</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-center space-x-2">
                <Select value={filterType} onValueChange={setFilterType}>
                  <SelectTrigger className="w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Types</SelectItem>
                    <SelectItem value="validation">Validation</SelectItem>
                    <SelectItem value="parsing">Parsing</SelectItem>
                    <SelectItem value="business_rule">Business Rule</SelectItem>
                    <SelectItem value="duplicate">Duplicate</SelectItem>
                    <SelectItem value="system">System</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-center space-x-2 flex-1 max-w-md">
                <Search className="h-4 w-4 text-gray-500" />
                <Input
                  placeholder="Search errors..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                />
              </div>

              <Button variant="outline" onClick={handleDownloadReport}>
                <Download className="h-4 w-4 mr-2" />
                Download CSV
              </Button>
            </div>
          </div>

          {/* Error List */}
          <Card className="flex-1">
            <CardContent className="p-0">
              <ScrollArea className="h-[500px]">
                {loading ? (
                  <div className="flex items-center justify-center h-32">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
                  </div>
                ) : filteredErrors.length === 0 ? (
                  <div className="text-center py-8">
                    <FileText className="h-12 w-12 text-gray-400 mx-auto mb-4" />
                    <p className="text-gray-500">No errors found with current filters</p>
                  </div>
                ) : (
                  <div className="divide-y">
                    {filteredErrors.map((error, index) => (
                      <div key={error.id || index} className="p-4">
                        <div 
                          className="flex items-center justify-between cursor-pointer"
                          onClick={() => toggleErrorExpansion(error.id)}
                        >
                          <div className="flex items-center space-x-3">
                            <div className="flex items-center">
                              {expandedErrors.has(error.id) ? (
                                <ChevronDown className="h-4 w-4 text-gray-400" />
                              ) : (
                                <ChevronRight className="h-4 w-4 text-gray-400" />
                              )}
                            </div>
                            
                            <div className="flex items-center space-x-3">
                              <Badge className="text-xs">
                                Row {error.row_number}
                              </Badge>
                              <Badge className={cn('text-xs', getSeverityColor(error.severity))}>
                                {error.severity}
                              </Badge>
                              <Badge className={cn('text-xs', getTypeColor(error.error_type))}>
                                {error.error_type}
                              </Badge>
                            </div>
                            
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-gray-900 truncate">
                                {error.error_message}
                              </p>
                              <p className="text-xs text-gray-500">
                                Column: {error.column_name || 'N/A'} • Code: {error.error_code}
                              </p>
                            </div>
                          </div>
                        </div>

                        {/* Expanded Details */}
                        {expandedErrors.has(error.id) && (
                          <div className="mt-4 pl-7 space-y-3">
                            {error.raw_value && (
                              <div>
                                <p className="text-xs font-medium text-gray-600 mb-1">Raw Value:</p>
                                <code className="text-xs bg-gray-100 px-2 py-1 rounded">
                                  {error.raw_value}
                                </code>
                              </div>
                            )}
                            
                            {error.expected_format && (
                              <div>
                                <p className="text-xs font-medium text-gray-600 mb-1">Expected Format:</p>
                                <p className="text-xs text-gray-800">{error.expected_format}</p>
                              </div>
                            )}
                            
                            {error.suggested_fix && (
                              <div>
                                <p className="text-xs font-medium text-gray-600 mb-1">Suggested Fix:</p>
                                <p className="text-xs text-gray-800">{error.suggested_fix}</p>
                              </div>
                            )}
                            
                            <div className="text-xs text-gray-500">
                              Occurred at: {new Date(error.created_at).toLocaleString()}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </ScrollArea>
            </CardContent>
          </Card>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-600">
                Page {currentPage} of {totalPages}
              </p>
              <div className="flex items-center space-x-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={currentPage === 1}
                  onClick={() => setCurrentPage(currentPage - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={currentPage === totalPages}
                  onClick={() => setCurrentPage(currentPage + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end pt-4 border-t">
          <Button onClick={onClose}>Close</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}