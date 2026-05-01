---
inclusion: always
---

# Git Conventions — PrescpHealth Rebuild

## Branch Naming

Format: `{type}/{short-description}`

Types:
- `feat/` — new feature work (e.g., `feat/auth-module`, `feat/risk-engine-api`)
- `fix/` — bug fixes (e.g., `fix/token-rotation-reuse`)
- `infra/` — infrastructure, CI/CD, Docker (e.g., `infra/docker-compose`)
- `test/` — test additions or fixes (e.g., `test/property-tenant-isolation`)
- `docs/` — documentation only (e.g., `docs/api-openapi-spec`)
- `refactor/` — code restructuring without behavior change (e.g., `refactor/split-risk-service`)

Rules:
- Always branch from `main`
- Use kebab-case for descriptions
- Keep branch names under 50 characters
- Never push directly to `main` — always use PRs

## Commit Message Format

```
<type>(<scope>): <short summary>

<optional body — explain WHY, not WHAT>

<optional footer — references>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `infra`, `chore`

Scopes: `auth`, `patients`, `measurements`, `risk`, `forecast`, `ai-assistant`, `drugs`, `alerts`, `reports`, `population`, `admin`, `portal`, `ml`, `frontend`, `core`, `docker`

Examples:
```
feat(auth): implement JWT refresh token rotation with reuse detection

Invalidates entire token family when reuse is detected to prevent
session hijacking. Uses Redis sorted set for O(1) family lookup.

Refs: REQ-2.3, REQ-2.5
```

```
fix(measurements): reject systolic BP values outside 60-300 range

Previous validation only checked for null, not physiological bounds.
This is a patient safety requirement per clinical guidelines.

Refs: REQ-5.2
```

Rules:
- Subject line: imperative mood, no period, max 70 chars
- Body: wrap at 72 chars, explain motivation
- Reference requirement IDs when applicable
- One logical change per commit — don't bundle unrelated changes
