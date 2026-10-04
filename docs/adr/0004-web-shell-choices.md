# ADR 0004: Web shell choices

Status: accepted (2026-10-04)

## Context
The spec names Tailwind and shadcn/ui, TanStack Query, React Router, react-hook-form with zod, i18n and a generated OpenAPI client. A few details needed deciding while building the Phase 0 shell.

## Decisions
- **shadcn-style components are written by hand** in `web/src/components/ui.tsx` (Button, Input, Select, Field, Card, Alert, Checkbox). shadcn/ui is copy-in code anyway; a handful of primitives did not justify its CLI or Radix yet. Radix primitives come in when dialogs, menus or drag-and-drop need them (Phase 2).
- **Tailwind CSS 4** with design tokens as CSS variables. Light and dark themes follow the system by default and can be forced in Settings > Appearance; text colours were chosen for WCAG AA contrast.
- **TypeScript is pinned to 5.9**: `openapi-typescript` 7 declares a peer range of `^5`.
- **API client**: `openapi-fetch` over types generated from the FastAPI spec (`npm run gen:api`). The generated `src/api/schema.d.ts` is committed so the web CI job needs no Python. `fetch` is resolved per call so tests can stub it.
- **Settings forms are generic**: one `SectionForm` renders any settings section from the API response, so new settings need no new UI code. Secret fields are write-only and shown masked.
- **Wizard steps reuse the settings API** (`PUT /settings/general`, `/providers`, `/notifications`) instead of dedicated endpoints.
- **End-to-end tests** use Playwright against the real server (built UI, fresh SQLite file under `e2e-data/`): `npm run e2e`.

## Consequences
Later phases add Radix primitives and widgets alongside these components. Changing the API requires re-running `npm run gen:api` and committing the schema.
