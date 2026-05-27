---
inclusion: manual
---

# Checkpoint Verification Protocol — PrescpHealth Rebuild

## When to Use

This protocol is triggered at every checkpoint task in the spec (Tasks 6, 8, 13, 19, 22, 24, 32, 35). It must be completed BEFORE marking the checkpoint as done and BEFORE proceeding to the next task group.

## Verification Steps (All Mandatory)

### 1. Full Test Suite
Run ALL tests and confirm zero failures:
```bash
python -m pytest backend/tests/ -v --tb=short
```
- All unit tests pass
- All property tests pass
- No flaky tests (run twice if any fail)
- Test count matches expectations (should only increase, never decrease)

### 2. Import Verification
Verify all modules in the completed task group import cleanly:
```python
# Run a single Python command that imports every public module
# from the completed task group + all prior modules
```
- No circular imports
- No missing dependencies
- Cross-module imports resolve correctly

### 3. Deep Code Review (Delegate to context-gatherer agent)
For EVERY file created or modified in the completed task group:
- **Logic correctness**: Any bugs, missing error handling, unreachable code, race conditions
- **Missing try/except**: Any code path that could crash a clinical workflow
- **SQL injection risk**: Any raw string interpolation in queries
- **Dead code**: Any unreachable branches or unused imports

### 4. HIPAA Compliance Audit
For EVERY file in the completed task group:
- **Log statements**: No patient names, measurement values, diagnoses, or PHI in any log call
- **Error messages**: No PHI in exception messages or API error responses
- **Cache headers**: All PHI-containing responses include `Cache-Control: no-store`
- **Audit trail**: Every CUD operation on patient data creates an audit log entry
- **SQL echo**: Confirm `echo=True` is NEVER enabled in production config

### 5. Commenting Standards Check
For EVERY file in the completed task group:
- **Module docstring**: Present, explains purpose in 1-3 sentences
- **Class docstrings**: Present on every class, explains responsibility
- **Function docstrings**: Present on every public function with Args, Returns, Raises
- **Inline comments**: Explain "why" (business rules, HIPAA requirements), not "what"
- **PHI field markers**: All PHI columns have `comment="PHI: ..."` in model definitions

### 6. File Size Compliance
For EVERY file in the completed task group:
- Count lines of logic (excluding comments, docstrings, blank lines)
- Flag any file exceeding ~150 lines of logic
- Exceptions allowed: data registries (validators.py), migrations (self-contained by convention)
- Split oversized files into focused sub-modules with re-export hubs

### 7. Forward Compatibility Analysis
Review the NEXT task group (the tasks that come after this checkpoint) and ask:
- **Do the current modules provide the interfaces the next tasks need?**
  - Check domain events: do they carry enough data for downstream subscribers?
  - Check service methods: are there missing aggregation/extraction methods the next module will need?
  - Check data models: are there missing fields or relationships the next module expects?
- **Are there gaps that would force retrofitting later?**
  - If the next task group needs a "feature vector" from measurements, does that method exist?
  - If the next task group subscribes to events, do those events carry sufficient context?
  - If the next task group needs cross-module data, is there an aggregation service?
- **Create preparatory work items for any gaps found:**
  - Small additions (new method, extra event field): implement NOW before proceeding
  - Larger additions (new service, new module): document as a work item with "implement before Task X"
- **Verify existing contracts won't break:**
  - Will the next task group need to modify any existing function signatures?
  - Will it need new columns on existing tables (requiring migrations)?
  - Will it need new domain events or modifications to existing ones?

Report gaps in this format:
```
FORWARD COMPATIBILITY:
- Gap: [description]
  Needed by: Task [N]
  Fix: [what to add/change]
  When: [NOW / Before Task X]
```

**Document all findings** in `.kiro/specs/prescphealth-saas-rebuild/forward-compatibility.md` — this is the living backlog of forward compatibility items. Update it at every checkpoint with new findings and mark completed items as ✅ DONE.

### 8. Fix All Issues
- Fix ALL critical and high severity issues before proceeding
- Fix medium severity issues if time permits
- Implement all "NOW" forward compatibility items before proceeding
- Document any accepted low-severity items with justification
- Re-run test suite after fixes to confirm no regressions

### 9. Git Commit and Push
- Stage all changes from the checkpoint verification
- Commit with message: `chore(core): checkpoint N verification — [summary of fixes]`
- Push to current branch

## Failure Criteria (Block Proceeding)

Do NOT proceed past a checkpoint if ANY of these are true:
- Any test fails
- Any module fails to import
- Any critical/high logic bug exists
- Any HIPAA violation exists (PHI in logs or errors)
- Any public function/class lacks a docstring
- Any forward compatibility gap marked "NOW" is unresolved

## Accuracy Standard

This project requires **100% accuracy**. No shortcuts, no "good enough", no "we'll fix it later":
- Every test must pass (0 failures, 0 flaky tests)
- Every optional test task must be completed (never skipped)
- Every file must be reviewed for correctness before moving on
- Every bug found must be fixed immediately (not deferred)
- Every forward compatibility gap must be addressed at the right time
- Code quality is non-negotiable — this is a solo project where technical debt compounds fast

## Subagent Task Size Limit

To prevent hung/dead subagents that waste time:
- **Maximum 3 tasks per subagent call** — never batch more than 3 tasks into a single invoke_sub_agent
- **Maximum scope per task**: one module's model+migration, OR one module's service, OR one module's schemas+router, OR up to 3 test files
- **If a subagent hasn't returned in 5 minutes**: assume it's dead, report to user, retry with smaller scope
- **Never dispatch a single subagent call that would take >5 minutes** — split into smaller chunks
- **After each subagent returns**: immediately report the result to the user before dispatching the next one

## Integration Testing at Every Checkpoint

Every checkpoint MUST include real-database integration tests (requires Docker):
- Spin up PostgreSQL via testcontainers
- Run ALL Alembic migrations against the real DB (from 0001 to latest)
- **Run ALL tests from ALL modules** (not just the new module) — this catches regressions and cross-module breakage
- **Test cross-module integration flows from scratch:**
  - Auth → Patient → Measurement → Risk pipeline (end-to-end data flow)
  - Encounter → Diagnosis → Patient chronic_conditions sync
  - Lab Order → Result → Measurement creation → MeasurementSaved event
  - Prescription → DDI check → Refill → Dispensing
  - Every new module must be tested in combination with ALL prior modules
- Verify RLS actually blocks cross-tenant access (query as tenant A, verify tenant B data invisible)
- Verify unique constraints reject duplicates at the DB level
- Verify foreign keys enforce referential integrity (delete parent, verify child behavior)
- Test concurrent access patterns where relevant (idempotency, race conditions)
- **The test count must ONLY increase** — if it decreases, something was deleted or broken
- If Docker is not available, BLOCK the checkpoint and inform the user

## Output Format

After completing all steps, report:
```
CHECKPOINT [N] — [PASS/FAIL]
- Tests: [count] passed, [count] failed
- Imports: [CLEAN/ISSUES]
- Logic bugs found: [count] (fixed: [count])
- HIPAA violations: [count] (fixed: [count])
- Missing comments: [count] (fixed: [count])
- Files over limit: [count] (split: [count], accepted: [count])
- Forward compatibility gaps: [count] (fixed now: [count], deferred: [count])
```
