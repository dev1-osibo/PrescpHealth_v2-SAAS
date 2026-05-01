---
inclusion: always
---

# Database & Migration Discipline — PrescpHealth Rebuild

## Core Principle

Patient data is sacred. Every database operation must be designed to NEVER lose, corrupt, or silently overwrite existing data. Migrations must be reversible, additive, and safe to run against production with live traffic.

## Data Ingestion Pipeline

All data entering the system follows this pipeline — no exceptions:

```
Raw Input → Validation → Cleaning → Normalization → Deduplication → Storage
```

### Stage 1: Validation (reject garbage at the gate)
- Pydantic schema validation at API boundary (type, format, required fields)
- Physiological range checks for measurements (systolic_bp: 60–300, etc.)
- Referential integrity checks (patient_id exists, tenant_id matches)
- Reject invalid data with descriptive errors — never silently fix it

### Stage 2: Cleaning (standardize what passes validation)
- Trim whitespace from string fields
- Normalize date formats to UTC ISO-8601
- Normalize measurement units to standard (always store in SI units internally)
- Strip control characters from text fields
- Normalize drug names to canonical form (uppercase, no trailing spaces)

### Stage 3: Normalization
- Convert local timestamps to UTC for storage (preserve original timezone in metadata)
- Standardize enum values to defined set
- Round measurement values to clinically meaningful precision (e.g., BP to integers, BMI to 1 decimal)

### Stage 4: Deduplication (idempotency)
- Check idempotency key: `(patient_id, measurement_type, recorded_at, value)`
- If duplicate detected: return existing record, do NOT create a new one
- Log duplicate attempt for monitoring (may indicate integration issues)

### Stage 5: Storage
- Insert validated, cleaned, normalized, deduplicated record
- Publish domain event (e.g., `MeasurementSaved`)
- Return created record with assigned ID

## Data Integrity Protection Rules

### Append-Only for Clinical Data
- New measurements APPEND to patient history — never overwrite previous entries
- Profile updates create VERSION HISTORY — old values preserved in `patient_versions` table
- Risk scores accumulate over time — historical scores are immutable once computed

### Bulk Import Safety
- Bulk imports are ADDITIVE — they add new records, never delete existing ones
- Each row validated independently — valid rows succeed, invalid rows reported as errors
- Transaction boundary: commit valid rows, report invalid rows with line numbers and reasons
- Never use `DELETE + re-INSERT` pattern — always upsert or append
- Pre-import summary shown to user: "X new records will be added, Y duplicates skipped, Z invalid rows rejected"

### Upsert Rules
- `ON CONFLICT DO NOTHING` — for idempotent measurement inserts
- `ON CONFLICT DO UPDATE` — ONLY for non-PHI metadata fields (e.g., `updated_at`, `sync_status`)
- NEVER use `ON CONFLICT REPLACE` for patient data
- NEVER overwrite clinical values without creating a version record

### Join/Merge Protections
- All queries combining datasets use EXPLICIT join types (never implicit cross joins)
- LEFT JOINs must handle NULL gracefully — never assume joined data exists
- Aggregation queries must use COALESCE for nullable fields
- Population analytics queries operate on READ-ONLY views — never modify source tables
- Any query that could theoretically modify data during a join is FORBIDDEN

## Migration Discipline

### Naming Convention
```
{YYYYMMDD}_{HHMMSS}_{description_in_snake_case}.py

Examples:
20250115_143000_create_patients_table.py
20250116_090000_add_risk_scores_index.py
20250120_110000_add_measurement_deviation_flag_column.py
```

### Safety Rules

1. **Never DROP COLUMN in the same release that removes code using it**
   - Release 1: Deploy code that no longer reads the column
   - Release 2: Drop the column in a migration (after confirming no queries reference it)

2. **Never TRUNCATE or DELETE FROM in a migration**
   - If data must be removed: soft-delete with audit trail
   - If table must be rebuilt: create new table, migrate data, swap names, keep old as backup

3. **Every migration must be reversible**
   - Define both `upgrade()` and `downgrade()` in every Alembic migration
   - Test downgrade path before deploying upgrade

4. **Data transformation migrations must be tested**
   - Test against production-sized dataset copy
   - Measure execution time — long-running migrations need batching
   - Never transform data in a migration that also changes schema (separate migrations)

5. **Additive-first approach**
   - Add new columns as NULLABLE first
   - Backfill data in a separate migration
   - Add NOT NULL constraint in a third migration (after confirming all rows populated)

### Index Management

- Every foreign key MUST have an index
- Every column used in WHERE clauses frequently MUST have an index
- Composite indexes: put high-cardinality columns first
- Review query plans before adding indexes (don't add blindly)
- Document WHY each index exists in a comment in the migration
- Monitor index usage — drop unused indexes quarterly

## Data Seeding Strategy

| Environment | Strategy |
|-------------|----------|
| Development | Synthetic seed data (50 patients, realistic measurements, pre-computed risk scores) |
| Staging | Anonymized subset of production-like data (if available) or larger synthetic set (500 patients) |
| Production | No seed data — starts empty, populated by real usage |
| Testing | Factory-generated per test (isolated, deterministic, synthetic) |

### Seed Data Rules
- All seed data MUST be clearly synthetic (names like "Demo Patient Alpha")
- Seed data must cover edge cases: patients with sparse data, patients with full history, patients at each risk stratum
- Seed data must be idempotent — running seed script twice produces same result (no duplicates)
- Never use real patient data in any non-production environment

## Backup & Recovery

- Point-in-time recovery enabled (WAL archiving)
- Daily full backups, hourly incremental
- Backup encryption at rest (AES-256)
- Monthly backup restoration test (verify backups actually work)
- RTO target: 1 hour, RPO target: 1 hour
