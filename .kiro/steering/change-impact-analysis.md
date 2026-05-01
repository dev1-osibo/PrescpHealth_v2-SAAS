---
inclusion: always
---

# Change Impact Analysis — PrescpHealth Rebuild

## Core Principle

Before making ANY code change, evaluate its impact on the entire existing pipeline. Never blindly modify a file without understanding what depends on it and what it depends on. As the codebase grows, this becomes increasingly critical.

## Mandatory Pre-Change Checklist

Before writing or modifying any code file, the following MUST be evaluated:

### 1. Dependency Analysis
- What modules import from the file being changed?
- What does this file import from other modules?
- Are there shared interfaces (schemas, base classes, protocols) that would break?

### 2. Contract Verification
- Does this change alter any function signatures (parameters, return types)?
- Does this change modify any Pydantic schema (request/response models)?
- Does this change affect database models (columns, relationships, constraints)?
- Does this change modify API endpoint behavior (status codes, response shape)?

### 3. Downstream Impact
- Which Celery tasks depend on the changed code?
- Which domain event handlers would be affected?
- Which frontend API calls depend on the changed endpoint?
- Which tests reference the changed function/class/module?

### 4. Cross-Module Effects
- If changing a shared utility (core/), which modules use it?
- If changing a model, which services query or write to that table?
- If changing an event, which subscribers react to it?
- If changing auth/RBAC, which endpoints are affected?

## Action Protocol

1. **Identify all affected files** before making the change
2. **Read the affected files** to understand current contracts
3. **Plan the change** including all necessary updates to dependents
4. **Make the change atomically** — update the source AND all dependents in the same pass
5. **Run existing tests** after the change to verify nothing broke
6. **If tests fail** — fix the regression before moving on, never leave broken tests behind

## Red Flags (Stop and Reassess)

- Changing a function signature that's used in 5+ places → consider backward-compatible approach
- Modifying a database column type → requires migration AND data transformation plan
- Altering an API response shape → frontend will break, coordinate both sides
- Changing domain event payloads → all subscribers must be updated simultaneously

## Never Do This

- Change a shared interface without updating all consumers
- Modify a model without generating a migration
- Alter an API contract without updating TypeScript types on frontend
- Skip running tests after a change "because it's small"
- Assume a change is isolated without checking imports/dependents

## Test-As-Verification

After EVERY change:
- Run unit tests for the modified module
- Run unit tests for all modules that depend on the modified code
- Run property tests if the change touches a correctness-critical path
- Run integration tests if the change crosses module boundaries
