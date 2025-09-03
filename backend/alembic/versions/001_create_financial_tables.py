"""Create financial tables for matching engine

Revision ID: 001
Revises: 
Create Date: 2025-01-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create enums
    document_status = postgresql.ENUM(
        'pending', 'processing', 'matched', 'unmatched', 'exception', 'archived',
        name='documentstatus'
    )
    document_status.create(op.get_bind())
    
    match_type = postgresql.ENUM(
        'exact', 'fuzzy', 'manual', 'partial',
        name='matchtype'
    )
    match_type.create(op.get_bind())
    
    match_status = postgresql.ENUM(
        'pending', 'approved', 'rejected', 'manual_review',
        name='matchstatus'
    )
    match_status.create(op.get_bind())
    
    currency_code = postgresql.ENUM(
        'USD', 'EUR', 'GBP', 'CAD', 'AUD',
        name='currencycode'
    )
    currency_code.create(op.get_bind())

    # Create tenants table
    op.create_table(
        'tenants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('settings', sa.JSON(), server_default='{}'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('name'),
    )
    
    # Create indexes for tenants
    op.create_index('idx_tenants_name', 'tenants', ['name'])
    op.create_index('idx_tenants_active', 'tenants', ['is_active'])

    # Create vendors table
    op.create_table(
        'vendors',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('vendor_code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('legal_name', sa.String(255)),
        sa.Column('tax_id', sa.String(50)),
        sa.Column('email', sa.String(255)),
        sa.Column('phone', sa.String(20)),
        sa.Column('address', sa.JSON()),
        sa.Column('default_currency', currency_code, server_default='USD'),
        sa.Column('payment_terms_days', sa.Integer(), server_default='30'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('settings', sa.JSON(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by', postgresql.UUID(as_uuid=True)),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint('tenant_id', 'vendor_code'),
    )
    
    # Create indexes for vendors
    op.create_index('idx_vendors_tenant', 'vendors', ['tenant_id'])
    op.create_index('idx_vendors_code', 'vendors', ['tenant_id', 'vendor_code'])
    op.create_index('idx_vendors_name', 'vendors', ['name'])
    op.create_index('idx_vendors_active', 'vendors', ['is_active'])

    # Create vendor_aliases table
    op.create_table(
        'vendor_aliases',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vendors.id'), nullable=False),
        sa.Column('alias', sa.String(255), nullable=False),
        sa.Column('similarity_score', sa.Numeric(5, 4), nullable=False),
        sa.Column('approved', sa.Boolean(), server_default='false'),
        sa.Column('source', sa.String(50), server_default='manual'),
        sa.Column('confidence', sa.Numeric(5, 4), server_default='0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_by', postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint('tenant_id', 'vendor_id', 'alias'),
        sa.CheckConstraint('similarity_score >= 0.0 AND similarity_score <= 1.0'),
        sa.CheckConstraint('confidence >= 0.0 AND confidence <= 1.0'),
    )
    
    # Create indexes for vendor_aliases
    op.create_index('idx_vendor_aliases_tenant', 'vendor_aliases', ['tenant_id'])
    op.create_index('idx_vendor_aliases_vendor', 'vendor_aliases', ['vendor_id'])
    op.create_index('idx_vendor_aliases_alias', 'vendor_aliases', ['alias'])
    op.create_index('idx_vendor_aliases_score', 'vendor_aliases', ['similarity_score'])
    op.create_index('idx_vendor_aliases_approved', 'vendor_aliases', ['approved'])

    # Create purchase_orders table
    op.create_table(
        'purchase_orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vendors.id'), nullable=False),
        sa.Column('po_number', sa.String(50), nullable=False),
        sa.Column('external_po_number', sa.String(50)),
        sa.Column('currency', currency_code, server_default='USD'),
        sa.Column('subtotal', sa.Numeric(15, 2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(15, 2), server_default='0.00'),
        sa.Column('total_amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('po_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expected_delivery_date', sa.DateTime(timezone=True)),
        sa.Column('status', document_status, server_default='pending'),
        sa.Column('approval_status', sa.String(20), server_default='pending'),
        sa.Column('description', sa.Text()),
        sa.Column('buyer_notes', sa.Text()),
        sa.Column('delivery_address', sa.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint('tenant_id', 'po_number'),
        sa.CheckConstraint('subtotal >= 0'),
        sa.CheckConstraint('tax_amount >= 0'),
        sa.CheckConstraint('total_amount >= 0'),
        sa.CheckConstraint('total_amount >= subtotal'),
    )
    
    # Create indexes for purchase_orders
    op.create_index('idx_purchase_orders_tenant', 'purchase_orders', ['tenant_id'])
    op.create_index('idx_purchase_orders_vendor', 'purchase_orders', ['vendor_id'])
    op.create_index('idx_purchase_orders_number', 'purchase_orders', ['tenant_id', 'po_number'])
    op.create_index('idx_purchase_orders_date', 'purchase_orders', ['po_date'])
    op.create_index('idx_purchase_orders_status', 'purchase_orders', ['status'])
    op.create_index('idx_purchase_orders_amount', 'purchase_orders', ['total_amount'])

    # Create purchase_order_lines table
    op.create_table(
        'purchase_order_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('purchase_order_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('purchase_orders.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('item_code', sa.String(50)),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('quantity', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_price', sa.Numeric(15, 4), nullable=False),
        sa.Column('line_total', sa.Numeric(15, 2), nullable=False),
        sa.Column('unit_of_measure', sa.String(10), server_default='EA'),
        sa.Column('quantity_received', sa.Numeric(15, 4), server_default='0'),
        sa.Column('quantity_invoiced', sa.Numeric(15, 4), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('purchase_order_id', 'line_number'),
        sa.CheckConstraint('quantity > 0'),
        sa.CheckConstraint('unit_price >= 0'),
        sa.CheckConstraint('line_total >= 0'),
        sa.CheckConstraint('quantity_received >= 0'),
        sa.CheckConstraint('quantity_invoiced >= 0'),
        sa.CheckConstraint('quantity_received <= quantity'),
        sa.CheckConstraint('quantity_invoiced <= quantity'),
    )
    
    # Create indexes for purchase_order_lines
    op.create_index('idx_po_lines_tenant', 'purchase_order_lines', ['tenant_id'])
    op.create_index('idx_po_lines_po', 'purchase_order_lines', ['purchase_order_id'])
    op.create_index('idx_po_lines_item', 'purchase_order_lines', ['item_code'])

    # Create invoices table
    op.create_table(
        'invoices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vendors.id'), nullable=False),
        sa.Column('invoice_number', sa.String(100), nullable=False),
        sa.Column('po_reference', sa.String(50)),
        sa.Column('currency', currency_code, server_default='USD'),
        sa.Column('subtotal', sa.Numeric(15, 2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(15, 2), server_default='0.00'),
        sa.Column('total_amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('invoice_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True)),
        sa.Column('received_date', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('status', document_status, server_default='pending'),
        sa.Column('processing_status', sa.String(50), server_default='uploaded'),
        sa.Column('ocr_confidence', sa.Numeric(5, 4)),
        sa.Column('extracted_data', sa.JSON()),
        sa.Column('raw_text', sa.Text()),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint('tenant_id', 'vendor_id', 'invoice_number'),
        sa.CheckConstraint('subtotal >= 0'),
        sa.CheckConstraint('tax_amount >= 0'),
        sa.CheckConstraint('total_amount >= 0'),
        sa.CheckConstraint('total_amount >= subtotal'),
        sa.CheckConstraint('file_size > 0'),
        sa.CheckConstraint('ocr_confidence IS NULL OR (ocr_confidence >= 0.0 AND ocr_confidence <= 1.0)'),
    )
    
    # Create indexes for invoices
    op.create_index('idx_invoices_tenant', 'invoices', ['tenant_id'])
    op.create_index('idx_invoices_vendor', 'invoices', ['vendor_id'])
    op.create_index('idx_invoices_number', 'invoices', ['tenant_id', 'invoice_number'])
    op.create_index('idx_invoices_po_ref', 'invoices', ['po_reference'])
    op.create_index('idx_invoices_date', 'invoices', ['invoice_date'])
    op.create_index('idx_invoices_status', 'invoices', ['status'])
    op.create_index('idx_invoices_amount', 'invoices', ['total_amount'])
    op.create_index('idx_invoices_hash', 'invoices', ['file_hash'])

    # Create invoice_lines table
    op.create_table(
        'invoice_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('invoice_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('invoices.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('item_code', sa.String(50)),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('quantity', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_price', sa.Numeric(15, 4), nullable=False),
        sa.Column('line_total', sa.Numeric(15, 2), nullable=False),
        sa.Column('unit_of_measure', sa.String(10), server_default='EA'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('invoice_id', 'line_number'),
        sa.CheckConstraint('quantity > 0'),
        sa.CheckConstraint('unit_price >= 0'),
        sa.CheckConstraint('line_total >= 0'),
    )
    
    # Create indexes for invoice_lines
    op.create_index('idx_invoice_lines_tenant', 'invoice_lines', ['tenant_id'])
    op.create_index('idx_invoice_lines_invoice', 'invoice_lines', ['invoice_id'])
    op.create_index('idx_invoice_lines_item', 'invoice_lines', ['item_code'])

    # Create receipts table
    op.create_table(
        'receipts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('purchase_order_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('purchase_orders.id'), nullable=False),
        sa.Column('receipt_number', sa.String(50), nullable=False),
        sa.Column('delivery_note', sa.String(100)),
        sa.Column('receipt_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_by', sa.String(255), nullable=False),
        sa.Column('total_quantity', sa.Numeric(15, 4), nullable=False),
        sa.Column('total_value', sa.Numeric(15, 2), nullable=False),
        sa.Column('status', document_status, server_default='pending'),
        sa.Column('notes', sa.Text()),
        sa.Column('delivery_conditions', sa.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint('tenant_id', 'receipt_number'),
        sa.CheckConstraint('total_quantity >= 0'),
        sa.CheckConstraint('total_value >= 0'),
    )
    
    # Create indexes for receipts
    op.create_index('idx_receipts_tenant', 'receipts', ['tenant_id'])
    op.create_index('idx_receipts_po', 'receipts', ['purchase_order_id'])
    op.create_index('idx_receipts_number', 'receipts', ['tenant_id', 'receipt_number'])
    op.create_index('idx_receipts_date', 'receipts', ['receipt_date'])
    op.create_index('idx_receipts_status', 'receipts', ['status'])

    # Create receipt_lines table
    op.create_table(
        'receipt_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('receipt_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('receipts.id'), nullable=False),
        sa.Column('po_line_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('purchase_order_lines.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('quantity_received', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(15, 4), nullable=False),
        sa.Column('line_value', sa.Numeric(15, 2), nullable=False),
        sa.Column('condition', sa.String(20), server_default='good'),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('receipt_id', 'line_number'),
        sa.CheckConstraint('quantity_received > 0'),
        sa.CheckConstraint('unit_cost >= 0'),
        sa.CheckConstraint('line_value >= 0'),
        sa.CheckConstraint("condition IN ('good', 'damaged', 'rejected')"),
    )
    
    # Create indexes for receipt_lines
    op.create_index('idx_receipt_lines_tenant', 'receipt_lines', ['tenant_id'])
    op.create_index('idx_receipt_lines_receipt', 'receipt_lines', ['receipt_id'])
    op.create_index('idx_receipt_lines_po_line', 'receipt_lines', ['po_line_id'])

    # Create matching_tolerances table
    op.create_table(
        'matching_tolerances',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vendors.id')),
        sa.Column('amount_threshold', sa.Numeric(15, 2)),
        sa.Column('tolerance_type', sa.String(20), nullable=False),
        sa.Column('percentage_tolerance', sa.Numeric(5, 4)),
        sa.Column('absolute_tolerance', sa.Numeric(15, 4)),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('priority', sa.Integer(), server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint("tolerance_type IN ('price', 'quantity', 'date')"),
        sa.CheckConstraint('percentage_tolerance IS NULL OR (percentage_tolerance >= 0.0 AND percentage_tolerance <= 1.0)'),
        sa.CheckConstraint('absolute_tolerance IS NULL OR absolute_tolerance >= 0'),
        sa.CheckConstraint('percentage_tolerance IS NOT NULL OR absolute_tolerance IS NOT NULL'),
        sa.CheckConstraint('priority >= 1 AND priority <= 10'),
    )
    
    # Create indexes for matching_tolerances
    op.create_index('idx_matching_tolerances_tenant', 'matching_tolerances', ['tenant_id'])
    op.create_index('idx_matching_tolerances_vendor', 'matching_tolerances', ['vendor_id'])
    op.create_index('idx_matching_tolerances_type', 'matching_tolerances', ['tolerance_type'])
    op.create_index('idx_matching_tolerances_active', 'matching_tolerances', ['is_active'])
    op.create_index('idx_matching_tolerances_priority', 'matching_tolerances', ['priority'])

    # Create match_results table
    op.create_table(
        'match_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('invoice_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('invoices.id'), nullable=False),
        sa.Column('purchase_order_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('purchase_orders.id')),
        sa.Column('receipt_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('receipts.id')),
        sa.Column('match_type', match_type, nullable=False),
        sa.Column('confidence_score', sa.Numeric(5, 4), nullable=False),
        sa.Column('match_status', match_status, server_default='pending'),
        sa.Column('criteria_met', sa.JSON(), nullable=False),
        sa.Column('tolerance_applied', sa.JSON()),
        sa.Column('auto_approved', sa.Boolean(), server_default='false'),
        sa.Column('requires_review', sa.Boolean(), server_default='false'),
        sa.Column('review_notes', sa.Text()),
        sa.Column('amount_variance', sa.Numeric(15, 2)),
        sa.Column('quantity_variance', sa.Numeric(15, 4)),
        sa.Column('matched_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
        sa.Column('approved_at', sa.DateTime(timezone=True)),
        sa.Column('matched_by', sa.String(20), server_default='system'),
        sa.Column('reviewed_by', postgresql.UUID(as_uuid=True)),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint('confidence_score >= 0.0 AND confidence_score <= 1.0'),
        sa.CheckConstraint("matched_by IN ('system', 'user')"),
        sa.CheckConstraint("(match_status = 'approved') = (approved_at IS NOT NULL)"),
        sa.CheckConstraint("(requires_review = true) OR (reviewed_at IS NULL)"),
    )
    
    # Create indexes for match_results
    op.create_index('idx_match_results_tenant', 'match_results', ['tenant_id'])
    op.create_index('idx_match_results_invoice', 'match_results', ['invoice_id'])
    op.create_index('idx_match_results_po', 'match_results', ['purchase_order_id'])
    op.create_index('idx_match_results_receipt', 'match_results', ['receipt_id'])
    op.create_index('idx_match_results_status', 'match_results', ['match_status'])
    op.create_index('idx_match_results_confidence', 'match_results', ['confidence_score'])
    op.create_index('idx_match_results_matched_at', 'match_results', ['matched_at'])
    op.create_index('idx_match_results_auto_approved', 'match_results', ['auto_approved'])
    op.create_index('idx_match_results_requires_review', 'match_results', ['requires_review'])

    # Create match_audit_log table
    op.create_table(
        'match_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('match_result_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('match_results.id'), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('event_description', sa.Text(), nullable=False),
        sa.Column('decision_factors', sa.JSON(), nullable=False),
        sa.Column('algorithm_version', sa.String(20), nullable=False),
        sa.Column('confidence_breakdown', sa.JSON(), nullable=False),
        sa.Column('old_values', sa.JSON()),
        sa.Column('new_values', sa.JSON()),
        sa.Column('user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('user_role', sa.String(50)),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('user_agent', sa.Text()),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('event_hash', sa.String(64), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('match_created', 'match_updated', 'status_changed', "
            "'confidence_updated', 'manual_review', 'approval_granted', 'approval_denied', "
            "'tolerance_applied', 'exception_created', 'user_feedback')"
        ),
    )
    
    # Create indexes for match_audit_log
    op.create_index('idx_match_audit_tenant', 'match_audit_log', ['tenant_id'])
    op.create_index('idx_match_audit_match', 'match_audit_log', ['match_result_id'])
    op.create_index('idx_match_audit_type', 'match_audit_log', ['event_type'])
    op.create_index('idx_match_audit_time', 'match_audit_log', ['occurred_at'])
    op.create_index('idx_match_audit_user', 'match_audit_log', ['user_id'])
    op.create_index('idx_match_audit_hash', 'match_audit_log', ['event_hash'])

    # Create matching_configuration table
    op.create_table(
        'matching_configuration',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('auto_approve_threshold', sa.Numeric(5, 4), server_default='0.85'),
        sa.Column('manual_review_threshold', sa.Numeric(5, 4), server_default='0.70'),
        sa.Column('rejection_threshold', sa.Numeric(5, 4), server_default='0.30'),
        sa.Column('fuzzy_matching_enabled', sa.Boolean(), server_default='true'),
        sa.Column('phonetic_matching_enabled', sa.Boolean(), server_default='true'),
        sa.Column('ocr_correction_enabled', sa.Boolean(), server_default='true'),
        sa.Column('vendor_name_weight', sa.Numeric(5, 4), server_default='0.30'),
        sa.Column('amount_weight', sa.Numeric(5, 4), server_default='0.40'),
        sa.Column('date_weight', sa.Numeric(5, 4), server_default='0.20'),
        sa.Column('reference_weight', sa.Numeric(5, 4), server_default='0.10'),
        sa.Column('batch_size', sa.Integer(), server_default='100'),
        sa.Column('parallel_processing_enabled', sa.Boolean(), server_default='true'),
        sa.Column('max_concurrent_jobs', sa.Integer(), server_default='4'),
        sa.Column('default_date_range_days', sa.Integer(), server_default='7'),
        sa.Column('max_date_range_days', sa.Integer(), server_default='30'),
        sa.Column('machine_learning_enabled', sa.Boolean(), server_default='true'),
        sa.Column('feedback_learning_enabled', sa.Boolean(), server_default='true'),
        sa.Column('config_version', sa.String(20), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint('tenant_id', 'config_version'),
        sa.CheckConstraint('auto_approve_threshold >= 0.0 AND auto_approve_threshold <= 1.0'),
        sa.CheckConstraint('manual_review_threshold >= 0.0 AND manual_review_threshold <= 1.0'),
        sa.CheckConstraint('rejection_threshold >= 0.0 AND rejection_threshold <= 1.0'),
        sa.CheckConstraint('auto_approve_threshold >= manual_review_threshold'),
        sa.CheckConstraint('manual_review_threshold >= rejection_threshold'),
        sa.CheckConstraint('vendor_name_weight + amount_weight + date_weight + reference_weight = 1.0'),
        sa.CheckConstraint('batch_size > 0 AND batch_size <= 1000'),
        sa.CheckConstraint('max_concurrent_jobs > 0 AND max_concurrent_jobs <= 20'),
        sa.CheckConstraint('default_date_range_days > 0 AND default_date_range_days <= max_date_range_days'),
        sa.CheckConstraint('max_date_range_days > 0 AND max_date_range_days <= 365'),
    )
    
    # Create indexes for matching_configuration
    op.create_index('idx_matching_config_tenant', 'matching_configuration', ['tenant_id'])
    op.create_index('idx_matching_config_active', 'matching_configuration', ['is_active'])
    op.create_index('idx_matching_config_version', 'matching_configuration', ['tenant_id', 'config_version'])

    # Enable Row Level Security (RLS)
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE vendors ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE vendor_aliases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE purchase_order_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE invoices ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE invoice_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE receipts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE receipt_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE matching_tolerances ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE match_results ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE match_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE matching_configuration ENABLE ROW LEVEL SECURITY")

    # Create RLS policies (simplified - real implementation would be more comprehensive)
    op.execute("""
        CREATE POLICY tenant_isolation ON vendors
        FOR ALL TO authenticated
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
    """)
    
    op.execute("""
        CREATE POLICY tenant_isolation ON invoices  
        FOR ALL TO authenticated
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
    """)
    
    op.execute("""
        CREATE POLICY tenant_isolation ON purchase_orders
        FOR ALL TO authenticated  
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
    """)
    
    op.execute("""
        CREATE POLICY tenant_isolation ON match_results
        FOR ALL TO authenticated
        USING (tenant_id = current_setting('app.current_tenant')::uuid)  
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
    """)


def downgrade():
    # Drop RLS policies
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON vendors")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON invoices")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON purchase_orders") 
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON match_results")

    # Drop tables in reverse order
    op.drop_table('matching_configuration')
    op.drop_table('match_audit_log')
    op.drop_table('match_results')
    op.drop_table('matching_tolerances')
    op.drop_table('receipt_lines')
    op.drop_table('receipts')
    op.drop_table('invoice_lines')
    op.drop_table('invoices')
    op.drop_table('purchase_order_lines')
    op.drop_table('purchase_orders')
    op.drop_table('vendor_aliases')
    op.drop_table('vendors')
    op.drop_table('tenants')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS currencycode")
    op.execute("DROP TYPE IF EXISTS matchstatus")
    op.execute("DROP TYPE IF EXISTS matchtype")
    op.execute("DROP TYPE IF EXISTS documentstatus")