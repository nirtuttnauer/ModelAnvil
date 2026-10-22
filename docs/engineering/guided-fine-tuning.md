# Guided local LLM fine tuning

The guided Training screen lets a new account fine-tune an instruction-tuned SmolLM2 model on its own text examples using compute managed by the local ModelAnvil installation. Users do not register tokenizers, manifests, workers or allowances, and do not run server commands.

## User flow

1. Create an account or sign in. Account creation supplies an isolated organization, team and first project. Browser credentials use an HttpOnly, SameSite cookie with CSRF protection; the browser stores only a session mode marker.
2. Choose the recommended instruction-tuned model. Apple computers with at least 32 GiB RAM use SmolLM2-1.7B-Instruct and lightweight rank-16 adapters across attention and feed-forward projections; other supported computers use SmolLM2-135M-Instruct with full SFT. The server verifies the pinned snapshot and prepares the matching tokenizer, runner, managed pool and a bounded training-step allowance in the user's workspace. Retries reuse these resources.
3. Upload JSONL, a JSON array or CSV. Accepted records contain `messages`, `prompt`/`response`, `prompt`/`completion`, `instruction`/`output`, `question`/`answer`, or `text`. For instruction/output records, an optional input field is preserved as prompt context. CSV column names are recognized without case or surrounding whitespace. Preview shows examples, duplicates removed, the training objective and actual split counts before publication.
4. Review the dataset, local GPU and automatic training plan. Six passes are recommended for adapter datasets with fewer than 100 training examples; other datasets use three. Each pass shuffles all training examples with a fixed seed and uses each once; validation and test examples remain outside optimization. Optional settings provide a three-step setup check or manual step count. Preflight checks the actual pinned inputs, storage, compute and allowance. If the managed trainer is offline, the dataset step says so before upload and names `python manage.py run_local` for the installation owner. Launch creates an idempotent durable job; the managed service executes it automatically. Progress, cancellation, download and a link to inspect the candidate remain available after reload.
5. Compare the exact candidate with its base model. Held-out examples are used when the dataset has them; otherwise the user confirms a short question list. Guided chat snapshots are scored with the model's native chat template. Paired answers and case failures sit beside **Record accept** and **Record reject**. Recording a choice does not deploy the model. Chat and download are ways to inspect the candidate, not evidence that it improved. A setup check or synthetic fixture cannot be accepted. An approved labeling snapshot can be chosen as the guided dataset without downloading and uploading the file again. The project owner can invite one teammate, who can record the decision.

Conversation examples preserve system, user and assistant roles. Training uses the verified model’s native chat template, including assistant end tokens, and masks prompt tokens from the loss. The advanced base-model profile retains its role-prefix format. The candidate exports its matching chat template so downloaded files and in-app chat use the same formatting. Plain text learns all text tokens.

The dataset step previews source rows and maps custom columns before publication. Its tokenizer-independent validation checks every source record, not only the five displayed samples. Missing required values, invalid text types and malformed chat roles block preparation with source row references. Empty optional or unused columns, exact duplicate training content and leading/trailing whitespace produce warnings. Exact duplicates use the publication kernel's content digest and are removed by guided preparation; other text is preserved. Changing a mapping rechecks the file and clears any prior prepared preview. Failed checks can be retried without losing the mapping; correcting source records requires uploading the corrected file. The subsequent tokenizer preview still enforces model token limits.

Related examples remain together: explicit `group_id` or `source_group_id` wins; otherwise repeated conversation prompts share a group. Whole groups are allocated proportionally into training, validation and test. Three or more independent groups retain at least one group in each requested held-out split. Smaller datasets remain in training with a visible warning.

## Installation owner setup

Run the API and managed service together in the trusted environment containing Django and the pinned GPU dependencies:

```sh
.venv-gpu/bin/python manage.py run_local
```

On this Mac, the default accelerator is `mps:0`. The command applies migrations and starts both services with a shared database and artifact store. The web development server retains its normal `/api` proxy to port 8000. A different local port can be passed as `run_local 127.0.0.1:8010`, with `VITE_API_URL` pointing to that API for Vite.

The managed service verifies the pinned local model files, fetching the allowlisted public snapshot if files are missing. It uses one installation lock, observes hardware, publishes a live heartbeat, and runs the shipped training executor and the guided comparison executor. Browser requests cannot choose executable code, host paths or device selectors. Existing job leases, cancellation, device admission and budget settlement remain in force. Email accounts can reset a password; this installation does not send mail, so a local development install shows the reset code in the browser and a production install does not.

The default model cache follows the selected model: `data/smollm2-1.7b-instruct` or `data/smollm2-135m-instruct`; installation owners may set `MODELANVIL_LOCAL_MODEL_DIR`. Self-service account creation defaults on in development and off when `DJANGO_DEBUG=0`; `MODELANVIL_SELF_SERVICE_ACCOUNTS` controls it explicitly. Existing API-key connections remain available. Existing engineers can use an enabled managed allowance; creating a new allowance requires an owner or administrator. New self-service accounts own their isolated workspace.

## Supported scope

The guided path supports two verified instruction snapshots: 1.7B FP32 LoRA on Apple GPUs with at least 32 GiB host RAM and 12 GiB process memory headroom, and 135M FP32 full SFT on the other supported GPUs, up to 1,000 examples, 16 MiB source files, 128 actual tokenizer tokens per example and 1–3,000 updates per run. Oversized examples are refused with repair guidance rather than truncated. The recommended complete passes adapt the instruction model to the dataset without asking users to guess a step count. AdamW uses 2e-4 for the large adapter profile or 2e-5 for the small full-SFT profile, with gradient clipping at norm 1. Only adapter parameters change in the large profile. The GPU installation requirements include the pinned PEFT and Accelerate dependencies. Three spaced checkpoints bound disk use, with the final checkpoint always saved; the checkpoint with the lowest measured validation loss supplies chat and download. A three-step setup check remains an explicit optional choice. Time estimates are approximate, and validation loss does not establish answer accuracy. New workspaces receive a 10,000-step local allowance; existing owner-configured allowances are retained. The advanced training workspace retains the other registered recipes and reference runtimes.

The local Apple GPU run, independently loaded export, browser chat and regression results are recorded in the [acceptance report](verification/guided-fine-tuning-2026-10-13/report.md).
The [fresh account browser retest](verification/first-user-retest-2026-10-13/report.md) covers UI signup, ordinary CSV, two local GPU runs, follow-up chat and the subsequent usability fixes.
The [useful local defaults report](verification/useful-local-training-2026-10-14/report.md) records the recommended six-pass adapter plan, real Apple GPU execution, validation checkpoint selection and reworded answer checks.
The [default-only fresh account retest](verification/defaults-fresh-account-2026-10-15/report.md) covers a different custom dataset, saved browser answers, conversation recovery and fixes to the unified training screen.


## Persistent local instance on this computer

The verified instance is running at `http://localhost:5180`, with its separate database and artifact store in the ignored `storage/guided-local` directory. To restart this same instance rather than opening the default development database, its installation owner can run:

```sh
DATABASE_NAME=storage/guided-local/modelanvil.sqlite3 MODELANVIL_ARTIFACT_ROOT="$PWD/storage/guided-local/artifacts" .venv-gpu/bin/python manage.py run_local 127.0.0.1:8010
```

The existing Vite server for this instance uses `VITE_API_URL=http://127.0.0.1:8010` and port 5180. This startup configuration belongs to the installation owner; users create accounts and train through the browser.

Password reset codes and invitation codes are consumed atomically and cannot be reused. A successful password reset revokes all existing API keys and browser sessions created by that account before issuing a fresh browser session. With DEBUG off, reset requests return the same response for known and unknown addresses. Email delivery remains unconfigured; development-only reset codes are never returned in production.
