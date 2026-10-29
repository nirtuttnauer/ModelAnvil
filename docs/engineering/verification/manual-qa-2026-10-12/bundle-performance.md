# Production bundle performance and regression QA

The production bundle-size warning is resolved. Screens now load through React's built-in lazy imports, with a screen-level Suspense loading status and an error boundary that offers an explicit reload. Navigation and project controls stay available during a slow or failed download. No dependency or warning-threshold change was needed.

| Measurement | Before | After |
| --- | --- | --- |
| Main JavaScript chunk, minified | 693.45 kB | 280.76 kB |
| Main JavaScript chunk, gzip reported by Vite | 189.27 kB | 86.84 kB |
| Largest application JavaScript chunk | 693.45 kB | 280.76 kB |
| Application production build warning | Present | Absent |

The main chunk is **59.5% smaller**. A cold Overview browser load fetched about **334 kB of decoded JavaScript**, including its dependencies, rather than the previous single 693 kB application bundle. Network inspection confirmed that Recipes, Training and Dataset Bank were not downloaded until opened. These byte measurements establish reduced startup payload; they do not establish a measured improvement in user-perceived loading time.

## Checks completed

- All **159 frontend tests passed**, including new loading/reload affordance tests and the synthetic acquisition-history regression. TypeScript, the application production build and whitespace checks passed.
- All **18 navigation screens** loaded at desktop 1440 × 1000 and mobile 390 × 844, with no unexpected browser errors or horizontal page overflow. These checks used built production chunks and the real API.
- A held Recipes download displayed an accessible loading status while navigation and project controls remained available. See [loading state](bundle-loading.png).
- An aborted Audit chunk displayed recovery within the screen. Navigating to Datasets still worked. Returning to Audit retained the recovery action, and explicit reload after restoring the download recovered the same `#audit` address. The injected download errors are recorded separately from normal navigation errors. See [recovery state](bundle-recovery.png).
- Unsaved Context Lab inputs survived navigation and remained isolated between projects. Exact published-resource links survived cold load, reload and browser Back. The real training run also survived reload.
- Axe WCAG A/AA checks passed on the mobile screen and failed-download recovery state. The two new states were visually inspected.
- A fresh browser project completed dataset preview/publication, two actual CPU optimizer steps, candidate inference, held-out baseline/candidate evaluation, frozen release review, archive download and authenticated local serving in **63.5 seconds**. The failed quality review remained failing. A separate infrastructure review explicitly used accuracy threshold zero; this does not qualify model quality.
- The downloaded archive executed independently with isolated standard-library Python, verified its weight hashes and generated two tokens.
- Storybook built successfully. Overview, Dataset Bank, Datasets, Run Detail and Context Lab interaction stories passed without page exceptions. This check also found and fixed a missing synthetic acquisition-history fixture that returned HTTP 501. Storybook's separate tooling/runtime bundles still emit their own size warning; the application build does not.

## Evidence and scope

[Sanitized evidence](bundle-performance-evidence.json), [application build](bundle-production-build.txt) and [frontend test summary](bundle-frontend-tests.txt) record the results. The final browser run used an isolated copy of the previous QA database and verified artifacts, plus a frozen frontend matching the current checkout. Its frontend source SHA-256 is `7a28241ce534341222e61fe72fa6263e0d0f5b1050b9d1f12e76bd66c8135510`. Concurrent resource-picker changes were included in the final production repeat. Credentials and model binaries are excluded from repository evidence.

The backend regression suite was not repeated for this frontend change; the preceding [829-test backend result and actual acquisition/recipe checks](remaining-fixes.md) remain the corresponding evidence. Specialist and Apple recipe model executions were not repeated for bundle splitting. Chromium was exercised here; subsequent [Firefox and Safari WebKit acceptance](cross-browser.md) adds engine coverage and fixes recipe input validation. Production hosting was not requalified. A missing deployment chunk requires reload after the server or connection is repaired.

QA servers and workers were stopped, and credentials in the isolated database disabled. Existing application data and services were retained. To repeat the automated frontend checks, run `npm test` and `npm run build` from `web`. Serve the built app with `vite preview` and the real API to repeat navigation, direct-link and interrupted-chunk checks.
