# ModelAnvil in FigCraft

Open **ModelAnvil.figcraft** in the installed FigCraft desktop app. It is the current, native auto-layout project. **ModelAnvil-snapshots.figcraft** preserves the original SVG-based design as a reference.

The project contains 19 desktop screens, matching tablet and mobile screens, five state examples, a component library, foundations, and a variable playground. Content comes from this repository's synthetic Storybook fixtures.

## Reusable component families

Select an instance and edit its properties in FigCraft's Design panel.

| Family | Properties |
| --- | --- |
| Button | Style: Primary / Secondary / Quiet; State: Default / Hover / Pressed / Focus / Disabled; Icon: Hidden / Visible; editable Label; swappable Glyph |
| Tab | Default / Active state; editable Label |
| Badge | Neutral / Success / Caution / Error tone; editable Label |
| Card | Surface / Subtle / Accent tone; editable Content slot |
| Notice | Caution / Error / Success tone; editable Content slot |
| Field | Input / Multiline kind; Default / Focus / Error / Disabled state; editable Value |
| Header | Desktop / Compact size; editable Page label |
| Navigation item | Page and Default / Selected state |
| Record row | Schema variants with editable cell values |
| Metric summary | Action / Read only behavior; editable Label, Value and Detail; Show detail toggle |
| Feedback | Loading / Empty / Error state; editable Title and Description; Show description / Show action; editable Action slot |

Checklists, charts, and icons are also reusable components. Cards and notices accept their own content through slots. Chart values come from the recorded demo measurements; native bars and wrapping step columns preserve the values while resizing.

The **Interaction states · Light and dark** board shows the action and field states in both themes. It wraps from 320–1100 px in Compact and Comfortable density. Hover and Pressed action colors are shared variables; Focus and Error use the semantic accent and error colors. These variants document native browser states; the React app activates them through pointer, keyboard, validation, and disabled attributes.

The **Feedback · Loading empty and recovery** board demonstrates the shared feedback family in Light and Dark themes. Horizontal icon/content auto layout wraps text from 320–1100 px in both densities. The Action slot accepts a reusable Button whose Label remains editable when switching feedback states. Matching React components announce loading and errors, respect reduced motion, and keep retry buttons from submitting surrounding forms. The loading glyph is static in the native design.

The **Resource summaries · Actions and read-only values** board shows the shared metric family in both themes, including zero, long values and hidden detail. Overview uses Action instances; accounting summaries use Read only instances. Existing metric instance IDs are retained. Native action examples document the affordance; React supplies pointer, keyboard, disabled and focus behavior. Overview labels, counts and supporting text match the recorded demo data.

## Shared variables

The file contains 58 real FigCraft variables:

- **Theme:** Light and Dark semantic colors.
- **Density:** Compact and Comfortable spacing, corner radii, and typography.
- **Workspace:** editable product, project, and organization labels.

Apply Theme or Density modes to a page or wrapping frame so nested instances inherit them. The **Variables in use** playground on the Components page demonstrates Light / Compact and Dark / Comfortable. Variable values can be imported from `variables.json`; `tokens.css` contains FigCraft's CSS export.

Use component properties for instance-specific labels and values. Use variables for shared design decisions.

## Responsive layouts

Desktop frames start at 1440 × 1280; tablet frames at 768 × 1100; mobile frames at 390 × 1100. Main content uses Fill and Hug sizing, wrapping grids, and vertical scrolling. Compact screens stack complex panels and present table rows as labeled records.

The desktop rail and compact header are explicit shell variants. Choose the matching shell/reference frame at a breakpoint; FigCraft does not automatically switch variants at a CSS media query. Auto layout handles resizing inside each shell.

Present mode supports desktop navigation, Overview → Training, and the compact Menu overlay. The file remains a design prototype; it does not run training or API actions and does not synchronize changes back to React.

## Verification and sources

`verification.json` records successful variant switching, inherited theme changes, a spacing-variable update, scrolling, desktop navigation, compact-menu navigation, and containment checks for all 19 screens at 320, 390, 768, 1024, and 1440 px in Compact density. The final Chat copy-control correction was rechecked at 320 and 390 px. No horizontal containment failures remain.

`manifest.json` records the current frame and component IDs. `component-system.json` records the variant families and variable IDs. `previews/` contains renders from FigCraft's renderer. `layouts/` contains captured source semantics and vector assets; `screens/` contains the original SVG sources. Snapshot manifests and verification records refer to the preserved reference file.

These are demo designs, not backend qualification or a full accessibility audit. Fonts are normalized to Arial for portable rendering.
