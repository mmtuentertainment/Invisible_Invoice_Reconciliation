"""Add import batch and error tracking models

Revision ID: 20250103_add_import_batch
Revises: previous_revision
Create Date: 2025-01-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250103_add_import_batch'
down_revision = 'previous_revision'  # Replace with actual previous revision
branch_labels = None
depends_on = None


def upgrade():
    """Add import batch and error tracking tables."""
    
    # Create import batch status enum
    import_batch_status = postgresql.ENUM(
        'PENDING', 'UPLOADING', 'VALIDATING', 'PROCESSING', 
        'COMPLETED', 'FAILED', 'CANCELLED',
        name='importbatchstatus',
        create_type=False
    )
    import_batch_status.create(op.get_bind(), checkfirst=True)
    
    # Create import error type enum
    import_error_type = postgresql.ENUM(
        'VALIDATION', 'PARSING', 'BUSINESS_RULE', 'DUPLICATE', 'SYSTEM',
        name='importerrortype',
        create_type=False
    )
    import_error_type.create(op.get_bind(), checkfirst=True)
    
    # Create import_batches table
    op.create_table(
        'import_batches',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), 
                  sa.ForeignKey('tenants.id'), nullable=False),
        
        # File information
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('storage_path', sa.String(500), nullable=False),
        
        # Processing status
        sa.Column('status', import_batch_status, server_default='PENDING'),
        sa.Column('processing_stage', sa.String(50)),
        sa.Column('progress_percentage', sa.Integer(), server_default='0'),
        
        # Record counts
        sa.Column('total_records', sa.Integer(), server_default='0'),
        sa.Column('processed_records', sa.Integer(), server_default='0'),
        sa.Column('successful_records', sa.Integer(), server_default='0'),
        sa.Column('error_records', sa.Integer(), server_default='0'),
        sa.Column('duplicate_records', sa.Integer(), server_default='0'),
        
        # Processing configuration
        sa.Column('csv_delimiter', sa.String(1), server_default=','),
        sa.Column('csv_encoding', sa.String(20), server_default='utf-8'),
        sa.Column('has_header', sa.Boolean(), server_default=sa.true()),
        sa.Column('column_mapping', postgresql.JSON()),
        
        # Processing times
        sa.Column('upload_started_at', sa.DateTime(timezone=True)),
        sa.Column('upload_completed_at', sa.DateTime(timezone=True)),
        sa.Column('processing_started_at', sa.DateTime(timezone=True)),
        sa.Column('processing_completed_at', sa.DateTime(timezone=True)),
        
        # Results and metadata
        sa.Column('processing_summary', postgresql.JSON()),
        sa.Column('error_summary', postgresql.JSON()),
        sa.Column('preview_data', postgresql.JSON()),
        
        # Audit trail
        sa.Column('created_at', sa.DateTime(timezone=True), 
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), 
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True)),
        
        # Constraints
        sa.CheckConstraint('file_size > 0'),
        sa.CheckConstraint('progress_percentage >= 0 AND progress_percentage <= 100'),
        sa.CheckConstraint('total_records >= 0'),
        sa.CheckConstraint('processed_records >= 0'),
        sa.CheckConstraint('successful_records >= 0'),
        sa.CheckConstraint('error_records >= 0'),
        sa.CheckConstraint('duplicate_records >= 0'),
        sa.CheckConstraint('processed_records <= total_records'),
        sa.CheckConstraint('successful_records + error_records + duplicate_records <= total_records'),
        sa.CheckConstraint("csv_delimiter IN (',', '\t', '|', ';')"),
        sa.CheckConstraint("csv_encoding IN ('utf-8', 'utf-16', 'ascii', 'iso-8859-1')"),
    )
    
    # Create import_errors table
    op.create_table(
        'import_errors',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), 
                  sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('import_batch_id', postgresql.UUID(as_uuid=True), 
                  sa.ForeignKey('import_batches.id'), nullable=False),
        
        # Error location
        sa.Column('row_number', sa.Integer(), nullable=False),
        sa.Column('column_name', sa.String(100)),
        sa.Column('column_index', sa.Integer()),
        
        # Error details
        sa.Column('error_type', import_error_type, nullable=False),
        sa.Column('error_code', sa.String(50), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(20), server_default='error'),
        
        # Data context
        sa.Column('raw_value', sa.Text()),
        sa.Column('expected_format', sa.String(100)),
        sa.Column('suggested_fix', sa.Text()),
        sa.Column('raw_row_data', postgresql.JSON()),
        
        # Resolution tracking
        sa.Column('is_resolved', sa.Boolean(), server_default=sa.false()),
        sa.Column('resolution_action', sa.String(100)),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_by', postgresql.UUID(as_uuid=True)),
        
        # Audit trail
        sa.Column('created_at', sa.DateTime(timezone=True), 
                  server_default=sa.func.now()),
        
        # Constraints
        sa.CheckConstraint('row_number > 0'),
        sa.CheckConstraint('column_index IS NULL OR column_index >= 0'),
        sa.CheckConstraint("severity IN ('error', 'warning')"),
    )
    
    # Create indexes
    op.create_index('idx_import_batches_tenant', 'import_batches', ['tenant_id'])
    op.create_index('idx_import_batches_status', 'import_batches', ['status'])
    op.create_index('idx_import_batches_created', 'import_batches', ['created_at'])
    op.create_index('idx_import_batches_filename', 'import_batches', ['filename'])
    op.create_index('idx_import_batches_hash', 'import_batches', ['file_hash'])
    
    op.create_index('idx_import_errors_tenant', 'import_errors', ['tenant_id'])
    op.create_index('idx_import_errors_batch', 'import_errors', ['import_batch_id'])
    op.create_index('idx_import_errors_row', 'import_errors', ['row_number'])
    op.create_index('idx_import_errors_type', 'import_errors', ['error_type'])
    op.create_index('idx_import_errors_severity', 'import_errors', ['severity'])
    op.create_index('idx_import_errors_resolved', 'import_errors', ['is_resolved'])


def downgrade():
    """Remove import batch and error tracking tables."""
    
    # Drop indexes
    op.drop_index('idx_import_errors_resolved', 'import_errors')
    op.drop_index('idx_import_errors_severity', 'import_errors')
    op.drop_index('idx_import_errors_type', 'import_errors')
    op.drop_index('idx_import_errors_row', 'import_errors')
    op.drop_index('idx_import_errors_batch', 'import_errors')
    op.drop_index('idx_import_errors_tenant', 'import_errors')
    
    op.drop_index('idx_import_batches_hash', 'import_batches')
    op.drop_index('idx_import_batches_filename', 'import_batches')
    op.drop_index('idx_import_batches_created', 'import_batches')
    op.drop_index('idx_import_batches_status', 'import_batches')
    op.drop_index('idx_import_batches_tenant', 'import_batches')
    
    # Drop tables
    op.drop_table('import_errors')
    op.drop_table('import_batches')
    
    # Drop enums
    op.execute('DROP TYPE IF EXISTS importerrortype')
    op.execute('DROP TYPE IF EXISTS importbatchstatus')