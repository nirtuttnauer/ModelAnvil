# ModelAnvil first time user post training review

**The current UI is not simple enough for a new user to post-train an existing LLM independently.** Project creation, custom CSV publication and budget creation worked. Model acquisition and training require operator-managed compute, and the easiest suggested model path creates untrained reference weights.

Reviewed on 13 October 2026, Asia/Jerusalem, through the real browser UI and API at `http://127.0.0.1:5180`. This was an exploratory usability walkthrough at an 813 × 951 viewport, not a training quality benchmark. No Storybook responses or mocked API calls were used. The browser footer reported matching client/API builds, with source digest prefix `28838a1d`.

## Starting conditions and results

The account began with no projects, datasets, models, workers, pools or budgets. Account and API-key provisioning required a Django shell because the visible UI offers an organization API-key connection rather than self-service account creation. This provisioning is an explicit exception to the first-time-user test; it does not count as successful onboarding. All subsequent project, dataset and budget writes used the UI.

An isolated SQLite database and artifact directory under `/private/tmp` kept this review separate from existing workspace data. Product code was unchanged. The review instance uses API port 8010 and UI port 5180.

| Journey step | Observed result |
| --- | --- |
| Arrive without a valid key | “Organization unavailable,” several authentication errors and an “API connected” indicator. Connection dialog asks for an API key without explaining how to obtain one. |
| Create project | Passed. Entering a name enables creation; the slug is generated. |
| Upload standard chat JSONL | Refused. Twenty records containing user/assistant `messages` returned “Input or split recipe is invalid for bounded source preparation.” No failing row, missing field or conversion guidance was shown. |
| Preview custom CSV | Passed after converting the examples to a single `text` column. This is plain-text input; it does not demonstrate preservation of chat roles or assistant-only training. |
| Use default held-out percentages | Without a group column, all 20 records entered training and none entered validation/test. The preview warned about empty held-out allocation. Mapping the `id` column as the source group yielded 17/1/2. |
| Publish custom dataset | Passed. One immutable revision with 20 samples was recorded. |
| Create training allowance | Passed. A lifetime allowance of 100 training steps appeared in the training selector; budget preflight passed for the default 50-step run. |
| Select a pretrained LLM | Hub search worked. Import remained unavailable without a download worker pool. Local import instead requires the user to already possess model files. |
| Resolve compute from the UI | Setup offers six local profiles, including model acquisition and two CPU reference training profiles. Its instructions require a worker process in the same application, database and artifact environment. No GPU training setup profile appears here. |
| Launch fine-tuning | Blocked. Dataset and budget passed; base model, tokenizer, runner manifest, pool, worker memory, worker slots and storage checks remained blocked. |
| Return from setup pages | Passed. The training draft and selected dataset restored automatically after navigation. |

The dataset is deliberately small and contains repeated synthetic support examples. Its split tests the controls, not leakage prevention or useful model quality. No model license acceptance, model download, paid compute, training launch or model quality evaluation occurred. [Final account state](account-state.json) confirms one project, dataset revision and budget, with zero models, workers, pools, jobs and training runs.

## Problems to address first

| Priority | First-time-user obstacle | Proposed change |
| --- | --- | --- |
| P1 | Users cannot discover how to get an account or organization key. A fresh visit looks like a broken populated application. | Provide a focused welcome/connection screen with the supported account provisioning path. Separate API reachability from authenticated workspace access. |
| P1 | The default dataset format expects an internal envelope. Ordinary chat training data fails with an opaque error. | Accept or guide conversion of `messages` and prompt/response records. Show the failing row, expected structure and a usable example. Preserve the distinction between plain-text training and chat SFT. |
| P1 | Downloading and training require application-server access. A newcomer reaches empty selectors and instructions to install/run workers. | Give the user a compute setup path appropriate to a pretrained LLM, or explicitly hand off to an administrator with an actionable request. Tie model, matching tokenizer, supported recipe and compute together. |
| P1 | “Initialize a CPU base” creates untrained character/byte reference weights. Following the suggested link does not achieve post-training a pretrained LLM. | Label this path as a reference execution demo and recommend a compatible pretrained model for the user's fine-tuning goal. |
| P2 | Published dataset success has no visible next action to train that revision. Training then asks for six separately registered resources. | Add “Fine-tune with this dataset” and carry the revision into a guided sequence: model → dataset review → compute → review and launch. Derive tokenizer and runner when possible. |
| P2 | The 80/10/10 graphic differs from the actual 20/0/0 allocation unless users understand source grouping. | Make actual split counts prominent, explain why related rows stay together, and give a concrete grouping example. Retain leakage protections. |
| P2 | Beginners see verbose draft policies, hashes, manifests and fully expanded sample envelopes before basic decisions. | Keep the first view focused on data examples and the next action; put provenance, limits and advanced settings behind expandable details. |

The generic preparation error originates in `modelanvil/data/publication.py`, which collapses multiple parsing and validation exceptions into one message. `modelanvil/jobs/setup.py` defines the six profiles observed in compute setup; `web/src/components/ComputeSetup.tsx` supplies the manual worker connection instructions. These source checks support the observed behavior, but were not used to bypass the UI journey.

## Browser evidence

- [Unconnected entry screen](01-unconnected.jpg)
- [Empty dataset setup](02-empty-datasets.jpg)
- [Chat JSONL error](03-chat-format-error.txt)
- [CSV preview with no group column](04-csv-preview-no-groups.txt)
- [Published custom dataset](05-published-dataset.txt)
- [Initial training preflight](07-training-prerequisites.txt)
- [CPU initialization creates untrained weights](09-cpu-base-is-untrained.txt)
- [Hub model acquisition requires a worker](10-hub-model-acquisition.txt)
- [Compute setup requires operator access](12-compute-setup.txt)
- [Final preflight after budget setup](15-final-training-blocked.txt)
- [Visible final blocking checks](15-final-training-blocked.jpg)

The UI walkthrough establishes the onboarding obstacles above. It does not establish that the underlying operator-configured training runtime is broken, nor does it qualify GPU execution, production deployment or output quality.
