# Fresh account browser retest

The complete signup → custom dataset → local training → model chat journey passed through the visible UI at `http://localhost:5180` on 13 October 2026. The test created a new disposable account through the signup form, using the isolated persistent `storage/guided-local` instance. No API key or server command was needed during the user journey.

The new [library help CSV](library-help.csv) contains 12 synthetic prompt/response examples with ordinary `Prompt,Response` headers. Preview preserved the roles and allocated 10 training examples, one validation example and one test example. The default SmolLM2-135M model and three training steps were retained.

| User action | Observed result |
| --- | --- |
| Create account | New isolated workspace and first project appeared automatically. |
| Choose model | Verified pretrained weights and matching resources were prepared automatically. |
| Upload custom CSV | Twelve examples previewed with assistant-only training and actual split counts. |
| Review and train | Approved checks; all three optimizer steps completed on `mps:0`, with three checkpoints and a succeeded job. |
| Try model | Exact candidate selected automatically; the default 128-token response streamed and was saved. |
| Follow-up chat | After the fix, two turns saved successfully, the exact model remained selected and a third message could be sent. |
| Reopen saved conversation | Both turns and the selected candidate were restored. |
| Invalid CSV | An empty answer identified `Example 1: response must contain nonempty text`, with repair guidance. Replacing the file restored a usable preview. |
| Duplicate dataset name | Returned a recoverable validation message. Editing the visible name field allowed publication and another successful three-step GPU run. |
| Download | The completed repeat run downloaded a 541,625,247-byte model archive. |
| Start another fine-tune | After the fix, model preparation led to an empty dataset step instead of silently reusing previous data. |
| Small screen and dark mode | Chat fit a 375-pixel viewport without horizontal overflow. Both themes were visually inspected; defaults restored afterward. |
| Sign out and return | Incorrect password produced useful feedback; correct sign-in restored the workspace. The app was finally signed out and left at signup. |

## Fixes made during the retest

- Simplified chat around the selected model and message box. Saved conversations, comparisons, device settings and draft details remain available through collapsed controls. Generated model names now have readable labels.
- Preserved model and generation configuration after saving a follow-up. Clearing the whole composer draft had reset the model, disabling the next message.
- Started a clean conversation when opening an exact model link, and retained that candidate for a new conversation.
- Reset the complete guided draft when starting another fine-tune.
- Validated duplicate dataset names before persistence, replacing an observed HTTP 500 with a rename message. Dataset uploads now preserve structured repair guidance, and editing the name resets incompatible import-resume state.
- Named the source field in invalid prompt/response records and removed internal `(root)` paths from displayed API errors.
- Made “Try your model” the primary completion action and explained that a short setup check does not establish useful answers.

The first completed run was `a83fc687-c592-44bf-a7ff-dc114baa4773`; the corrected repeat run was `d0f76f3d-028c-45ef-a979-87de0a8632f4`. Both completed three GPU steps. Read-only database checks corroborated job success, checkpoint counts and assistant-only training; browser actions performed signup, upload, launch, generation and download.

## Verification and limits

All 166 frontend tests passed. The focused backend suite ran 73 tests with one explicitly skipped test and no failures. Production frontend and Storybook builds passed, along with Django system checks, migration drift and whitespace checks. The browser assertions verified exact candidate handoff, model retention after follow-up, next-message availability, a clean next-run dataset and narrow-screen sizing. The full backend suite and all Storybook interaction plays were not rerun during this retest.

The three-step models produced repetitive, unreliable answers. This verifies execution and usability, not task quality. No quality benchmark, personal dataset, other model or other hardware was qualified. This download was verified through the browser; an independent exported-model consumer was verified in the [earlier acceptance](../guided-fine-tuning-2026-10-13/report.md), not repeated here.

## Evidence

- [Signup success](01-signup-success.txt), [CSV preview](02-csv-preview.txt) and [approved review](03-ready-to-train.txt)
- [Initial GPU evidence](training-evidence.json) and [corrected repeat GPU evidence](repeat-training-evidence.json)
- [Simplified chat](08-chat-simplified.png) and [completed follow-up](22-followup-after-fix.txt)
- [Invalid CSV feedback](14-invalid-csv-after-fix.txt), [duplicate-name repair](16-duplicate-name-after-fix.txt) and [successful renamed publication](17-duplicate-repair-success.txt)
- [Empty next-run dataset step](20-new-fine-tune-dataset.txt), [reopened conversation](26-reopened-conversation.txt) and [browser assertions](browser-regressions.json)
- [Narrow chat](24-mobile-chat.png), [dark-mode chat](25-mobile-dark-chat.png) and [download evidence](download-evidence.json)
- [Frontend tests](frontend-tests.txt), [focused backend tests](backend-tests.txt), [production build](frontend-build.txt) and [Storybook build](storybook-build.txt)

Disposable account credentials are excluded from these artifacts. The test workspace and trained models remain in the isolated local instance; existing workspace data was retained.
