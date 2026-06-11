# 10 — Settings Screen (future)

**Status:** Future / not yet scheduled.
**Depends on:** [04 Frontend Foundation](./04-frontend-foundation.md) (app shell, ui store,
`Modal`), [02 API](./02-python-api-server.md), [09 Prompts & Permissions](./09-prompts-and-permissions.md).
**Blocks:** nothing (leaf feature; can land anytime after 04).

A single **settings modal**, openable from anywhere in the app, that collects the
configuration surfaces that currently have no UI (most importantly the per-project
**permissions** config, whose backend exists but is only editable by hand-editing
`permissions.json`).

## Why a modal (not a tab/route)
- Settings are cross-cutting, not a "place" in the Design/Plan/Build flow — a modal keeps the
  user in context.
- It must be reachable from every tab, so a global trigger (a gear icon in the app-shell top
  bar) + global open state beats a dedicated route. Deep-linking is a nice-to-have, not a
  requirement.

## Trigger & state
- A **gear button** in the persistent top bar (04), right side.
- Open/close state lives in the ui store (zustand, 04): `settingsOpen` + an optional
  `settingsSection` so other UI can deep-open a section (e.g. "Edit permissions" from a
  Build permission prompt jumps to the Permissions section).
- Built on the shared `Modal` (Radix Dialog, 04). Layout: a left nav list of sections + a
  right content pane (a wide modal, ~`min(48rem, 92vw)`).

```
┌──────────────── Settings ─────────────────────────┐
│ Sections      │  (selected section content)        │
│ • Project     │                                    │
│ • Permissions │                                    │
│ • Models      │                                    │
│ • About       │                                    │
└───────────────┴────────────────────────────────────┘
```

## Sections (v1 scope)
Scoped to the **active project** unless noted.

1. **Project**
   - Show name + root path (read-only for v1).
   - **Remove project** (unregister) → `DELETE /projects/{name}` (02), with a confirm; offer
     to leave files on disk. Switch away to the picker afterward.
   - (Later: rename, change root.)

2. **Permissions** — the headline reason for this screen. Edit the project's
   `permissions.json` (09) via `GET/PUT /permissions` (02):
   - Per profile (**generation**, **execution**): `permissionMode` (select),
     `allow` / `deny` rule lists (add/remove chips), and for execution the `askFallback`
     toggle.
   - `additionalReadDirs`: list of extra directories AI may read (add/remove).
   - Show the canonical defaults and a "reset to defaults" action; link out to the Claude
     permissions docs. Validate lightly (non-empty rule strings); the server is the source of
     truth.

3. **Models** — choose the default Claude model used for generation/chat/execution. Maps to
   the model passed to the CLI (currently `PROMPTLY_MODEL` / `ClaudeService.default_model`,
   03). Decide scope: global vs. per-project (lean per-project, stored alongside
   `permissions.json` or in a small project settings file). Needs a backend setting + a
   `GET/PUT` to persist it (small addition to 02).

4. **About** — app/CLI version (`claude --version`), links, and a pointer to where prompts
   live (`prompts/`, 09) for power users who want to edit them.

## Data & API
- Reuses `GET/PUT /permissions` (02/09) and `DELETE /projects/{name}` (02).
- **New** for the Models section: a tiny per-project settings value (e.g. `model`) with a
  `GET/PUT /settings` endpoint, or fold it into the permissions file's sibling. Define when
  scheduled.
- React Query hooks: `usePermissionsConfig()` (already planned in 04) + a mutation; a
  `useAppSettings()` if/when Models lands.

## Implementation steps
1. `settingsOpen`/`settingsSection` in the ui store + gear button in the app shell (04).
2. `SettingsModal` shell (left nav + content pane) on the shared `Modal`.
3. **Permissions** section wired to `GET/PUT /permissions` (rule chips, mode select,
   read-dirs, reset). — highest value; can ship alone.
4. **Project** section (remove/unregister with confirm).
5. **Models** section (after the backend setting exists).
6. **About** section.

## Open questions
- Model setting scope (global vs. per-project) and where to persist it — resolve when Models
  is scheduled; Permissions/Project sections don't depend on it.
- Should editing `permissions.json` through the UI ever write a real `.claude/settings.json`
  into the repo, or stay Promptly-only (ephemeral `--settings`)? Keep Promptly-only per 09's
  open question unless a user needs the repo-committed form.
- Deep-linking to a section (`?settings=permissions`) — add only if a flow needs it (e.g. the
  Build permission prompt's "edit permissions" shortcut).
