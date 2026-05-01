---
inclusion: always
---

# Code Style — PrescpHealth Rebuild

## Mandatory Rules

1. **Heavy commenting**: Every module, class, and function MUST have a docstring explaining its purpose, parameters, return values, and any side effects. Use inline comments to explain non-obvious logic, business rules, and the "why" behind decisions — not just restating what the code does.

2. **Extreme modularity**: No single file should exceed ~150 lines of code (excluding comments/docstrings). If a file grows beyond this, split it into smaller focused modules. Each file should have a single, clear responsibility.

3. **No behemoth files**: Prefer many small, well-named files over fewer large ones. Use `__init__.py` re-exports to keep imports clean. Group related utilities into their own sub-modules rather than dumping them into a shared utils file.

4. **File naming**: File names should clearly communicate their contents. Prefer descriptive names (`token_rotation.py`, `risk_stratification.py`) over generic ones (`helpers.py`, `utils.py`).

5. **Function size**: Individual functions should do one thing. If a function has more than ~30 lines of logic, consider extracting helper functions with descriptive names.

## Comment Style Examples

```python
# Good — explains WHY
# Lock account after 5 failed attempts within a 10-minute sliding window
# to mitigate brute-force credential stuffing attacks (OWASP recommendation)
if failed_attempts >= MAX_ATTEMPTS and within_window:
    await self._lock_account(user_id)

# Bad — restates WHAT
# Check if failed attempts is greater than max
if failed_attempts >= MAX_ATTEMPTS:
    ...
```

```typescript
// Good — explains business context
// Patient_User role gets 100 req/min (lower than clinicians at 1000 req/min)
// because patient portal has simpler access patterns and we want to
// reserve capacity for clinical workflows
const rateLimit = role === 'Patient_User' ? 100 : 1000;
```
