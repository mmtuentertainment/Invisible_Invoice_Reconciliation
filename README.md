# Invisible Invoice Reconciliation Platform

> Automating AP workflows for SMB-MM companies, reducing invoice processing costs by 80%

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104%2B-green)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-blue)](https://www.postgresql.org/)
[![Next.js](https://img.shields.io/badge/Next.js-14%2B-black)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Proprietary-red)](LICENSE)

## 🎯 Overview

The Invisible Invoice Reconciliation Platform addresses the **$3.5B AP automation market**, targeting SMB and mid-market companies processing 100-500 invoices monthly. Our platform reduces invoice processing costs from **$15-16 to $3 per invoice** while achieving **70-80% time savings**.

### Key Features
- **3-Way Matching**: Automatic PO ↔ Receipt ↔ Invoice reconciliation
- **Smart CSV Import**: RFC 4180 compliant bulk processing
- **Vendor Normalization**: Eliminate duplicates with fuzzy matching
- **Multi-tenant Architecture**: Secure isolation with PostgreSQL RLS
- **Configurable Tolerances**: Business rules for auto-approval
- **Exception Management**: Prioritized queue for manual review

## 📊 Value Proposition

| Metric | Current State | With Our Platform | Improvement |
|--------|--------------|-------------------|-------------|
| Cost per Invoice | $15-16 | $3 | **80% reduction** |
| Processing Time | 8-10 days | <1 day | **90% faster** |
| Error Rate | 1.6% | <0.5% | **70% fewer errors** |
| Manual Work | 15-30 min/exception | 2-3 min/exception | **85% reduction** |

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Next.js UI │────▶│ FastAPI Backend│────▶│ PostgreSQL  │
│ (TypeScript)│     │  (Python 3.11) │     │  with RLS   │
└─────────────┘     └──────────────┘     └─────────────┘
                           │                      │
                    ┌──────┴───────┐       ┌─────┴──────┐
                    │ Redis Cache  │       │ S3 Storage │
                    └──────────────┘       └────────────┘
```

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+
- Redis 7+
- Docker & Docker Compose

### Development Setup

1. **Clone the repository**
```bash
git clone https://github.com/mmtuentertainment/Invisible_Invoice_Reconciliation.git
cd Invisible_Invoice_Reconciliation
```

2. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. **Start services with Docker Compose**
```bash
docker-compose up -d
```

4. **Install backend dependencies**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements/dev.txt
```

5. **Run database migrations**
```bash
alembic upgrade head
```

6. **Start backend server**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

7. **Install and start frontend**
```bash
cd ../frontend
npm install
npm run dev
```

8. **Access the application**
- Frontend: http://localhost:3000
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## 📁 Project Structure

```
invisible-invoice-reconciliation/
├── backend/                 # FastAPI backend application
│   ├── app/
│   │   ├── api/            # API endpoints
│   │   ├── auth/           # Authentication logic
│   │   ├── core/           # Core utilities
│   │   ├── models/         # SQLAlchemy models
│   │   ├── schemas/        # Pydantic schemas
│   │   └── services/       # Business logic
│   ├── tests/              # Test suite
│   └── alembic/            # Database migrations
├── frontend/               # Next.js frontend
│   ├── src/
│   │   ├── pages/         # Next.js pages
│   │   ├── components/    # React components
│   │   └── services/      # API clients
│   └── public/            # Static assets
├── docs/                  # Documentation
│   ├── PRD.md            # Product Requirements
│   ├── user-stories.md   # Detailed user stories
│   ├── technical-spec.md # Technical specification
│   └── epic-breakdown.md # Development epics
└── docker/               # Docker configurations
```

## 🔧 Technology Stack

### Backend
- **Language**: Python 3.11+
- **Framework**: FastAPI 0.104+
- **ORM**: SQLAlchemy 2.0 (async)
- **Database**: PostgreSQL 15+ with RLS
- **Cache**: Redis 7+
- **Testing**: pytest, pytest-asyncio

### Frontend
- **Framework**: Next.js 14+
- **UI Library**: React 18+
- **Language**: TypeScript 5+
- **Styling**: Tailwind CSS 3+
- **State**: React Query / Zustand

### Infrastructure
- **Container**: Docker
- **CI/CD**: GitHub Actions
- **Hosting**: Railway (MVP) → AWS (Scale)
- **Monitoring**: Sentry, Prometheus
- **VCS**: Git with JJ (Jujutsu)

## 🧪 Testing

### Run Tests
```bash
# Backend tests
cd backend
pytest tests/ -v --cov=app --cov-report=html

# Frontend tests
cd frontend
npm run test
npm run test:e2e
```

### Code Quality
```bash
# Backend
ruff check .
black .
mypy app/

# Frontend
npm run lint
npm run type-check
```

## 🔐 Security

- **Multi-tenancy**: PostgreSQL Row Level Security (RLS)
- **Authentication**: JWT with MFA/TOTP support
- **API Security**: RFC 9457 error handling, rate limiting
- **Data Protection**: Field-level encryption for PII
- **Idempotency**: All mutations are idempotent
- **Compliance**: SOC 2 Type I ready

## 📚 Documentation

- [Product Requirements Document](docs/PRD.md)
- [User Stories](docs/user-stories.md)
- [Technical Specification](docs/technical-spec.md)
- [Epic Breakdown](docs/epic-breakdown.md)
- [API Documentation](http://localhost:8000/docs)

## 🗺️ Roadmap

### MVP (8 weeks)
- [x] Core infrastructure & security
- [x] CSV document processing
- [x] 3-way matching engine
- [ ] Basic UI
- [ ] Testing & deployment

### v1.1 (Q2 2025)
- [ ] Vendor normalization
- [ ] QuickBooks integration
- [ ] Advanced analytics
- [ ] Email notifications

### v1.2 (Q3 2025)
- [ ] Banking API integration
- [ ] Payment automation
- [ ] Mobile application
- [ ] EU e-invoicing compliance

## 👥 Team

- **Product Manager**: Define requirements and priorities
- **Backend Engineers**: 2 FTE for core platform
- **Frontend Engineers**: 1.5 FTE for UI
- **DevOps Engineer**: 0.5 FTE for infrastructure
- **QA Engineer**: 0.5 FTE for testing

## 🤝 Contributing

We use JJ (Jujutsu) for version control with Git colocation:

```bash
# Initialize JJ repository
jj git init --colocate

# Create new change
jj new -m "feat: your feature description"

# Make changes (≤8 files, ≤400 LOC per batch)
# ...

# Describe change
jj describe -m "Detailed description"

# Push to remote
jj git push
```

### Development Principles
- **KISS**: Keep It Simple, Stupid
- **YAGNI**: You Aren't Gonna Need It
- **DIW**: Do It Well
- **Micro-batches**: ≤8 files, ≤400 LOC, ≤2 runtime domains

## 📊 Success Metrics

### Technical
- 95% auto-match rate on clean data
- <500ms p95 API response time
- Process 100 invoices in <5 seconds
- 99.5% uptime SLA

### Business
- 25 customers in 6 months
- $15K MRR by month 6
- 90% customer retention
- $34K annual savings per customer

## 📝 License

This project is proprietary software. All rights reserved.

## 📞 Support

- **Documentation**: See `/docs` folder
- **Issues**: GitHub Issues
- **Email**: support@invoice-recon.com

---

*Built with ❤️ for SMB finance teams struggling with manual invoice processing*