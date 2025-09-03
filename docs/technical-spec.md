# Technical Specification
## Invisible Invoice Reconciliation Platform

**Version:** 1.0  
**Date:** January 2025  
**Architect:** System Design Team  
**Status:** Draft

---

## 1. System Architecture

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client Layer                             │
├─────────────────┬────────────────┬──────────────────────────────┤
│   Next.js App   │  Mobile Web    │    API Consumers             │
│   (TypeScript)  │  (Responsive)  │    (Webhooks)                │
└────────┬────────┴────────┬───────┴──────────┬───────────────────┘
         │                 │                  │
         ▼                 ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API Gateway (FastAPI)                       │
│  - Rate Limiting    - Auth Middleware    - Request Validation   │
└─────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Auth       │    │  Business Logic   │    │  Integration     │
│  Service     │    │    Services       │    │   Service        │
└──────────────┘    └──────────────────┘    └──────────────────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                │
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
        ┌──────────┐    ┌──────────┐    ┌──────────┐
        │PostgreSQL│    │  Redis   │    │    S3    │
        │  + RLS   │    │  Cache   │    │  Storage │
        └──────────┘    └──────────┘    └──────────┘
```

### 1.2 Technology Stack

#### Backend Stack
```yaml
Language: Python 3.11+
Framework: FastAPI 0.104+
ORM: SQLAlchemy 2.0 (async mode)
Database: PostgreSQL 15+
Cache: Redis 7+
Queue: Redis + RQ or Celery
Testing: pytest, pytest-asyncio
Linting: ruff, black, mypy
```

#### Frontend Stack
```yaml
Framework: Next.js 14+
UI Library: React 18+
Language: TypeScript 5+
Styling: Tailwind CSS 3+
State: Zustand or Redux Toolkit
Forms: React Hook Form + Zod
Testing: Jest, React Testing Library
```

#### Infrastructure
```yaml
Container: Docker
Orchestration: Docker Compose (dev), K8s (prod)
Hosting: Railway (MVP), AWS ECS (scale)
CDN: CloudFlare
Monitoring: Sentry, Prometheus
Logging: ELK Stack or CloudWatch
```

### 1.3 Development Environment

```bash
# Project structure
invisible-invoice-reconciliation/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app entry
│   │   ├── config.py            # Settings management
│   │   ├── database.py          # DB connection
│   │   ├── auth/
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── endpoints/
│   │   │   │   └── deps.py     # Dependencies
│   │   ├── core/
│   │   │   ├── security.py
│   │   │   └── rls.py          # RLS helpers
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── utils/
│   ├── tests/
│   ├── alembic/                 # Migrations
│   └── requirements/
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── types/
│   └── package.json
├── docker/
├── docs/
└── scripts/
```

---

## 2. Database Design

### 2.1 Core Schema

```sql
-- Tenant management
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    settings JSONB DEFAULT '{}',
    subscription_tier VARCHAR(50) DEFAULT 'starter',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Users with tenant association
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user',
    mfa_secret VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    last_login TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, email)
);

-- Core invoice table
CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    invoice_number VARCHAR(255) NOT NULL,
    vendor_id UUID REFERENCES vendors(id),
    
    -- Amounts
    subtotal DECIMAL(12,2) NOT NULL,
    tax_amount DECIMAL(12,2) DEFAULT 0,
    total_amount DECIMAL(12,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    
    -- Dates
    invoice_date DATE NOT NULL,
    due_date DATE,
    received_date DATE DEFAULT CURRENT_DATE,
    
    -- References
    po_number VARCHAR(255),
    reference_number VARCHAR(255),
    
    -- Status tracking
    status VARCHAR(50) DEFAULT 'pending',
    match_status VARCHAR(50) DEFAULT 'unmatched',
    
    -- Metadata
    source VARCHAR(50), -- 'manual', 'csv', 'api'
    raw_data JSONB,
    attachments JSONB,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_invoice_per_tenant 
        UNIQUE(tenant_id, invoice_number, vendor_id)
);

-- Vendors with normalization
CREATE TABLE vendors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    
    -- Names
    legal_name VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    normalized_name VARCHAR(255), -- For matching
    
    -- Identifiers
    tax_id VARCHAR(50),
    vendor_code VARCHAR(100),
    
    -- Contact
    address JSONB,
    phone VARCHAR(50),
    email VARCHAR(255),
    
    -- Metadata
    category VARCHAR(100),
    payment_terms INTEGER, -- Days
    is_active BOOLEAN DEFAULT true,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_vendor_per_tenant 
        UNIQUE(tenant_id, normalized_name)
);

-- Purchase orders
CREATE TABLE purchase_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    po_number VARCHAR(255) NOT NULL,
    vendor_id UUID REFERENCES vendors(id),
    
    -- Amounts
    total_amount DECIMAL(12,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    
    -- Dates
    po_date DATE NOT NULL,
    expected_date DATE,
    
    -- Status
    status VARCHAR(50) DEFAULT 'open',
    
    -- Line items stored as JSONB for flexibility
    line_items JSONB,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_po_per_tenant 
        UNIQUE(tenant_id, po_number)
);

-- Receipts/Goods received
CREATE TABLE receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    receipt_number VARCHAR(255),
    po_id UUID REFERENCES purchase_orders(id),
    
    -- Details
    received_date DATE NOT NULL,
    total_amount DECIMAL(12,2),
    
    -- Items received
    line_items JSONB,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 2.2 Matching Tables

```sql
-- Matching rules configuration
CREATE TABLE matching_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name VARCHAR(100) NOT NULL,
    
    -- Tolerances
    price_tolerance_pct DECIMAL(5,2) DEFAULT 5.0,
    price_tolerance_abs DECIMAL(12,2) DEFAULT 10.0,
    quantity_tolerance_pct DECIMAL(5,2) DEFAULT 10.0,
    quantity_tolerance_abs INTEGER DEFAULT 5,
    date_tolerance_days INTEGER DEFAULT 7,
    
    -- Thresholds
    auto_approve_confidence DECIMAL(3,2) DEFAULT 0.85,
    min_match_confidence DECIMAL(3,2) DEFAULT 0.50,
    
    -- Vendor-specific overrides
    vendor_overrides JSONB DEFAULT '{}',
    
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT one_default_per_tenant 
        UNIQUE(tenant_id, is_default) WHERE is_default = true
);

-- Match results
CREATE TABLE match_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    
    -- Entities being matched
    invoice_id UUID REFERENCES invoices(id),
    po_id UUID REFERENCES purchase_orders(id),
    receipt_id UUID REFERENCES receipts(id),
    
    -- Matching details
    match_type VARCHAR(50) NOT NULL, -- 'exact', 'fuzzy', 'tolerance', 'manual'
    confidence_score DECIMAL(5,4) NOT NULL,
    
    -- Status
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
    
    -- Match breakdown
    match_details JSONB NOT NULL, -- Detailed scoring breakdown
    discrepancies JSONB, -- List of mismatches
    
    -- Review tracking
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    review_notes TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    INDEX idx_match_status (tenant_id, status),
    INDEX idx_match_confidence (confidence_score DESC)
);

-- Matching exceptions
CREATE TABLE match_exceptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    invoice_id UUID REFERENCES invoices(id),
    
    -- Exception details
    exception_type VARCHAR(50) NOT NULL, -- 'no_match', 'multiple_matches', 'below_threshold'
    priority VARCHAR(20) DEFAULT 'medium', -- 'high', 'medium', 'low'
    
    -- Suggested matches
    suggested_matches JSONB, -- Array of potential matches with scores
    
    -- Resolution
    status VARCHAR(50) DEFAULT 'open', -- 'open', 'in_review', 'resolved'
    assigned_to UUID REFERENCES users(id),
    resolved_by UUID REFERENCES users(id),
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution_notes TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    INDEX idx_exception_priority (tenant_id, priority, created_at)
);
```

### 2.3 Row Level Security (RLS)

```sql
-- Enable RLS on all tables
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendors ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_results ENABLE ROW LEVEL SECURITY;

-- Create policies
CREATE POLICY tenant_isolation_policy ON invoices
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant')::UUID);

CREATE POLICY tenant_isolation_policy ON vendors
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant')::UUID);

-- Function to set tenant context
CREATE OR REPLACE FUNCTION set_tenant_context(tenant_uuid UUID)
RETURNS void AS $$
BEGIN
    PERFORM set_config('app.current_tenant', tenant_uuid::TEXT, false);
END;
$$ LANGUAGE plpgsql;

-- Audit trigger for all tables
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_invoices_updated_at 
    BEFORE UPDATE ON invoices
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();
```

---

## 3. API Design

### 3.1 Authentication Endpoints

```yaml
POST /api/v1/auth/login:
  request:
    email: string
    password: string
    mfa_token?: string
  response:
    access_token: string
    refresh_token: string
    expires_in: number
    
POST /api/v1/auth/refresh:
  headers:
    Authorization: Bearer {refresh_token}
  response:
    access_token: string
    expires_in: number
    
POST /api/v1/auth/logout:
  headers:
    Authorization: Bearer {access_token}
  response:
    message: string
```

### 3.2 Invoice Management

```yaml
GET /api/v1/invoices:
  query:
    limit?: number (default: 50, max: 100)
    offset?: number (default: 0)
    status?: string
    vendor_id?: uuid
    date_from?: date
    date_to?: date
    sort_by?: string (default: created_at)
    sort_order?: asc|desc (default: desc)
  response:
    data: Invoice[]
    total: number
    limit: number
    offset: number
    
POST /api/v1/invoices:
  headers:
    Idempotency-Key: uuid
  request:
    invoice_number: string
    vendor_id: uuid
    total_amount: decimal
    invoice_date: date
    po_number?: string
  response:
    id: uuid
    status: string
    
POST /api/v1/invoices/bulk:
  headers:
    Idempotency-Key: uuid
  request:
    file: multipart/form-data
    options:
      skip_errors: boolean
      validate_only: boolean
  response:
    job_id: uuid
    status: pending|processing|complete
```

### 3.3 Matching Engine

```yaml
POST /api/v1/matching/run:
  request:
    invoice_ids?: uuid[]
    date_range?: {from: date, to: date}
    force_rematch?: boolean
  response:
    job_id: uuid
    invoices_queued: number
    
GET /api/v1/matching/results/{invoice_id}:
  response:
    matches: MatchResult[]
    best_match: MatchResult
    status: string
    
POST /api/v1/matching/approve:
  request:
    match_id: uuid
    notes?: string
  response:
    success: boolean
    
GET /api/v1/matching/exceptions:
  query:
    priority?: high|medium|low
    status?: open|in_review|resolved
    assigned_to?: uuid
  response:
    data: Exception[]
    stats:
      total: number
      by_priority: object
      avg_age_days: number
```

### 3.4 Error Handling (RFC 9457)

```json
// Validation Error
{
  "type": "https://api.invoice-recon.com/errors/validation",
  "title": "Validation Failed",
  "status": 400,
  "detail": "One or more fields failed validation",
  "instance": "/api/v1/invoices",
  "errors": [
    {
      "field": "total_amount",
      "message": "Must be a positive number",
      "value": -100
    }
  ]
}

// Business Logic Error
{
  "type": "https://api.invoice-recon.com/errors/business-rule",
  "title": "Business Rule Violation",
  "status": 422,
  "detail": "Invoice already exists for this vendor",
  "instance": "/api/v1/invoices",
  "duplicate_invoice_id": "550e8400-e29b-41d4"
}

// Authentication Error
{
  "type": "https://api.invoice-recon.com/errors/unauthorized",
  "title": "Authentication Required",
  "status": 401,
  "detail": "Access token has expired",
  "instance": "/api/v1/protected-resource"
}
```

---

## 4. Security Implementation

### 4.1 Authentication & Authorization

```python
# JWT token generation
from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext

class AuthService:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self.pwd_context = CryptContext(schemes=["bcrypt"])
        self.algorithm = "HS256"
    
    def create_access_token(
        self, 
        user_id: str, 
        tenant_id: str,
        permissions: List[str]
    ) -> str:
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "permissions": permissions,
            "exp": datetime.utcnow() + timedelta(minutes=15),
            "iat": datetime.utcnow(),
            "type": "access"
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def verify_password(self, plain: str, hashed: str) -> bool:
        return self.pwd_context.verify(plain, hashed)
    
    def hash_password(self, password: str) -> str:
        return self.pwd_context.hash(password)
```

### 4.2 Database Connection with RLS

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def get_db_with_tenant(
    tenant_id: str,
    db: AsyncSession
) -> AsyncSession:
    """Set tenant context for RLS"""
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
        {"tenant_id": tenant_id}
    )
    return db

# FastAPI dependency
async def get_current_tenant_db(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> AsyncSession:
    payload = verify_token(token)
    tenant_id = payload.get("tenant_id")
    return await get_db_with_tenant(tenant_id, db)
```

### 4.3 Idempotency Implementation

```python
from fastapi import Header, HTTPException
import redis.asyncio as redis
import json
import hashlib

class IdempotencyService:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.ttl = 86400  # 24 hours
    
    async def check_idempotency(
        self,
        key: str,
        request_body: dict,
        path: str
    ) -> Optional[dict]:
        # Create cache key
        cache_key = f"idempotency:{key}"
        
        # Check if key exists
        cached = await self.redis.get(cache_key)
        if cached:
            cached_data = json.loads(cached)
            
            # Verify same request
            request_hash = hashlib.sha256(
                json.dumps(request_body, sort_keys=True).encode()
            ).hexdigest()
            
            if cached_data["hash"] != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key used with different request"
                )
            
            return cached_data["response"]
        
        return None
    
    async def save_response(
        self,
        key: str,
        request_body: dict,
        response: dict
    ):
        cache_key = f"idempotency:{key}"
        request_hash = hashlib.sha256(
            json.dumps(request_body, sort_keys=True).encode()
        ).hexdigest()
        
        data = {
            "hash": request_hash,
            "response": response
        }
        
        await self.redis.setex(
            cache_key,
            self.ttl,
            json.dumps(data)
        )
```

---

## 5. Matching Engine Algorithm

### 5.1 Core Matching Logic

```python
from typing import List, Optional, Tuple
from dataclasses import dataclass
import Levenshtein
import re

@dataclass
class MatchResult:
    match_type: str
    confidence: float
    po_id: Optional[str]
    receipt_id: Optional[str]
    details: dict
    discrepancies: List[dict]

class MatchingEngine:
    def __init__(self, rules: MatchingRules):
        self.rules = rules
        
    async def match_invoice(
        self,
        invoice: Invoice,
        purchase_orders: List[PurchaseOrder],
        receipts: List[Receipt]
    ) -> MatchResult:
        """
        Three-way matching algorithm
        Priority: Exact > Fuzzy > Tolerance > Exception
        """
        
        # Step 1: Try exact match
        exact_match = self._exact_match(invoice, purchase_orders, receipts)
        if exact_match and exact_match.confidence >= 1.0:
            return exact_match
        
        # Step 2: Try fuzzy match
        fuzzy_matches = self._fuzzy_match(invoice, purchase_orders, receipts)
        if fuzzy_matches:
            best_match = max(fuzzy_matches, key=lambda x: x.confidence)
            if best_match.confidence >= self.rules.auto_approve_confidence:
                return best_match
        
        # Step 3: Try tolerance-based match
        tolerance_matches = self._tolerance_match(
            invoice, purchase_orders, receipts
        )
        if tolerance_matches:
            best_match = max(tolerance_matches, key=lambda x: x.confidence)
            if best_match.confidence >= self.rules.min_match_confidence:
                return best_match
        
        # Step 4: Create exception
        return MatchResult(
            match_type="exception",
            confidence=0.0,
            po_id=None,
            receipt_id=None,
            details={"reason": "no_match_found"},
            discrepancies=[]
        )
    
    def _exact_match(
        self,
        invoice: Invoice,
        purchase_orders: List[PurchaseOrder],
        receipts: List[Receipt]
    ) -> Optional[MatchResult]:
        """Check for exact matches on key fields"""
        
        for po in purchase_orders:
            # Match on PO number
            if invoice.po_number and invoice.po_number == po.po_number:
                # Check amount
                if abs(invoice.total_amount - po.total_amount) < 0.01:
                    # Find corresponding receipt
                    receipt = self._find_receipt_for_po(po, receipts)
                    
                    return MatchResult(
                        match_type="exact",
                        confidence=1.0,
                        po_id=po.id,
                        receipt_id=receipt.id if receipt else None,
                        details={
                            "matched_fields": ["po_number", "amount"],
                            "match_method": "exact"
                        },
                        discrepancies=[]
                    )
        
        return None
    
    def _fuzzy_match(
        self,
        invoice: Invoice,
        purchase_orders: List[PurchaseOrder],
        receipts: List[Receipt]
    ) -> List[MatchResult]:
        """Fuzzy matching with OCR error tolerance"""
        
        matches = []
        
        for po in purchase_orders:
            score = 0.0
            matched_fields = []
            discrepancies = []
            
            # Fuzzy match PO number
            if invoice.po_number and po.po_number:
                similarity = self._string_similarity(
                    invoice.po_number,
                    po.po_number
                )
                if similarity > 0.8:
                    score += similarity * 0.4
                    matched_fields.append("po_number_fuzzy")
                else:
                    discrepancies.append({
                        "field": "po_number",
                        "expected": po.po_number,
                        "actual": invoice.po_number,
                        "similarity": similarity
                    })
            
            # Check amount within tolerance
            amount_diff_pct = abs(
                (invoice.total_amount - po.total_amount) / po.total_amount
            ) * 100
            
            if amount_diff_pct <= self.rules.price_tolerance_pct:
                score += (1 - amount_diff_pct / 100) * 0.3
                matched_fields.append("amount_tolerance")
            else:
                discrepancies.append({
                    "field": "amount",
                    "expected": po.total_amount,
                    "actual": invoice.total_amount,
                    "difference_pct": amount_diff_pct
                })
            
            # Check vendor match
            if invoice.vendor_id == po.vendor_id:
                score += 0.2
                matched_fields.append("vendor")
            
            # Check date proximity
            date_diff = abs((invoice.invoice_date - po.po_date).days)
            if date_diff <= self.rules.date_tolerance_days:
                score += (1 - date_diff / 30) * 0.1
                matched_fields.append("date_proximity")
            
            if score > 0.5:
                receipt = self._find_receipt_for_po(po, receipts)
                matches.append(MatchResult(
                    match_type="fuzzy",
                    confidence=score,
                    po_id=po.id,
                    receipt_id=receipt.id if receipt else None,
                    details={
                        "matched_fields": matched_fields,
                        "match_method": "fuzzy"
                    },
                    discrepancies=discrepancies
                ))
        
        return matches
    
    def _string_similarity(self, str1: str, str2: str) -> float:
        """Calculate string similarity with OCR error handling"""
        
        # Normalize strings
        str1 = self._normalize_for_matching(str1)
        str2 = self._normalize_for_matching(str2)
        
        # Handle common OCR errors
        str1 = self._fix_ocr_errors(str1)
        str2 = self._fix_ocr_errors(str2)
        
        # Calculate Levenshtein ratio
        return Levenshtein.ratio(str1, str2)
    
    def _normalize_for_matching(self, text: str) -> str:
        """Normalize text for matching"""
        if not text:
            return ""
        
        # Convert to uppercase
        text = text.upper()
        
        # Remove special characters except alphanumeric
        text = re.sub(r'[^A-Z0-9]', '', text)
        
        return text
    
    def _fix_ocr_errors(self, text: str) -> str:
        """Fix common OCR misreads"""
        replacements = {
            '0': 'O', 'O': '0',  # Zero/O confusion
            '1': 'I', 'I': '1',  # One/I confusion
            '5': 'S', 'S': '5',  # Five/S confusion
            '6': 'G',            # Six/G confusion
            '8': 'B',            # Eight/B confusion
        }
        
        # Try both versions for ambiguous characters
        return text  # Simplified for now
```

---

## 6. Performance Optimization

### 6.1 Database Indexing

```sql
-- Performance indexes
CREATE INDEX idx_invoices_status 
    ON invoices(tenant_id, status) 
    WHERE status IN ('pending', 'processing');

CREATE INDEX idx_invoices_date_range 
    ON invoices(tenant_id, invoice_date DESC);

CREATE INDEX idx_vendors_normalized 
    ON vendors(tenant_id, normalized_name);

CREATE INDEX idx_match_results_pending 
    ON match_results(tenant_id, status) 
    WHERE status = 'pending';

-- Full-text search
CREATE INDEX idx_vendors_search 
    ON vendors USING gin(
        to_tsvector('english', 
            coalesce(legal_name, '') || ' ' || 
            coalesce(display_name, '')
        )
    );
```

### 6.2 Caching Strategy

```python
# Redis caching configuration
CACHE_CONFIG = {
    "tenant_settings": 3600,      # 1 hour
    "matching_rules": 1800,        # 30 minutes
    "vendor_list": 900,            # 15 minutes
    "dashboard_stats": 300,        # 5 minutes
    "user_session": 900,           # 15 minutes
}

# Cache decorator
from functools import wraps
import pickle

def cache_result(key_prefix: str, ttl: int):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = f"{key_prefix}:{args}:{kwargs}"
            
            # Check cache
            cached = await redis.get(cache_key)
            if cached:
                return pickle.loads(cached)
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            await redis.setex(
                cache_key,
                ttl,
                pickle.dumps(result)
            )
            
            return result
        return wrapper
    return decorator
```

### 6.3 Async Processing

```python
# Background job processing
from rq import Queue
from redis import Redis

redis_conn = Redis()
queue = Queue(connection=redis_conn)

# Enqueue matching job
def enqueue_matching_job(invoice_ids: List[str]):
    job = queue.enqueue(
        'app.tasks.matching.process_invoices',
        invoice_ids,
        job_timeout='10m',
        result_ttl=86400,
        failure_ttl=86400
    )
    return job.id

# Task implementation
async def process_invoices(invoice_ids: List[str]):
    """Process invoices in background"""
    async with get_db() as db:
        for invoice_id in invoice_ids:
            try:
                invoice = await get_invoice(db, invoice_id)
                result = await matching_engine.match_invoice(invoice)
                await save_match_result(db, result)
            except Exception as e:
                logger.error(f"Failed to process {invoice_id}: {e}")
                continue
```

---

## 7. Testing Strategy

### 7.1 Unit Testing

```python
# Test example for matching engine
import pytest
from decimal import Decimal

@pytest.mark.asyncio
async def test_exact_match():
    """Test exact matching logic"""
    
    # Setup
    invoice = Invoice(
        po_number="PO-12345",
        total_amount=Decimal("1000.00"),
        vendor_id="vendor-1"
    )
    
    purchase_order = PurchaseOrder(
        po_number="PO-12345",
        total_amount=Decimal("1000.00"),
        vendor_id="vendor-1"
    )
    
    # Execute
    engine = MatchingEngine(default_rules)
    result = await engine.match_invoice(
        invoice, 
        [purchase_order], 
        []
    )
    
    # Assert
    assert result.match_type == "exact"
    assert result.confidence == 1.0
    assert result.po_id == purchase_order.id
    assert len(result.discrepancies) == 0

@pytest.mark.asyncio
async def test_fuzzy_match_with_ocr_errors():
    """Test fuzzy matching with OCR errors"""
    
    # Invoice with OCR error (O instead of 0)
    invoice = Invoice(
        po_number="PO-1234O",  # OCR error
        total_amount=Decimal("1000.00"),
        vendor_id="vendor-1"
    )
    
    purchase_order = PurchaseOrder(
        po_number="PO-12340",  # Correct
        total_amount=Decimal("1000.00"),
        vendor_id="vendor-1"
    )
    
    # Execute
    engine = MatchingEngine(default_rules)
    result = await engine.match_invoice(
        invoice,
        [purchase_order],
        []
    )
    
    # Assert
    assert result.match_type == "fuzzy"
    assert result.confidence > 0.8
    assert result.po_id == purchase_order.id
```

### 7.2 Integration Testing

```python
# API integration test
from fastapi.testclient import TestClient

def test_invoice_creation_with_idempotency():
    """Test idempotent invoice creation"""
    
    client = TestClient(app)
    
    # First request
    response1 = client.post(
        "/api/v1/invoices",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "test-key-123"
        },
        json={
            "invoice_number": "INV-001",
            "vendor_id": "vendor-1",
            "total_amount": 1000.00,
            "invoice_date": "2024-01-15"
        }
    )
    
    assert response1.status_code == 201
    invoice_id = response1.json()["id"]
    
    # Duplicate request with same idempotency key
    response2 = client.post(
        "/api/v1/invoices",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "test-key-123"
        },
        json={
            "invoice_number": "INV-001",
            "vendor_id": "vendor-1",
            "total_amount": 1000.00,
            "invoice_date": "2024-01-15"
        }
    )
    
    assert response2.status_code == 201
    assert response2.json()["id"] == invoice_id
```

### 7.3 Performance Testing

```python
# Locust performance test
from locust import HttpUser, task, between

class InvoiceUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        """Login and get token"""
        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "test@example.com",
                "password": "password"
            }
        )
        self.token = response.json()["access_token"]
    
    @task
    def list_invoices(self):
        self.client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {self.token}"}
        )
    
    @task
    def get_invoice_detail(self):
        invoice_id = "test-invoice-id"
        self.client.get(
            f"/api/v1/invoices/{invoice_id}",
            headers={"Authorization": f"Bearer {self.token}"}
        )
    
    @task
    def run_matching(self):
        self.client.post(
            "/api/v1/matching/run",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"invoice_ids": ["invoice-1", "invoice-2"]}
        )
```

---

## 8. Deployment & DevOps

### 8.1 Docker Configuration

```dockerfile
# Backend Dockerfile
FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements/base.txt .
RUN pip install --no-cache-dir -r base.txt

# Copy application
COPY ./app ./app
COPY ./alembic ./alembic
COPY alembic.ini .

# Run migrations and start server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

# Frontend Dockerfile
FROM node:18-alpine AS frontend-base

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --only=production

# Copy application
COPY . .

# Build
RUN npm run build

# Production image
FROM node:18-alpine

WORKDIR /app

COPY --from=frontend-base /app/.next ./.next
COPY --from=frontend-base /app/public ./public
COPY --from=frontend-base /app/package*.json ./

RUN npm ci --only=production

CMD ["npm", "start"]
```

### 8.2 Docker Compose

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: invoice_recon
      POSTGRES_USER: app_user
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app_user"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql://app_user:${DB_PASSWORD}@postgres:5432/invoice_recon
      REDIS_URL: redis://redis:6379/0
      JWT_SECRET: ${JWT_SECRET}
      ENABLE_RLS: "true"
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - ./backend:/app

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    environment:
      NEXT_PUBLIC_API_URL: http://backend:8000
    ports:
      - "3000:3000"
    depends_on:
      - backend

volumes:
  postgres_data:
  redis_data:
```

### 8.3 Monitoring & Logging

```python
# Sentry integration
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    integrations=[
        FastApiIntegration(transaction_style="endpoint"),
        SqlalchemyIntegration(),
    ],
    traces_sample_rate=0.1,
    environment=settings.ENVIRONMENT,
)

# Structured logging
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()
```

---

## 9. Development Workflow

### 9.1 JJ (Jujutsu) Commands

```bash
# Initialize colocated repository
jj git init --colocate

# Daily workflow
jj new -m "feat: implement invoice upload API"
# ... make changes to ≤8 files, ≤400 LOC ...

jj describe -m "Add multipart upload handling and validation"

# Continue with next micro-batch
jj new -m "feat: add CSV parsing logic"
# ... implement CSV parser ...

# Squash related changes
jj squash -i  # Interactive squash

# Review changes
jj diff

# Push to remote
jj git push

# If you need to undo
jj undo

# View operation log
jj op log
```

### 9.2 Code Quality Standards

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/charliermarsh/ruff-pre-commit
    rev: v0.1.0
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]

  - repo: https://github.com/psf/black
    rev: 23.1.0
    hooks:
      - id: black

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.0.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]

# ruff.toml
line-length = 88
select = ["E", "F", "B", "W", "I", "N", "UP"]
ignore = ["E501"]  # Line length handled by black
target-version = "py311"

[per-file-ignores]
"tests/*" = ["S101"]  # Allow assert in tests
```

---

## 10. Appendix

### 10.1 Environment Variables

```bash
# .env.example

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/invoice_recon
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=0

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
JWT_SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Features
ENABLE_RLS=true
ENABLE_MFA=true
ENABLE_IDEMPOTENCY=true

# External Services
SENTRY_DSN=https://key@sentry.io/project
QUICKBOOKS_CLIENT_ID=
QUICKBOOKS_CLIENT_SECRET=

# Environment
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=info
```

### 10.2 API Rate Limiting

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"]
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Different limits for different endpoints
@app.post("/api/v1/auth/login")
@limiter.limit("5/minute")
async def login():
    pass

@app.post("/api/v1/invoices/bulk")
@limiter.limit("10/hour")
async def bulk_upload():
    pass
```

---

*Technical specification maintained by Engineering. Last updated: January 2025*