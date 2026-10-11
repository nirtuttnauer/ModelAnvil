# Bounded CPU character alignment

The alignment workspace executes real numerical updates for four recipes on pinned, committed local character-model weights. This is a synchronous CPU implementation with small inputs; it does not qualify arbitrary language models, GPUs or production deployment. Apply the `0007_alignmentrun_execution_pins_and_more` migration before using the new artifact pins.

| Recipe | Actual optimization and output |
| --- | --- |
| DPO | Analytic gradients of the preference log-ratio objective against a frozen reference; updated policy Safetensors. |
| Reward model | Bradley–Terry logistic training of a scalar reward head over a frozen character encoder; serialized float32 `reward_head.json` with its own digest and encoder pin. The encoder Safetensors remain unchanged intentionally. |
| PPO RLHF | Fresh multinomial policy samples scored by the pinned learned reward head; clipped policy updates, reference KL, and a trained value baseline. Output includes changed policy Safetensors and serialized value head. |
| Verifier RL | Fresh sampled policy completions scored by exact match, substring or numeric tolerance against each chosen response; clipped policy updates, reference KL and value training. Success/failure rewards are measured from generated text, not declared fixture scores. |

The algorithms persist measured per-step metrics and rollouts. Held-out predictions are computed separately from the disjoint held-out artifact. Different recipes expose different metrics; a saved `completed` label alone is not execution evidence. The scalar reward model is a reward scorer, not an aligned text generator.

## Inputs and API

1. Register training and held-out preferences separately with `POST /api/v1/alignment-runs/register-preferences/`: `{ "name": "Train preferences", "samples": [{ "prompt": "a", "chosen": "ab", "rejected": "cd" }] }`. Each response contains its committed artifact UUID and SHA-256. `GET /api/v1/alignment-runs/preference-artifacts/` lists accessible registered inputs.
2. Create a pending run with `POST /api/v1/alignment-runs/`. Supply an algorithm, numeric `policy_model_version`, UUID `train_dataset_artifact` and `held_out_dataset_artifact`, and `total_steps`. DPO and PPO require `reference_model_version`; PPO requires an actual trained `reward_model_version`; verifier RL requires `verifier_spec: { "type": "substring" }` or another supported rule. Artifact digests are derived by the server.
3. Execute with `POST /api/v1/alignment-runs/{run_id}/execute/`. The response is the serialized run, including measured progress, an output model version and server-owned execution evidence. Repeating execution of a completed run verifies and returns the same candidate without retraining or charging again.
4. Cancel with `POST /api/v1/alignment-runs/{run_id}/cancel/`. Pending cancellation publishes no weights. Running cancellation invalidates the claim token; later checkpoint/candidate publication is refused. Previous committed checkpoints remain inspectable. Interrupted or failed execution has no resume action; create a new plan.

A registered artifact contains `{ "schema_version": "modelanvil.preference-pairs.v1", "pairs": [...] }`. Both sets need 1–32 unique pairs, nonblank strings and distinct chosen/rejected responses. Responses are limited to 32 characters; prompt plus either response must fit 62 characters. Training and held-out prompts, after whitespace trimming, must be disjoint. Every character must exist in the pinned policy vocabulary. Supported policies use `modelanvil.cpu-character-sft.v1` and the bounded character tokenizer, at most 256 vocabulary entries, embedding width 16 and LoRA rank 4. Base/reference/reward models must pin the same tokenizer and actual accessible committed bundles.

Execution permits 1–100 optimizer steps. Hyperparameters must be finite numbers within the [OpenAPI bounds](../../contracts/schemas/openapi.json); booleans, unknown knobs and knobs from another recipe are rejected. DPO accepts `beta`; PPO/verifier accept `kl_coefficient`, `clip_range`, integer `ppo_epochs`, `rollout_batch_size`, `max_new_tokens` and `value_learning_rate`. All recipes accept `learning_rate` and `max_gradient_norm`. Numeric-tolerance verifiers accept finite `tolerance` from 0 to 1,000,000. The synchronous service uses a reproducible seed and float32 checkpoint state.

Legacy digest-only alignment records remain saved plans and cannot execute until both actual preference artifacts and a supported model bundle are pinned. This preserves earlier metadata without treating fabricated metrics as new execution.

## Isolation, accounting and publication

Engineer permission is required for preference registration, plan changes, execution and cancellation; viewers can inspect accessible records. Model/artifact references enforce tenant and project boundaries and explicit grants. Started plans become immutable. Input bytes, SHA-256, size, tombstones, tokenizer and reward-head checksums are checked before admission and again before final candidate publication.

Use a tenant `training_steps` budget. `hyperparameters.budget_policy_id` selects an enabled compatible policy; one existing compatible policy may be selected automatically. Multiple compatible policies require explicit selection. With no compatible policy, usage is recorded without a reservation. Admission reserves `total_steps` using the run UUID. Completion, failure or started cancellation settles the committed step count and records one idempotent `alignment:<run UUID>` usage event. Pending cancellation has no optimizer usage. Quantity is separate from monetary pricing; unpriced events remain unpriced.

Each checkpoint checks a live execution token, next-step cursor and pinned inputs. The candidate must match the verified final checkpoint and unchanged input pins before publication. Committed candidate artifacts contain actual Safetensors, tokenizer/configuration, any reward/value head and provenance. Filesystem bytes are immutable artifacts; as with other local artifact writers, a failed database commit may leave an unreferenced object for cleanup.

Execution evidence remains `integrated_execution`, with hardware and production qualification false. Local tests do not authorize release promotion. The integration suite independently parses Safetensors in a separate standard-library-only process and computes numerical inference; it makes no third-party runtime or hardware qualification claim.

## Verification

Run `.venv/bin/python manage.py test modelanvil.runners.alignment.test_numerical modelanvil.runners.alignment.test_alignment_execution`. The API journeys cover all four actual recipes, committed changed output (or changed reward head), independent byte loading, held-out input separation, corrupted artifacts/reward heads, numeric bounds, role/tenant/project restrictions, budget refusal, completed replay, pending cancellation and cancellation after one committed checkpoint. Parent integration also runs the existing fixture suites, frontend checks and application builds.
