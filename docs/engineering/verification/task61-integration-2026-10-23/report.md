# Screen integration verification

PR15 was reconciled against the merged decision-loop, account-security, onboarding, privacy and protected-evaluation changes. Its shell groups data, development and context modes while preserving legacy links. Duplicate alias destinations were removed from the sidebar; their views remain available through the grouped workspaces and original URL aliases.

Workspace tab groups now expose linked labelled panels and one selected tab stop, with arrow/Home/End navigation. The guided comparison retains its per-run key and retry behavior; Overview retains the real next-step decision logic, invitation controls and privacy settings. Existing registration actions and durable run history remain accessible.

The frontend's 225 tests, production build and Storybook build pass. The [browser observation](screen-checks.json) exercises five legacy links, selected panels, keyboard wrapping/Home/End, one page heading, privacy controls and four representative screens at 1440/390 pixels. Screenshots were inspected after lazy loading and local requests settled; no page errors or page overflow were observed. No training, provisioning or inference job was launched by this screen check.

Backend changes come from the already-verified protected-evaluation delivery; this UI integration does not introduce another training or hardware qualification. Final PR-head CI is required before merge.
