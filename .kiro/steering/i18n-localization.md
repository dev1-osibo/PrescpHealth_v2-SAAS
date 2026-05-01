---
inclusion: always
---

# Internationalization & Localization — PrescpHealth Rebuild

## Core Principle

PrescpHealth serves clinicians across Africa and underserved communities. The platform must support multiple languages, date/number formats, and clinical terminology from day one — not bolted on later.

## Supported Languages (Launch)

| Language | Code | Region | Priority |
|----------|------|--------|----------|
| English | en | Pan-African, global | Primary |
| French | fr | West/Central Africa (Senegal, DRC, Cameroon, etc.) | Day 1 |
| Portuguese | pt | Lusophone Africa (Mozambique, Angola, Guinea-Bissau) | Day 1 |
| Swahili | sw | East Africa (Kenya, Tanzania, Uganda) | Phase 2 |
| Arabic | ar | North Africa (Egypt, Sudan, Morocco) | Phase 2 |

## Architecture Rules

### Backend
- All user-facing strings (error messages, notification content, report labels) must use translation keys — never hardcoded English
- Store translations in structured JSON files: `backend/app/i18n/{locale}.json`
- API responses include translated content based on `Accept-Language` header or user preference
- Clinical terminology uses standardized medical coding (ICD-10, ATC for drugs) with locale-specific display names
- Audit logs and internal system logs remain in English (operational language)

### Frontend
- Use a translation library (react-i18next or similar lightweight solution)
- All UI text uses translation keys: `t('patient.risk_score_label')` — never inline strings
- Store translations in `frontend/src/i18n/{locale}/` directory structure
- Support RTL layout for Arabic (Phase 2) — design components to be RTL-aware from the start
- Language selector accessible from every page (header/settings)

### Database
- User language preference stored in user profile
- Tenant default language configurable by Clinic_Admin
- Drug names stored with canonical English name + locale-specific display names in JSONB
- Condition/diagnosis names reference ICD-10 codes with locale display mapping

## Date, Time, and Number Formatting

| Element | Rule |
|---------|------|
| Dates (storage) | Always UTC ISO-8601: `2025-01-15T10:30:00Z` |
| Dates (display) | Locale-appropriate: `15/01/2025` (fr), `01/15/2025` (en-US), `15 Jan 2025` (en-GB) |
| Times (display) | 24-hour format for clinical context (reduces AM/PM ambiguity) |
| Numbers | Locale decimal separator: `3.14` (en), `3,14` (fr/pt) |
| Currency | Not applicable (no billing in MVP) |
| Measurement units | SI units internally, display in locale preference (kg vs lbs — but clinical standard is metric) |

## Clinical Terminology Localization

- Drug names: Store ATC code + English generic name. Display locale-specific name where available.
- Condition names: Store ICD-10 code. Display locale-specific description.
- Measurement types: Translate labels (e.g., "Blood Pressure" → "Tension artérielle" → "Pressão arterial")
- Risk strata: Translate labels (Low/Moderate/High/Critical → Faible/Modéré/Élevé/Critique)
- Alert messages: Fully translated per user's language preference

## Translation Workflow

1. Developer adds new UI text using translation key with English default
2. English translation file updated as source of truth
3. Other locale files flagged as needing translation (missing key = fallback to English)
4. Never show raw translation keys to users — always fall back to English if translation missing

## Notification Localization

- Email/SMS/WhatsApp notifications sent in recipient's preferred language
- Notification templates stored per locale
- Minimal PHI in notifications regardless of language (HIPAA rule takes precedence)
- Example: "You have a new clinical alert" (not "Your stroke risk is critical")

## Implementation Notes

- i18n infrastructure set up in Phase 1 (scaffolding) so all subsequent code uses it from the start
- Do NOT write English strings inline and "plan to translate later" — use keys from day one
- Keep translation files organized by module: `common`, `auth`, `patients`, `measurements`, `risk`, `alerts`, etc.
