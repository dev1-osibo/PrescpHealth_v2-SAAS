---
inclusion: always
---

# Documentation Standards — PrescpHealth Rebuild

## Core Principle

Code without documentation is a liability. Every module must be self-explanatory to a new developer joining the team. Documentation lives alongside the code it describes — not in a separate wiki that goes stale.

## README Per Module

Every module directory MUST contain a README.md explaining:

1. **Purpose** — what this module does in 1-2 sentences
2. **Key concepts** — domain terms and business rules specific to this module
3. **Dependencies** — what this module imports from other modules
4. **API surface** — public functions/classes exposed (brief summary, details in docstrings)
5. **How to test** — command to run this module's tests in isolation
6. **HIPAA considerations** — what PHI this module handles and how it's protected

Example locations:
```
backend/app/modules/auth/README.md
backend/app/modules/patients/README.md
backend/app/modules/risk_engine/README.md
backend/app/core/README.md
ml/risk_engine/README.md
ml/forecast_engine/README.md
frontend/src/components/risk/README.md
```

## OpenAPI Specification

- Auto-generated from FastAPI route annotations and Pydantic schemas
- Kept in sync automatically — no manual OpenAPI YAML files
- Every endpoint must have:
  - Summary (short description)
  - Description (detailed explanation including business context)
  - Request/response schema with field descriptions
  - Example values for request and response
  - Error response documentation (all possible error codes)
  - Security requirements (which roles can access)
- Accessible at `/docs` (Swagger UI) and `/redoc` (ReDoc) in development
- Disabled in production (security — don't expose API surface publicly)

## Architecture Decision Records (ADRs)

For every significant technical decision, create an ADR in `docs/adr/`:

### Format
```markdown
# ADR-{number}: {Title}

## Status
Accepted | Superseded by ADR-{n} | Deprecated

## Context
What is the issue that we're seeing that is motivating this decision?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or more difficult because of this change?

## Alternatives Considered
What other options were evaluated and why were they rejected?
```

### When to Write an ADR
- Choosing between competing technologies (e.g., why XGBoost + LightGBM ensemble over single model)
- Architectural patterns (e.g., why event-driven over direct service calls)
- Security decisions (e.g., why RLS over application-level tenant filtering)
- Data model decisions (e.g., why JSONB for diagnoses over normalized tables)
- Infrastructure choices (e.g., why Celery over background threads)

## Inline Documentation (Code-Level)

Covered in detail by `code-style.md` steering rule. Summary:
- Module-level docstring explaining the file's purpose
- Class-level docstring explaining responsibility and usage
- Function-level docstring with params, returns, raises, and side effects
- Inline comments for non-obvious logic (the "why")

## Changelog

Maintain a `CHANGELOG.md` at project root following Keep a Changelog format:

```markdown
# Changelog

## [Unreleased]

### Added
- Patient profile versioning with full audit trail (REQ-4.5)

### Changed
- Risk computation now uses ensemble of 4 models instead of 3

### Fixed
- Token rotation reuse detection was not invalidating full family

### Security
- Added rate limiting to patient search endpoint (1000 req/min)
```

## API Versioning Documentation

- Document breaking changes between API versions
- Provide migration guides when endpoints change
- Deprecation notices must appear at least 1 version before removal
- Never remove an endpoint without a documented replacement

## Deployment Documentation

Maintain `docs/deployment/` with:
- `local-setup.md` — how to run the full stack locally (Docker Compose)
- `environment-variables.md` — every env var with description, example, and whether required
- `database-setup.md` — how to run migrations, seed data, connect to DB
- `troubleshooting.md` — common issues and solutions
