---
inclusion: always
---

# Dependency Management — PrescpHealth Rebuild

## Core Principle

Every dependency is a liability. Each one adds attack surface, maintenance burden, and potential for supply chain compromise. For a HIPAA-regulated clinical platform, we must be deliberate about what we bring in.

## Version Pinning

- **Python (pyproject.toml)**: Pin EXACT versions. No `>=`, no `~=`, no `^`.
  ```toml
  # Good
  fastapi = "0.109.0"
  sqlalchemy = "2.0.25"
  
  # Bad
  fastapi = ">=0.109.0"
  sqlalchemy = "^2.0"
  ```

- **JavaScript (package.json)**: Pin EXACT versions. No `^`, no `~`.
  ```json
  // Good
  "react": "18.2.0",
  "axios": "1.6.5"
  
  // Bad
  "react": "^18.2.0",
  "axios": "~1.6.5"
  ```

- **Lock files**: Always commit `poetry.lock` / `uv.lock` and `package-lock.json`. These are the source of truth for reproducible builds.

## Criteria for Adding a New Dependency

Before adding ANY new package, evaluate:

1. **Is it necessary?** Can we achieve this with stdlib or existing deps? (prefer fewer deps)
2. **Is it actively maintained?** Last commit within 6 months, responsive to issues
3. **Is it widely adopted?** Prefer packages with >1000 GitHub stars and active community
4. **Is the license compatible?** Acceptable: MIT, Apache 2.0, BSD. Avoid: GPL, AGPL (copyleft risk for SaaS)
5. **Is it HIPAA-safe?** Does it phone home? Does it collect telemetry? Does it process data externally?
6. **What's the transitive dependency tree?** A small package with 50 transitive deps is risky
7. **Is there a known vulnerability history?** Check CVE databases

## Vulnerability Scanning

- Run `pip audit` (Python) and `npm audit` (JavaScript) on every CI build
- **Critical/High severity**: Blocks merge — must be resolved before code ships
- **Medium severity**: Must be resolved within 7 days
- **Low severity**: Track in backlog, resolve within 30 days
- Weekly automated dependency update PRs (Dependabot/Renovate style)
- Quarterly manual review of full dependency tree

## Approved Core Dependencies

### Backend (Python)
| Package | Purpose | License |
|---------|---------|---------|
| fastapi | Web framework | MIT |
| uvicorn | ASGI server | BSD |
| sqlalchemy | ORM/database | MIT |
| asyncpg | PostgreSQL async driver | Apache 2.0 |
| pydantic | Validation/schemas | MIT |
| pydantic-settings | Config management | MIT |
| celery | Task queue | BSD |
| redis | Redis client | MIT |
| bcrypt | Password hashing | Apache 2.0 |
| python-jose | JWT handling | MIT |
| httpx | HTTP client | BSD |
| hypothesis | Property testing | MPL 2.0 |
| alembic | DB migrations | MIT |
| structlog | Structured logging | MIT |

### Frontend (JavaScript/TypeScript)
| Package | Purpose | License |
|---------|---------|---------|
| react | UI framework | MIT |
| react-dom | DOM rendering | MIT |
| react-router-dom | Routing | MIT |
| axios | HTTP client | MIT |
| zustand | State management | MIT |
| recharts | Charts | MIT |
| vite | Build tool | MIT |
| vitest | Test runner | MIT |
| typescript | Type system | Apache 2.0 |
| @testing-library/react | Component testing | MIT |
| playwright | E2E testing | Apache 2.0 |

### ML Pipeline (Python)
| Package | Purpose | License |
|---------|---------|---------|
| xgboost | Gradient boosting | Apache 2.0 |
| lightgbm | Gradient boosting | MIT |
| scikit-learn | ML utilities | BSD |
| torch | Neural networks | BSD |
| shap | Explainability | MIT |
| prophet | Time series | MIT |
| lifelines | Survival analysis | MIT |
| pycox | Deep survival | BSD |

## Forbidden Patterns

- No `*` or `latest` version specifiers — ever
- No installing packages from git URLs in production (use published releases)
- No private/internal packages without explicit documentation of source
- No packages that require network access at import time
- No packages with telemetry enabled by default (disable or don't use)
