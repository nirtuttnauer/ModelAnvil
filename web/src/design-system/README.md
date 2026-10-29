The React UI implements the native [FigCraft project](../../../design/figcraft/ModelAnvil.figcraft).

## Tokens

`design/figcraft/variables.json` is the source for the 58 design variables. Run `npm run tokens:sync` in `web` after exporting updated variables from FigCraft; `npm run build` checks that `tokens.css` is current, so never edit it by hand. Everything derived from the tokens lives in `semantic.css`: the semantic aliases page CSS uses (`--surface`, `--primary`, `--border`, `--text`, status tones), the system font stacks (a font stack cannot be a FigCraft variable), control height, radii, overlay shadow, chart palette and layout sizes. It is the only hand-written stylesheet allowed to contain a color literal, and every literal has a dark pair.

## Stylesheet layers

`index.css` imports, in order, `tokens.css` → `semantic.css` → `base.css` → `primitives.css`; `src/app.css` holds the shell. `semantic.css` declares the cascade order `@layer tokens, base, primitives, shell, pages;` so a stylesheet's import order can no longer change the result. Page stylesheets wrap their rules in `@layer pages { … }` and contain layout only: grids, sticky regions, page-specific spacing. They never restyle elements, `[data-ui]` primitives or legacy classes, and they contain no `!important` and no color literals.

The end of `primitives.css` is a fenced block of legacy class names (`.panel`, `.notice`, `.state`, `.form-grid`, …) restyled onto the system so unmigrated pages stay coherent. It is deleted once every page uses the primitives.

Type scale: page title `--type-24`, section `--type-20`, subsection `--type-16`, body and controls `--type-14`, labels `--type-13`, captions and badges `--type-12` (the minimum). Weights 400/500/600 only, no letter-spacing, no uppercase. Spacing uses `--space-4/8/12/16/24/32`; controls use `--radius-control` (6 px) and panels `--radius-panel` (8 px); only floating surfaces carry `--shadow-overlay`. A bordered container never holds another bordered box: nested cards, form grids and feedback lose their border inside cards, inspectors, dialogs and card sections.

## Primitives

`components/ui.tsx` re-exports everything in `components/primitives/` plus `RecordTable`, `MetricSummary`, `NavigationItem` and `WorkspaceHeader`. Styling is keyed on `data-ui` / `data-variant` / `data-tone` attributes, never on class names.

| Primitive | Purpose |
| --- | --- |
| `Button`, `LinkButton` | `variant="primary\|secondary\|quiet"`, `size="sm\|lg"`, `icon` for square icon buttons; native `type` default kept |
| `Card` | `tone="surface\|subtle\|accent"`, `padded` |
| `PageHeader` | the one `<h1>` per page, rendered by the shell; `PageActions` portals page buttons into its action slot |
| `Section` | `title`, `description`, `actions`, `level={2\|3}`, `variant="plain\|card"`; groups content with one heading |
| `StatRow` / `Stat` | one row of figures with hairline dividers; `tone` tints the value |
| `StatusBadge` | text plus icon for any lifecycle string, toned by `api/status.ts` (`statusTone`, `statusLabel`); keeps the `state` class |
| `Badge`, `Notice` | tones `neutral\|info\|success\|caution\|error` (`Notice` defaults to neutral) |
| `Field`, `MultilineField`, `TextControl`, `Select`, `Checkbox`, `Radio`, `FileInput` | labelled controls with hint and error slots; `FileInput` keeps the native input focusable |
| `SegmentedControl`, `TabList` + `Tab` | pressed-state group and underline tabs |
| `Disclosure` | real `<details>/<summary>`; `variant="plain\|card\|quiet"` |
| `KeyValueList` | `<dl>` of facts, one or two columns |
| `Toolbar` | filters left, `actions` right |
| `Dialog`, `Menu`, `MenuSection` | native `<dialog>` rendered in place; disclosure-based popover menu |
| `JourneySteps` | numbered steps for the shared fine-tuning journey in `api/journey.ts` |
| `Feedback`, `EmptyState` | loading / empty / error with `layout="inline\|centered"` |

Charts: `ChartPanel` takes `bordered={false}` when it already sits inside a card or section; colors come from `--chart-1..4` and `--chart-neutral`; "View data" is a quiet disclosure and the selected point is announced through a live region instead of a permanent readout bar.

### Technical identifiers

Use `Identifier` from `components/Identifier` beside a readable resource name. It shows a small circle icon, reveals the exact value on hover or keyboard focus, and copies it on activation with announced success or failure; `display="code"` shows the value inline for detail and inspector rows. Tables show the human name only; the copyable identifier belongs in the inspector, never as the only content of a cell and never twice in a row.

New internal UUIDs use `modelanvil.core.ids.uuid7`. Avoid shortened UUID prefixes for display or identity: UUIDv7 prefixes encode time and are shared by nearby records. Prefer names, revisions and per-list ordinals.

## Shell

The rail is a light surface (dark in the dark theme), 240 px, with the Workspace group always visible and the other groups behind "Advanced workspace", which opens for its own pages and closes when the user returns to the workspace group. The header carries four controls: the project scope, "Go to…" page search (⌘K), Active jobs, and a settings menu holding appearance, organization, refresh, connection/sign-out, API status and build identity. Theme and density preferences persist locally; Light is the default and System follows the OS.

Preview every variant in Storybook under **ModelAnvil → Components → FigCraft** (light and dark). Screen and action stories exercise the integrated components with synthetic API data.
