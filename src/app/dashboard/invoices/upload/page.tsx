'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { InvoiceUploadInterface } from '@/components/invoice-upload/InvoiceUploadInterface';
import { Button } from '@/components/ui/button';
import { FileText, Upload, AlertCircle, CheckCircle } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';

export default function InvoiceUploadPage() {
  const handleImportComplete = (results: any) => {
    console.log('Import completed:', results);
    // Handle completion - show success message, redirect, etc.
  };

  return (
    <div className="container mx-auto py-6">
      {/* Page Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Invoice Upload</h1>
        <p className="mt-2 text-gray-600">
          Upload and process invoice CSV files for automated reconciliation
        </p>
      </div>

      {/* Quick Start Guide */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center">
            <FileText className="h-5 w-5 mr-2" />
            Quick Start Guide
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="flex items-start space-x-3">
              <div className="flex-shrink-0">
                <div className="flex items-center justify-center h-8 w-8 rounded-full bg-blue-100 text-blue-600 text-sm font-medium">
                  1
                </div>
              </div>
              <div>
                <h3 className="text-sm font-medium text-gray-900">Upload CSV File</h3>
                <p className="text-sm text-gray-600">
                  Drag and drop or select your invoice CSV file (up to 50MB)
                </p>
              </div>
            </div>

            <div className="flex items-start space-x-3">
              <div className="flex-shrink-0">
                <div className="flex items-center justify-center h-8 w-8 rounded-full bg-blue-100 text-blue-600 text-sm font-medium">
                  2
                </div>
              </div>
              <div>
                <h3 className="text-sm font-medium text-gray-900">Configure Mapping</h3>
                <p className="text-sm text-gray-600">
                  Map your CSV columns to required invoice fields
                </p>
              </div>
            </div>

            <div className="flex items-start space-x-3">
              <div className="flex-shrink-0">
                <div className="flex items-center justify-center h-8 w-8 rounded-full bg-blue-100 text-blue-600 text-sm font-medium">
                  3
                </div>
              </div>
              <div>
                <h3 className="text-sm font-medium text-gray-900">Import & Review</h3>
                <p className="text-sm text-gray-600">
                  Monitor progress and review any validation errors
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* CSV Format Requirements */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>CSV Format Requirements</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <Alert>
              <CheckCircle className="h-4 w-4" />
              <AlertDescription>
                <strong>Required Fields:</strong> Invoice Number, Vendor Name, Total Amount, Invoice Date
              </AlertDescription>
            </Alert>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <h4 className="text-sm font-medium text-gray-900 mb-2">Supported Formats</h4>
                <ul className="text-sm text-gray-600 space-y-1">
                  <li>• CSV files (.csv)</li>
                  <li>• Text files (.txt)</li>
                  <li>• UTF-8, UTF-16, ASCII encoding</li>
                  <li>• Comma, tab, pipe, semicolon delimiters</li>
                  <li>• With or without header row</li>
                </ul>
              </div>

              <div>
                <h4 className="text-sm font-medium text-gray-900 mb-2">Data Format Examples</h4>
                <ul className="text-sm text-gray-600 space-y-1">
                  <li>• <strong>Dates:</strong> 2023-01-15, 01/15/2023, 15/01/2023</li>
                  <li>• <strong>Amounts:</strong> 123.45, $1,234.56, €999.99</li>
                  <li>• <strong>Invoice Numbers:</strong> INV001, 2023-001</li>
                  <li>• <strong>Vendors:</strong> ACME Corp, Beta Industries</li>
                </ul>
              </div>
            </div>

            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Files are automatically validated for security and data quality. 
                Large files (500+ records) are processed in the background with real-time progress updates.
              </AlertDescription>
            </Alert>
          </div>
        </CardContent>
      </Card>

      {/* Upload Interface */}
      <Card>
        <CardContent className="p-6">
          <InvoiceUploadInterface 
            onImportComplete={handleImportComplete}
            className="w-full"
          />
        </CardContent>
      </Card>

      {/* Help Section */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Need Help?</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <h4 className="text-sm font-medium text-gray-900 mb-2">Common Issues</h4>
              <ul className="text-sm text-gray-600 space-y-2">
                <li>• <strong>File too large:</strong> Split files into smaller batches (under 50MB)</li>
                <li>• <strong>Encoding errors:</strong> Save file as UTF-8 from Excel</li>
                <li>• <strong>Date format issues:</strong> Use YYYY-MM-DD format for best results</li>
                <li>• <strong>Amount formatting:</strong> Remove currency symbols during processing</li>
              </ul>
            </div>

            <div>
              <h4 className="text-sm font-medium text-gray-900 mb-2">Sample CSV Template</h4>
              <div className="bg-gray-50 p-3 rounded-lg text-xs font-mono">
                invoice_number,vendor_name,total_amount,invoice_date<br/>
                INV001,ACME Corporation,150.00,2023-01-15<br/>
                INV002,Beta Industries,75.50,2023-01-16<br/>
                INV003,Gamma LLC,225.75,2023-01-17
              </div>
              <Button variant="outline" size="sm" className="mt-2">
                Download Template
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}