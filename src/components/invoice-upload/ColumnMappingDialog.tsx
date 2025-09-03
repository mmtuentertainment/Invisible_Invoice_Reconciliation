'use client';

import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { CheckCircle, AlertCircle, FileText, Eye } from 'lucide-react';

interface UploadedFile {
  file: File;
  batchId?: string;
  status: string;
  progress: number;
  error?: string;
  metadata?: any;
}

interface ColumnMappingDialogProps {
  open: boolean;
  onClose: () => void;
  file: UploadedFile | null;
  onStartProcessing: (columnMapping: Record<string, string>) => void;
}

const REQUIRED_FIELDS = [
  { key: 'invoice_number', label: 'Invoice Number', required: true },
  { key: 'vendor', label: 'Vendor Name', required: true },
  { key: 'amount', label: 'Total Amount', required: true },
  { key: 'invoice_date', label: 'Invoice Date', required: true },
];

const OPTIONAL_FIELDS = [
  { key: 'po_reference', label: 'PO Reference' },
  { key: 'description', label: 'Description' },
  { key: 'tax_amount', label: 'Tax Amount' },
  { key: 'subtotal', label: 'Subtotal' },
  { key: 'due_date', label: 'Due Date' },
  { key: 'vendor_code', label: 'Vendor Code' },
  { key: 'currency', label: 'Currency' },
];

export function ColumnMappingDialog({
  open,
  onClose,
  file,
  onStartProcessing
}: ColumnMappingDialogProps) {
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    if (file?.metadata) {
      // Auto-suggest mappings based on column analysis
      const autoMapping: Record<string, string> = {};
      const headers = file.metadata.headers || [];
      const columnAnalysis = file.metadata.column_analysis || {};

      headers.forEach((header: string) => {
        const analysis = columnAnalysis[header];
        if (analysis?.potential_mapping) {
          autoMapping[header] = analysis.potential_mapping;
        }
      });

      setColumnMapping(autoMapping);
    }
  }, [file?.metadata]);

  const handleMappingChange = (csvColumn: string, fieldName: string) => {
    setColumnMapping(prev => {
      const newMapping = { ...prev };
      
      // Remove previous mapping to this field
      Object.keys(newMapping).forEach(key => {
        if (newMapping[key] === fieldName) {
          delete newMapping[key];
        }
      });
      
      // Add new mapping
      if (fieldName !== 'none') {
        newMapping[csvColumn] = fieldName;
      }
      
      return newMapping;
    });
  };

  const validateMapping = (): string[] => {
    const errors: string[] = [];
    const mappedFields = Object.values(columnMapping);

    // Check required fields
    REQUIRED_FIELDS.forEach(field => {
      if (!mappedFields.includes(field.key)) {
        errors.push(`Required field "${field.label}" is not mapped`);
      }
    });

    // Check for duplicate mappings
    const fieldCounts: Record<string, number> = {};
    mappedFields.forEach(field => {
      fieldCounts[field] = (fieldCounts[field] || 0) + 1;
    });

    Object.entries(fieldCounts).forEach(([field, count]) => {
      if (count > 1) {
        const fieldLabel = [...REQUIRED_FIELDS, ...OPTIONAL_FIELDS]
          .find(f => f.key === field)?.label || field;
        errors.push(`Field "${fieldLabel}" is mapped to multiple columns`);
      }
    });

    return errors;
  };

  const handleStartProcessing = () => {
    const errors = validateMapping();
    setValidationErrors(errors);

    if (errors.length === 0) {
      onStartProcessing(columnMapping);
    }
  };

  const getCurrentMapping = (fieldKey: string): string | undefined => {
    return Object.keys(columnMapping).find(csvColumn => columnMapping[csvColumn] === fieldKey);
  };

  const getColumnType = (header: string): string => {
    const analysis = file?.metadata?.column_analysis?.[header];
    return analysis?.type || 'text';
  };

  const getColumnSamples = (header: string): string[] => {
    const analysis = file?.metadata?.column_analysis?.[header];
    return analysis?.sample_values || [];
  };

  if (!file?.metadata) {
    return null;
  }

  const { headers = [], preview_data = [] } = file.metadata;

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden">
        <DialogHeader>
          <DialogTitle>Configure Column Mapping</DialogTitle>
          <p className="text-sm text-gray-500">
            Map your CSV columns to the required invoice fields. 
            File: <span className="font-medium">{file.file.name}</span>
          </p>
        </DialogHeader>

        <div className="flex-1 overflow-hidden">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 h-full">
            {/* Mapping Configuration */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-medium">Field Mapping</h3>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowPreview(!showPreview)}
                >
                  <Eye className="h-4 w-4 mr-1" />
                  {showPreview ? 'Hide' : 'Show'} Preview
                </Button>
              </div>

              <ScrollArea className="h-[500px] pr-4">
                {/* Required Fields */}
                <div className="space-y-4">
                  <div>
                    <h4 className="font-medium text-sm text-gray-900 mb-3">
                      Required Fields
                    </h4>
                    <div className="space-y-3">
                      {REQUIRED_FIELDS.map(field => (
                        <div key={field.key} className="space-y-2">
                          <Label className="text-sm font-medium flex items-center">
                            {field.label}
                            <Badge variant="destructive" className="ml-2 text-xs">
                              Required
                            </Badge>
                          </Label>
                          <Select
                            value={getCurrentMapping(field.key) || 'none'}
                            onValueChange={(value) => 
                              handleMappingChange(value === 'none' ? '' : value, field.key)
                            }
                          >
                            <SelectTrigger>
                              <SelectValue placeholder="Select column..." />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">Not mapped</SelectItem>
                              {headers.map((header: string) => (
                                <SelectItem key={header} value={header}>
                                  <div className="flex items-center space-x-2">
                                    <span>{header}</span>
                                    <Badge variant="outline" className="text-xs">
                                      {getColumnType(header)}
                                    </Badge>
                                  </div>
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          
                          {/* Show sample values for mapped column */}
                          {getCurrentMapping(field.key) && (
                            <div className="text-xs text-gray-500">
                              Samples: {getColumnSamples(getCurrentMapping(field.key)!).slice(0, 3).join(', ')}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Optional Fields */}
                  <div className="pt-4 border-t">
                    <h4 className="font-medium text-sm text-gray-900 mb-3">
                      Optional Fields
                    </h4>
                    <div className="space-y-3">
                      {OPTIONAL_FIELDS.map(field => (
                        <div key={field.key} className="space-y-2">
                          <Label className="text-sm">{field.label}</Label>
                          <Select
                            value={getCurrentMapping(field.key) || 'none'}
                            onValueChange={(value) => 
                              handleMappingChange(value === 'none' ? '' : value, field.key)
                            }
                          >
                            <SelectTrigger>
                              <SelectValue placeholder="Select column..." />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">Not mapped</SelectItem>
                              {headers.map((header: string) => (
                                <SelectItem key={header} value={header}>
                                  <div className="flex items-center space-x-2">
                                    <span>{header}</span>
                                    <Badge variant="outline" className="text-xs">
                                      {getColumnType(header)}
                                    </Badge>
                                  </div>
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          
                          {getCurrentMapping(field.key) && (
                            <div className="text-xs text-gray-500">
                              Samples: {getColumnSamples(getCurrentMapping(field.key)!).slice(0, 3).join(', ')}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </ScrollArea>
            </div>

            {/* Data Preview */}
            {showPreview && (
              <div className="space-y-4">
                <h3 className="text-lg font-medium">Data Preview</h3>
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">
                      First {Math.min(5, preview_data.length)} rows
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-[480px]">
                      {preview_data.slice(0, 5).map((row: any, index: number) => (
                        <div key={index} className="mb-4 p-3 border rounded-lg">
                          <div className="text-xs font-medium text-gray-500 mb-2">
                            Row {row.__row_number__ || index + 1}
                          </div>
                          <div className="space-y-1">
                            {Object.entries(row)
                              .filter(([key]) => key !== '__row_number__')
                              .map(([header, value]) => (
                                <div key={header} className="flex justify-between text-sm">
                                  <span className="font-medium text-gray-600 truncate flex-1 mr-2">
                                    {header}:
                                  </span>
                                  <span className="text-gray-900 truncate max-w-[200px]">
                                    {String(value) || '-'}
                                  </span>
                                </div>
                              ))}
                          </div>
                        </div>
                      ))}
                    </ScrollArea>
                  </CardContent>
                </Card>
              </div>
            )}
          </div>
        </div>

        {/* Validation Errors */}
        {validationErrors.length > 0 && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              <ul className="list-disc list-inside space-y-1">
                {validationErrors.map((error, index) => (
                  <li key={index}>{error}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <div className="flex items-center space-x-3">
            <div className="flex items-center text-sm text-gray-500">
              <FileText className="h-4 w-4 mr-1" />
              {Object.keys(columnMapping).length} of {headers.length} columns mapped
            </div>
            
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            
            <Button onClick={handleStartProcessing}>
              <CheckCircle className="h-4 w-4 mr-1" />
              Start Processing
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}