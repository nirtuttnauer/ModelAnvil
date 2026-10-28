# Firefox and Safari WebKit acceptance

Firefox 151.0 and WebKit 26.5 passed production browser acceptance after fixing recipe step-ID validation. Both engines exercised the actual API and isolated local artifacts. Native Safari automation was disabled; the user explicitly selected WebKit coverage for this run. These results qualify the tested engines and workflows, not native Safari 27 or Firefox on macOS.

## Defect fixed

Firefox reported that the recipe editor's `[a-z][a-z0-9_-]{0,31}` input pattern was invalid under HTML's Unicode-set regular-expression rules. Its unescaped hyphen caused browser constraint validation to be ignored and repeated console errors. Escaping the hyphen preserves the intended lowercase-letter, digit, underscore and hyphen syntax. A regression test compiles the actual page pattern with the `v` flag and checks valid IDs, invalid characters and the 32-character limit. Real input validity checks passed in both engines after the fix.

## Completed checks

| Check | Firefox 151.0 | WebKit 26.5 |
| --- | --- | --- |
| All 18 screens, desktop and mobile navigation | Passed | Passed |
| Horizontal page overflow at 1440 × 1000 and 390 × 844 | None | None |
| Cold screen chunks, slow loading and aborted-chunk recovery | Passed | Passed |
| Unsaved drafts across navigation, project isolation and reload | Passed | Passed |
| Exact published-resource cold links, reload and browser Back | Passed | Passed |
| Recipe history restores definition without publication approval | Passed | Passed |
| Native recipe-ID validity, JSON file import and Blob export | Passed | Passed |
| Keyboard search, input focus, Enter and Escape | Passed | Passed |
| Selected WCAG A/AA checks for mobile and recovery states | Passed | Passed |
| Unexpected page exceptions or console errors after the fix | None | None |
| Fresh project → dataset publication → 2 actual CPU training steps → candidate chat → held-out evaluation → release download → authenticated local serving | 59.5 seconds | 50.5 seconds |
| Downloaded model independently runs with isolated standard-library Python and verified hashes | Passed | Passed |

Each engine recorded 42 screen/recovery assertions and seven additional interaction assertions, plus direct-resource and real local execution checks. Mobile pages and the long WebKit release screen were visually inspected. WebKit's sticky navigation remained at the viewport top when scrolling. The held-out quality review remained failing; local serving used a separate, explicitly declared infrastructure review with accuracy threshold zero. These executions do not establish model accuracy.

All **160 frontend tests** passed. TypeScript and the application production build passed without the application bundle-size warning; the main chunk remains about 281 kB. Storybook also built successfully, retaining its separate tooling bundle warnings. No backend implementation was changed by this browser fix, and the full backend suite was not repeated.

## Runtime and evidence

macOS Firefox failed before loading the app with subprocess-sandbox and framebuffer errors. Headless and windowed attempts did not resolve startup. Testing therefore used real Firefox in an isolated Linux arm64 container, with a matching Playwright client, while the API and CPU workers remained in the Mac QA workspace. A container-local localhost proxy preserved the secure-context requirements for WebCrypto upload verification; those application integrity checks were retained. Only temporary test files and the isolated container were changed during runtime setup.

The frozen frontend matched the checkout at completion. [Sanitized evidence](cross-browser-evidence.json) records its source identity, runtime details and assertions; [frontend summary](cross-browser-frontend-tests.txt) and [production build](cross-browser-build.txt) record regressions. The API used a frozen snapshot. Concurrent additions to the release deployment serializer and its test were outside that snapshot and are identified in the evidence. Credentials, private browser traces and model binaries are excluded.

See [Firefox mobile](firefox-mobile.png) and [WebKit mobile](webkit-mobile.png). QA services, workers and the temporary Firefox container were removed or stopped, and credentials in the isolated database disabled. Existing application data, services and browser settings were retained. Native Safari, Firefox on macOS and physical iOS devices remain untested in this run.
