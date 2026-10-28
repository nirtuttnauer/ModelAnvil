# Guided local LLM fine tuning acceptance

**A fresh account can now prepare a pretrained model, upload its own chat dataset, review the inputs and launch real local GPU training through the browser.** The app supplies the matching tokenizer, runner, compute pool and training allowance. Users do not need server commands or an API key.

Verification date: 13 October 2026, Asia/Jerusalem. The real browser and APIs ran against an isolated SQLite database and artifact store. The managed service used the available Apple GPU on this computer. Existing workspace data was retained. After verification, the isolated instance was copied with SQLite backup and its artifact files into the ignored `storage/guided-local` directory for persistent local use; the app remains available at `http://localhost:5180`.

## Browser and execution results

| Check | Result |
| --- | --- |
| Self-service account API | Created an isolated account and first project; response disclosed no bearer credential. Its cookie was HttpOnly. |
| Welcome and sign-in UI | Passed with the new disposable account. Account creation, CSRF enforcement, sign-out and workspace isolation also passed backend tests. |
| Model setup | Prepared the verified pretrained SmolLM2-135M snapshot and matching resources automatically. No manual worker, tokenizer, manifest or budget selection. |
| Ordinary chat JSONL | Eight user/assistant examples previewed and published with roles preserved. Exact duplicate removal was enabled. |
| Held-out allocation | Six training examples, one validation example and one test example. Related prompts remain in the same group. |
| Training review | Preflight approved with automatic resource selection and three requested steps. |
| Real GPU execution | Three optimizer steps, three saved checkpoints, succeeded job and completed candidate. Recorded training used assistant-only targets on Apple MPS. |
| Reload | Returned to the completed guided run and its result actions. |
| Download | The browser downloaded a 541,625,246-byte archive containing actual model files and provenance. |
| Independent consumer | A separate transformers process loaded the downloaded files and generated eight tokens. The exported chat template was present; 331,625 values in the first attention query projection differed from the pretrained tensor converted to FP32. |
| In-app chat | “Try your model” selected the exact candidate and its chat template. A cookie-authenticated streamed response completed and was saved. |
| Narrow screen and dark mode | The flow fit a 375-pixel viewport with no horizontal overflow. Dark-mode screenshot inspected; viewport and theme restored afterward. |

The first GPU attempt exposed a readiness check that rejected the worker after its slot was claimed. The check now requires a fresh heartbeat while permitting the occupied single slot during execution. The corrected run completed, and a regression test covers busy and stale workers.

Training success establishes execution and export integrity, not useful task accuracy. This acceptance used synthetic support examples and three steps. It did not train a supplied personal dataset, benchmark quality, or qualify another model, GPU vendor or production deployment.

## Regression checks

| Check | Result |
| --- | --- |
| Full backend suite after account and chat changes | 844 tests ran; passed with nine explicitly skipped tests. |
| Final import, account and OpenAPI checks | 18 tests passed, including the subsequent instruction-context and CSV-header normalization check. |
| Frontend suite | All 163 tests passed. |
| Production frontend build | Passed. |
| Storybook build | Passed. Guided options are represented as an explicitly disconnected synthetic preview; the advanced training action opens the preserved workspace. |
| Django system checks and migration drift | Passed; no ungenerated migration changes. |
| Whitespace check | Passed. |

The networked test suites initially encountered sandbox restrictions on localhost listeners and then passed when allowed to bind their test servers. Skipped tests remain outside the pass claim. Storybook build success does not establish that every interaction play test ran.

## Recorded evidence

- [Welcome screen](01-welcome.jpg)
- [Pretrained model choice](02-model.jpg)
- [Ordinary chat dataset preview](04-dataset-preview.txt)
- [Approved review without manual selectors](05-ready-to-train.txt)
- [Completed guided result](07-completed.jpg)
- [Saved candidate chat](08-trained-model-chat.txt)
- [Narrow result layout](09-mobile-completed.jpg)
- [Dark-mode result](10-mobile-dark.jpg)
- [GPU steps, checkpoints, split counts and inference](training-evidence.json)
- [Independent exported model consumer](independent-export.json)
- [Final frontend tests](frontend-tests.txt)
- [Full backend regression](backend-tests.txt)
- [Final focused backend checks](focused-tests.txt)
- [Production build](frontend-build.txt)
- [Storybook build](storybook-build.txt)

The [setup guide](../../guided-fine-tuning.md) records the installation-owned service lifecycle and supported bounds: SmolLM2-135M, up to 1,000 examples, 128 tokens per example, and 1–50 steps per guided run.
