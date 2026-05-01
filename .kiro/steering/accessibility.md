---
inclusion: always
---

# Accessibility Standards — PrescpHealth Rebuild

## Core Principle

Clinical software must be usable by ALL clinicians and patients, including those with visual, motor, cognitive, or situational disabilities. Accessibility is not optional — it's a requirement for healthcare software serving diverse communities.

## Compliance Target

- **WCAG 2.1 Level AA** — minimum standard for all UI components
- Full validation requires manual testing with assistive technologies and expert accessibility review

## Keyboard Navigation

- Every interactive element must be reachable via keyboard (Tab/Shift+Tab)
- Logical tab order following visual layout (top-to-bottom, left-to-right for LTR)
- Focus indicators must be clearly visible (minimum 2px outline, high contrast)
- No keyboard traps — user can always Tab away from any component
- Escape key closes modals, dropdowns, and overlays
- Enter/Space activates buttons and links
- Arrow keys navigate within composite widgets (tabs, menus, grids)

## Screen Reader Support

- All images have meaningful `alt` text (or `alt=""` for decorative images)
- All form inputs have associated `<label>` elements (not just placeholder text)
- Dynamic content updates announced via `aria-live` regions
- Risk gauges and charts have text alternatives describing the data
- Modal dialogs use `role="dialog"` with `aria-labelledby` and `aria-describedby`
- Loading states announced: `aria-busy="true"` on containers being updated
- Error messages linked to inputs via `aria-describedby`

## Charts and Data Visualization

Risk dashboards and charts are core to PrescpHealth. They MUST be accessible:

- Every chart has a text summary describing the key insight (e.g., "Stroke risk: 72/100, Critical stratum. Top factors: systolic BP, smoking history, age.")
- Data tables available as alternative to visual charts (toggle between chart/table view)
- Chart colors are NOT the only way to convey information — use patterns, labels, or icons alongside color
- Interactive chart elements (tooltips, drill-downs) accessible via keyboard

## Color and Contrast

- Text contrast ratio: minimum 4.5:1 against background (AA standard)
- Large text (18px+ or 14px+ bold): minimum 3:1
- UI component boundaries: minimum 3:1 against adjacent colors
- Risk strata colors must be distinguishable by colorblind users:
  - Low: Green (#2E7D32) + "Low" text label + checkmark icon
  - Moderate: Amber (#F57C00) + "Moderate" text label + warning icon
  - High: Orange-Red (#D84315) + "High" text label + alert icon
  - Critical: Red (#B71C1C) + "Critical" text label + danger icon
- Never use color alone to convey meaning — always pair with text, icon, or pattern

## Component-Level Requirements

### Forms (measurement entry, patient creation, login)
- Clear labels above or beside inputs (not inside as placeholder-only)
- Required fields marked with both `*` and `aria-required="true"`
- Inline validation errors appear immediately and are announced to screen readers
- Error summary at top of form listing all issues with links to each field
- Autocomplete attributes on appropriate fields (`autocomplete="email"`, etc.)

### Tables (patient list, alert history, watchlist)
- Proper `<table>`, `<thead>`, `<tbody>`, `<th>` semantic markup
- Column headers use `scope="col"`, row headers use `scope="row"`
- Sortable columns indicate current sort direction via `aria-sort`
- Pagination controls are keyboard accessible with clear labels

### Modals and Dialogs (drug interaction alerts, confirmations)
- Focus trapped inside modal while open
- Focus moves to modal on open, returns to trigger on close
- Background content marked `aria-hidden="true"` while modal is open
- Close button clearly labeled and keyboard accessible

### Alerts and Notifications
- Critical alerts use `role="alert"` for immediate screen reader announcement
- Non-critical notifications use `role="status"` (polite announcement)
- Toast notifications persist long enough to be read (minimum 5 seconds, or until dismissed)
- Notification history accessible for users who missed transient alerts

## Mobile and Touch (Patient Portal)

- Touch targets minimum 44x44px (WCAG 2.5.5)
- Pinch-to-zoom not disabled (users may need to enlarge content)
- Content readable without horizontal scrolling at 320px viewport width
- Orientation not locked — support both portrait and landscape

## Testing Requirements

- Automated: axe-core or similar tool integrated into CI (catches ~30-40% of issues)
- Manual: keyboard-only navigation test for every new page/component
- Screen reader: test with NVDA (Windows) or VoiceOver (Mac) for critical flows
- Color contrast: automated checker in CI for all color combinations
- Note: Full WCAG compliance requires expert manual review beyond automated tools
