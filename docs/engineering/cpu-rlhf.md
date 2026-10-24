# CPU learned reward and RLOO

TASK-24 adds a dedicated local CPU worker for the exact plain SmolLM2-135M snapshot `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`. It trains actual reward weights and a rank-eight q/v policy adapter. It requires the pinned packages in `requirements.gpu.txt`, one CPU thread and a host with at least 16 GiB physical memory. The package filename also serves existing GPU profiles; this worker explicitly places all parameters and math on CPU.

The profile permits 1–20 updates, 1–32 reviewed pairs per split, and 128 tokens per sequence without truncation. RLOO samples 2–4 fresh completions of at most eight tokens for one prompt per update. It does not append an EOS that was not sampled. Reward training includes the tokenizer's EOS in each labelled response. Control tokens and unstable prompt boundaries are refused. Older character examples and PPO records remain separate reference paths.

## Math and model files

Reward training freezes the pretrained encoder and fits a 576-weight, bias-free scalar head to mean response hidden states with Bradley–Terry pair loss. Its download contains `reward_head.safetensors`, pooling configuration, Apache license and exact base/data/checkpoint provenance. Independent held-out scoring reports pair ranking, log loss, Brier score, reliability bins and individual chosen/rejected scores. Calibration includes both label orientations; the pair count is the independent sample count.

RLOO freezes that learned head and the starting reference. Fresh full-vocabulary multinomial samples receive learned reward minus beta times the sampled policy/reference log ratio. Each sample's baseline is the mean reward of the other samples for the same prompt. A single on-policy sequence REINFORCE update uses these detached, unstandardized advantages. This follows [Ahmadian et al., section 2.3](https://arxiv.org/html/2402.14740v1). Stale rollouts cannot be reused after a policy change. Post-update categorical KL at sampled contexts enforces the configured stop limit; it differs from the signed sampled log ratio.

Only adapter parameters change. Downloads contain Safetensors/PEFT adapter files and exact base provenance; acquire the pinned base separately. Verified policy candidates use existing bounded local inference. Reward heads are scoring models and are excluded from chat and SFT base selection.

## Operator and user flow

Import the verified local plain base with `setup_gpu_training --device cpu` using canonical sample-envelope JSONL; this operator command neither downloads weights nor starts training. Disable its unused SFT worker if only alignment is needed. Register a separate single-slot worker:

```sh
python manage.py setup_cpu_rlhf_worker --tenant-id TENANT_UUID --name cpu-rlhf
python manage.py run_worker --worker-id WORKER_ID \
  --executor modelanvil.runners.alignment.hf_rlhf.worker_executor
```

In Alignment, register reviewed preference artifacts with source group IDs. Choose Reward Model, its CPU pool, exact base/reference, and separate training, held-out and regression data. Select explicit `training_steps` and `alignment_scores` policies. Queue and execute the worker. For RLOO, select its successfully produced and independently checked reward head plus a `generated_tokens` policy. RLOO's held-out/regression groups and prompts must also be disjoint from all data used to train or select the reward head. The API rechecks owner-attestation audit scope or exact formal-review export identity and current project access.

Each stage records declared upper resource bounds before computing. Checkpoints preserve weights, Adam moments, phase, update cursor, rollout scores, reference logits and CPU sampling RNG. Training, rollout and scoring have distinct reservations, including capacity for at most three attempts. Measured committed or aborted stages settle measured units. Interrupted work without a valid measurement stays explicitly unknown and charges its declared upper bound. Settlement releases unused capacity. These are resource quotas without monetary currency; sequence scoring calls differ from predicted tokens.

Lease expiry fences the old attempt and resumes the last committed stage. A committed rollout is restored instead of resampled. Cancellation kills and waits for an active independent scorer. Divergence stops preserve a measured aborted update and publish no candidate. Partial failures leave existing model revisions untouched.

## Qualification

The fixed independent subprocess imports neither Django nor ModelAnvil. It rechecks exact file/data hashes, loads weights on CPU and recomputes reward ranking/calibration or policy preference scores plus separate chosen-response regression NLL against the starting model. Missing or failed evaluation blocks bounded qualification. Passing checks still produce an immutable **draft**, `production_qualified=false`; registry labels and authored fixtures cannot authorize promotion. Customer quality and other profiles require separate evidence.

The opt-in proof creates an isolated database and owned artifact directory, uses authored test-owner labels, and revokes fixture authority on exit:

```sh
python scripts/qualify_cpu_rlhf.py --model-dir /path/to/pinned/base \
  --output /new/path/to/cpu-rlhf-proof
```

Run numerical qualifications serially. This bounded correctness check is not an idle-host performance benchmark or customer quality evaluation.
