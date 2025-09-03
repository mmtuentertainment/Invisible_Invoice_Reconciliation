# BMad Method - Complete Reference Guide

## Overview

This document provides a comprehensive reference for all BMad Method tools, agents, and capabilities installed in your Invisible Invoice Reconciliation project.

## Installation Summary

Your project includes:
- **BMad Agile Core System** (v4.43.0)
- **Infrastructure DevOps Pack** (v1.12.0) 
- **Creative Writing Studio** (v1.1.1)
- **Claude Code Integration**
- **Gemini CLI Integration**
- **Codex CLI Integration**
- **Web Bundles** (all available bundles)

## Core BMad Agents

### Primary Development Agents

#### `/analyst`
- **Purpose**: Market research, competitive analysis, project briefs
- **When to use**: Project inception, market validation, research phase
- **Key capabilities**: Brainstorming, market research, competitor analysis

#### `/pm` (Product Manager)
- **Purpose**: Product Requirements Document (PRD) creation and management
- **When to use**: Planning phase, requirements gathering
- **Key capabilities**: PRD creation, functional/non-functional requirements, epics & stories

#### `/architect`
- **Purpose**: System architecture design and technical specifications
- **When to use**: After PRD completion, technical planning phase
- **Key capabilities**: Architecture documentation, system design, technology stack decisions

#### `/ux-expert`
- **Purpose**: User experience design and frontend specifications
- **When to use**: UI/UX design phase, user journey mapping
- **Key capabilities**: Frontend specs, UI prompts for tools like Lovable/V0

#### `/po` (Product Owner)
- **Purpose**: Document validation, sharding, and alignment
- **When to use**: Validation phase, document management
- **Key capabilities**: Master checklist execution, document sharding, epic/story validation

#### `/sm` (Scrum Master)
- **Purpose**: Story creation and sprint management
- **When to use**: Development cycle, story drafting
- **Key capabilities**: Story drafting from epics, development workflow management

#### `/dev` (Developer)
- **Purpose**: Code implementation and development
- **When to use**: Development phase, feature implementation
- **Key capabilities**: Sequential task execution, code implementation, testing

#### `/qa` (Test Architect)
- **Purpose**: Quality assurance, testing strategy, quality gates
- **When to use**: Throughout development cycle, quality validation
- **Key capabilities**: Risk assessment, test design, coverage analysis, quality gates

### Master Agents

#### `/bmad-master`
- **Purpose**: Multi-role agent capable of all tasks except story implementation
- **When to use**: When you want a single agent for multiple roles
- **Key capabilities**: All agent capabilities combined, conversation compaction

#### `/bmad-orchestrator`
- **Purpose**: Heavy-duty orchestration agent (primarily for web bundles)
- **When to use**: Complex multi-agent workflows, web platform usage
- **Key capabilities**: Agent morphing, comprehensive workflow management

## Infrastructure DevOps Pack

### `/infra-devops-platform`
- **Purpose**: Infrastructure architecture, DevOps workflows, platform management
- **When to use**: Infrastructure setup, deployment planning, DevOps implementation
- **Key capabilities**: 
  - Infrastructure architecture design
  - CI/CD pipeline creation
  - Container orchestration
  - Cloud platform setup
  - Monitoring and observability
  - Security and compliance

## Creative Writing Studio Pack

*Note: These agents are available but not relevant to your invoice reconciliation project*

### Available Creative Writing Agents:
- `/world-builder` - World and setting creation
- `/plot-architect` - Plot structure and story arcs
- `/narrative-designer` - Narrative flow and pacing
- `/character-psychologist` - Character development
- `/dialog-specialist` - Dialog writing and improvement
- `/editor` - Content editing and refinement
- `/genre-specialist` - Genre-specific guidance
- `/cover-designer` - Book cover concepts
- `/book-critic` - Critical analysis
- `/beta-reader` - Reader feedback simulation

## Core BMad Tasks

### Planning & Research Tasks
- `/advanced-elicitation` - Advanced requirement gathering
- `/facilitate-brainstorming-session` - Structured brainstorming
- `/create-deep-research-prompt` - Deep research planning
- `/document-project` - Project documentation

### Story & Epic Management
- `/create-next-story` - Generate next development story
- `/validate-next-story` - Validate story readiness
- `/shard-doc` - Break documents into manageable pieces
- `/create-brownfield-story` - Stories for existing projects
- `/brownfield-create-epic` - Epics for existing projects
- `/brownfield-create-story` - Brownfield-specific stories

### Quality Assurance Tasks
- `/risk-profile` - Assess implementation risks
- `/test-design` - Create comprehensive test strategies
- `/trace-requirements` - Map requirements to test coverage
- `/nfr-assess` - Non-functional requirements assessment
- `/review-story` - Comprehensive story review
- `/qa-gate` - Quality gate management
- `/apply-qa-fixes` - Apply quality-based fixes

### Development Support
- `/execute-checklist` - Run validation checklists
- `/correct-course` - Course correction for development
- `/create-doc` - General document creation
- `/index-docs` - Document indexing and organization

### Advanced Features
- `/generate-ai-frontend-prompt` - Generate UI/UX prompts
- `/kb-mode-interaction` - Knowledge base interaction

## Infrastructure Tasks

- `/validate-infrastructure` - Infrastructure validation
- `/review-infrastructure` - Infrastructure review and assessment
- `/create-doc` - Infrastructure documentation

## BMad Workflow Integration Points

### Planning Phase (Web UI recommended)
1. `/analyst` → Project research and brief
2. `/pm` → PRD creation with FRs, NFRs, epics, stories
3. `/ux-expert` → Frontend specifications (optional)
4. `/architect` → System architecture
5. `/qa` → Early test strategy (optional)
6. `/po` → Master checklist and document alignment

### Development Phase (IDE)
1. `/po` → Document sharding
2. `/sm` → Story drafting
3. `/qa` → Risk assessment and test design (high-risk stories)
4. `/dev` → Implementation
5. `/qa` → Mid-development validation
6. `/qa` → Final review and quality gates

## File Structure Created

```
.bmad-core/                     # Core BMad framework
├── agents/                     # Agent definitions
├── tasks/                      # Task definitions
├── templates/                  # Document templates
├── data/                       # Knowledge base and preferences
└── workflows/                  # Workflow definitions

.bmad-infrastructure-devops/    # Infrastructure expansion
├── agents/                     # DevOps agents
├── tasks/                      # Infrastructure tasks
└── templates/                  # Infrastructure templates

.bmad-creative-writing/         # Creative writing expansion
├── agents/                     # Writing agents
├── tasks/                      # Writing tasks
└── templates/                  # Writing templates

.claude/commands/               # Claude Code slash commands
├── BMad/                       # Core agents and tasks
├── bmadInfraDevOps/           # Infrastructure commands
└── bmad-cw/                   # Creative writing commands

web-bundles/                    # Standalone web bundles
├── agents/                     # Individual agent bundles
├── teams/                      # Team bundles
└── expansion-packs/           # Expansion pack bundles
```

## Configuration Files

- `AGENTS.md` - Codex CLI integration with full agent directory
- `.gitignore` - Git ignore patterns for BMad files
- `.bmad-core/core-config.yaml` - Core BMad configuration
- `.bmad-core/data/technical-preferences.md` - Your technical preferences

## Usage Recommendations for Invoice Reconciliation Project

### Essential Agents for Your Project:
1. **`/pm`** - Create comprehensive PRD for invoice reconciliation system
2. **`/architect`** - Design system architecture for financial data processing
3. **`/infra-devops-platform`** - Set up secure, compliant infrastructure
4. **`/dev`** - Implement reconciliation algorithms and UI
5. **`/qa`** - Ensure financial accuracy and security compliance

### Recommended Workflow:
1. Start with `/pm` to define requirements
2. Use `/architect` to design the system
3. Leverage `/infra-devops-platform` for secure infrastructure
4. Use `/po` to shard documents
5. Implement with `/dev` and validate with `/qa`

### Key Considerations for Financial Applications:
- Security and compliance requirements
- Data accuracy and integrity
- Audit trails and logging
- Performance for large datasets
- Error handling and reconciliation exceptions

## Getting Started

1. **Restart Claude Code** to load all slash commands
2. Begin with `/pm` to create your project requirements
3. Use `/architect` to design your invoice reconciliation system
4. Set up infrastructure with `/infra-devops-platform`
5. Follow the BMad development workflow for implementation

## Support Resources

- User Guide: `.bmad-core/user-guide.md`
- GitHub Repository: https://github.com/bmad-code-org/BMAD-METHOD
- Discord Community: Available through GitHub repository
- Working in Brownfield: `.bmad-core/working-in-the-brownfield.md`