---
inclusion: always
---

# Testing Conventions — PrescpHealth Rebuild

## Test Structure

```
backend/tests/
├── unit/              # Fast, isolated, no DB/Redis
│   ├── auth/
│   ├── patients/
│   ├── measurements/
│   └── ...
├── property/          # Hypothesis-based property tests
│   ├── test_tenant_isolation.py
│   ├── test_risk_score_range.py
│   └── ...
├── integration/       # Real DB (testcontainers), real Redis
│   ├── test_auth_flow.py
│   ├── test_measurement_to_risk.py
│   └── ...
└── conftest.py        # Shared fixtures
```

## Naming Conventions

- Test files: `test_{module}_{aspect}.py` (e.g., `test_auth_token_rotation.py`)
- Test functions: `test_{action}_{condition}_{expected_result}` (e.g., `test_login_with_locked_account_returns_403`)
- Property tests: `test_property_{property_name}` (e.g., `test_property_risk_score_always_in_range`)
- Fixtures: descriptive names matching what they provide (e.g., `authenticated_doctor`, `patient_with_measurements`)

## What to Test

### Unit Tests (every module MUST have these)
- Happy path for each public function
- Edge cases (empty inputs, boundary values, None handling)
- Error conditions (invalid input, missing data, permission denied)
- Business rule enforcement (HIPAA rules, clinical validation ranges)

### Property Tests (for correctness properties in the spec)
- Use Hypothesis library for Python
- Define clear invariants that must ALWAYS hold
- Use strategies that generate realistic clinical data
- Target the 14 correctness properties defined in requirements.md

### Integration Tests (for cross-module flows)
- End-to-end API flows (login → action → verify state)
- Event-driven flows (measurement saved → risk computed → alert generated)
- External service failover (GPT-4o timeout → Claude fallback)

## Test Quality Rules

1. **No test should depend on another test's state** — each test is fully isolated
2. **No sleeping in tests** — use async awaits, polling, or mocked time
3. **No hardcoded secrets in tests** — use fixtures that generate test credentials
4. **PHI in test data must be synthetic** — never use real patient data, even in tests
5. **Every test must have a docstring** explaining what it validates and why
6. **Property tests must document the invariant** being checked

## Coverage Expectations

- Unit test coverage target: 80%+ on business logic modules
- Property tests: one per correctness property (14 total minimum)
- Integration tests: cover every critical user flow
- No coverage gaming — don't test trivial getters/setters just for numbers

## Test Data

- Use factory functions for test data (not raw dicts)
- All patient data in tests MUST be clearly synthetic (use names like "Test Patient Alpha")
- Generate realistic but fake clinical measurements within valid ranges
- Use Hypothesis strategies for property tests to explore edge cases automatically

## Running Tests

```bash
# Unit tests only (fast, no external deps)
pytest backend/tests/unit/ -v

# Property tests (may take longer due to shrinking)
pytest backend/tests/property/ -v --hypothesis-show-statistics

# Integration tests (requires testcontainers)
pytest backend/tests/integration/ -v

# All tests
pytest backend/tests/ -v
```
