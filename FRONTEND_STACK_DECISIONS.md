# Frontend Stack Decisions — Locked In

**Date:** June 21, 2026
**Status:** APPROVED — ready for builder brief

---

## Core Stack

| Layer | Choice | Version |
|-------|--------|---------|
| Framework | React + TypeScript | 18.x |
| Build | Vite | Latest |
| Styling | Tailwind CSS | 3.x |
| Components | shadcn/ui + Radix Primitives | Latest |
| Animations | Framer Motion | Latest |
| Charts | Recharts + Custom SVG Gauge | Latest |
| State (server) | TanStack Query (React Query) | v5 |
| State (UI) | Zustand | Latest |
| Search | cmdk (Command Palette) | Latest |
| Tables | TanStack Table | v8 |
| Toasts | Sonner | Latest |
| Loading | Skeleton (shadcn) + NProgress | — |
| Routing | React Router v6 | 6.x |
| Forms | React Hook Form + Zod | Latest |
| i18n | react-i18next | Latest |
| Testing | Vitest + Testing Library + Playwright | Latest |

---

## Bundle Budget

| Component | Gzipped Size |
|-----------|-------------|
| React + ReactDOM | ~40KB |
| Tailwind (purged) | ~10KB |
| shadcn/ui (tree-shaken) | ~15KB |
| Framer Motion | ~15KB |
| TanStack Query | ~12KB |
| Recharts | ~15KB |
| cmdk | ~3KB |
| Sonner | ~4KB |
| TanStack Table | ~10KB |
| Zustand | ~1KB |
| React Router | ~10KB |
| React Hook Form + Zod | ~10KB |
| **Total** | **~145KB** |

Target: Under 150KB initial bundle (gzipped). Passes 3G performance budget.

---

## Premium UX Patterns (MUST implement)

1. Every icon/label has a tooltip — hover anything to learn what it does
2. Hover cards on patient names — see summary without clicking
3. Command palette (Cmd+K) — find any patient, action, or page instantly
4. Animated page transitions — pages slide/fade, no hard cuts
5. Skeleton screens — content shape immediately, fill on data load
6. Toast notifications — non-blocking success/error feedback
7. Animated risk gauge — needle sweeps to new score on update
8. Breadcrumbs + back navigation — always know where you are
9. Keyboard shortcuts — Escape closes, Enter submits, Tab navigates
10. Contextual actions — right-click or "..." menu on every row/card

---

## Screens (27 total across 4 roles)

### Doctor (9)
1. Dashboard (morning overview)
2. Inpatient List (ward round mode)
3. Appointment Schedule
4. Patient Chart (risk gauges, measurements, meds, AI, encounters, labs, alerts)
5. SOAP Note Editor
6. Prescription Writer (live DDI check)
7. Lab Order Form
8. Population Watchlist
9. Reports (generate/download)

### Nurse (6)
1. Task Queue
2. Vitals Entry (speed-optimized)
3. Patient Quick View
4. Alert Management
5. Medication Administration
6. Triage View

### Lab Tech (5)
1. Lab Queue
2. Result Entry
3. Batch Result Entry
4. Critical Value Protocol
5. Order History

### Patient Portal (7)
1. Home (health status traffic light)
2. Log Vitals
3. My Numbers (trends)
4. My Medications
5. Messages
6. Appointments
7. Settings

---

## Design Principles

- Role-appropriate complexity (Doctor=depth, Nurse=speed, Patient=simplicity)
- Mobile-first for Nurses (one-hand operation)
- Desktop-first for Doctors (screen real estate for chart review)
- 3G baseline (all screens load and function on slow connections)
- WCAG 2.1 AA accessibility minimum
- Dark/light theme toggle
- Never show raw risk scores to patients (plain language only)

---

## Color Palette (Clinical)

- Risk Low: Green (#2E7D32)
- Risk Moderate: Amber (#F57C00)
- Risk High: Orange-Red (#D84315)
- Risk Critical: Red (#B71C1C)
- Primary: Deep Blue (#1565C0) — trust, clinical, professional
- Background: White (#FFFFFF) / Dark (#0F172A)
- Text: Slate (#1E293B) / Dark mode (#F8FAFC)

---

## API Connection

- Base URL: /api/v1/
- Auth: JWT in Authorization header (auto-refresh on 401)
- WebSocket: Future (for real-time alerts) — not in MVP
- Response format: {success, data, meta} envelope

---

## Build Phases (for builder brief)

Phase 1: Project setup + auth + routing + layout shell + common components
Phase 2: Patient management (list, search, chart, timeline)
Phase 3: Clinical workflows (vitals, SOAP, prescriptions, labs, encounters)
Phase 4: AI + Risk + Forecast (gauges, SHAP, counterfactual, alerts)
Phase 5: Admin + Population + Reports + Patient Portal
