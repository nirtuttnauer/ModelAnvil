The React UI implements the native [FigCraft project](../../../design/figcraft/ModelAnvil.figcraft).

`design/figcraft/variables.json` is the source for all 58 design variables. Run `npm run tokens:sync` in `web` after exporting updated variables from FigCraft. The generator converts numeric values to CSS lengths and maps FigCraft mode names to the app's lowercase attributes. `npm run build` checks that generated tokens are current.

`tokens.css` defines light/dark colors and compact/comfortable spacing, typography, and radii. Existing semantic names such as `--surface`, `--primary`, and `--text` in `style.css` reference these exported tokens. Feature styles use the same spacing and type scale. Theme and density preferences persist locally; System follows the OS color theme. Workspace strings from the design remain reference values; live organization and project names come from the API.

The shared components in `components/ui.tsx` and `components/Feedback.tsx` map the design families to React:

| FigCraft family | React | Editable properties |
| --- | --- | --- |
| Button | `Button` | `variant="primary\|secondary\|quiet"`, native `disabled`, children/icon |
| Tab | `Tab` | `aria-selected`, label, native keyboard handlers |
| Badge | `Badge` | `tone="neutral\|success\|caution\|error"`, children |
| Card | `Card` | `tone="surface\|subtle\|accent"`, semantic `as`, children |
| Notice | `Notice` | tone, semantic `as`, children, native live-region role |
| Field | `Field`, `MultilineField` | native input/textarea value, validation, labels and refs |
| Header | `WorkspaceHeader` | desktop and compact layouts through CSS |
| Navigation item | `NavigationItem` | selected, label, icon, action |
| Record row | `RecordTable` | column headers, records and existing controls |
| Feedback | `Feedback` | `state="loading\|empty\|error"`, title, description, optional action slot |
| Metric summary | `MetricSummary` | `as="button\|article"`, label, value, optional detail/icon, native actions |

Components forward native attributes, events and refs. Buttons retain native form submission defaults. Feature components continue to own their data and interactions.

Button hover and pressed colors come from FigCraft's `Color/Action hover` and `Color/Action pressed` tokens. Keyboard focus uses `:focus-visible`; field error styles use `aria-invalid="true"` and keep the caller's associated error message. Disabled fields retain native disabled behavior. Storybook's **Interaction states** example exercises validation and keyboard focus without adding artificial state props to the runtime components.

`Feedback` shares loading, empty and error layouts across resource requests, screen boundaries, workflows, evaluations and the source catalog. Loading uses a status region; errors use an alert; empty content stays passive. Callers provide the optional recovery action. Retry and reload buttons explicitly use `type="button"`, and the loading animation stops for reduced-motion preferences. Storybook’s **Feedback states** shows the variants; **Loading and recovery** verifies retry without form submission.

`MetricSummary` serves Overview actions and Budget read-only articles. Action tiles default to `type="button"`; callers can explicitly request submission. Both forms retain zero values, wrap long content, use tabular numerals and align content at the top. Metric grids use a 200px preferred minimum and collapse to one column on phones. The **Resource summaries** story checks keyboard activation, passive articles, disabled actions and form isolation.

At 1024px and below, the full-label menu replaces the rail. Workspace options reveal organization/project selectors and appearance controls. At 600px and below, simple record tables reflow into labeled cards while retaining table semantics and the same controls. Multi-level or spanning tables retain local scrolling. Metrics and panels wrap with available space. Interactive charts retain their recorded series, tooltips, legends and data views.

Preview every variant and exercise native form submission in Storybook under **ModelAnvil → Components → FigCraft**. Existing screen and action stories exercise the integrated components with synthetic API data.

### Technical identifiers

Use `Identifier` from `components/Identifier` beside a readable resource name. It displays a circle icon, reveals the exact value on hover or keyboard focus, and copies it on activation with announced success or failure. Tooltips use the top layer so they remain visible in scroll containers and dialogs. Keep controls outside links, buttons, summaries and select options. UUIDs and hashes in structured inspectors use this shared control automatically; source text, editable IDs and exported data retain their exact contents.

New internal UUIDs use `modelanvil.core.ids.uuid7`. Existing identifiers, imported source references and deterministic UUID5 sample references remain valid. Avoid using shortened UUID prefixes for display or identity: UUIDv7 prefixes encode time and are shared by nearby records. Prefer names, revisions and per-list ordinals.
