# TASK-25 — bounded CPU GRPO, 23 October 2026

Implemented one real grouped policy-optimization recipe on the existing CPU character runtime, with independent qualification of its exported tensors. This is an authored numerical correctness fixture, not pretrained-language-model or production qualification. GPU, MLX and FP8 variants remain unsupported and require separate evidence.

## Actual local execution

Python 3.12.15 on this Mac. A seeded 12-token, width-4/rank-2 model received four real warm-up SFT updates, then three GRPO steps. Two authored training prompts and two protected held-out prompts use disjoint source groups; two separate regression probes are evaluated only by the independent consumer. Inputs are registered through the real project-scoped API and committed artifact storage, not supplied as declared scores. Fixture data and weights are repository-authored under its MIT license.

| Step | Real completions | Mean reward | Reward population std | Nonempty coverage | Tensor update |
| --- | --- | --- | --- | --- | --- |
| 1 | 8 | 0 | 0 | 0.75 | No |
| 2 | 8 | 0.25 | 0.4330127 | 0.75 | Yes |
| 3 | 8 | 0.25 | 0.4330127 | 0.875 | Yes |

The zero-dispersion first group correctly produces zero relative advantages. Exact categorical reference KL remains finite (about 1.33e-8 at step two, 2.22e-9 at step three). Verifier peak RSS was approximately 17.2 MB. The receipt pins actual code, input digests, source groups, frozen reference, sampler state, optimizer identity, verifier contract, checkpoint metrics and output weight digest.

Base weights: `f4c1b9ed4ccc5dfb004fcd963b53de923bb4195885676f4efa200bdfaf225913`.
Candidate weights: `cf9a10811094dcc300fc78a727e9a6b30091000bf8f405887d730f3be91eb240`.

## Recovery and accounting

A separate process executes the ordinary training path and exits with code 93 immediately after checkpoint one commits. The durable state remains running at step one with the original reservation and no settled usage. Corrupting the saved checkpoint digest causes the real resume endpoint to refuse recovery. Restoring the known fixture digest permits explicit takeover, rotates the execution token and restores the exact sampler/float32 state. Final tensors equal uninterrupted execution byte for byte; checkpoint steps remain 1, 2, 3. Prior worker tokens are refused. This is a deliberate fault-injection proof, not a naturally occurring process failure.

Completed execution replay preserves one usage event and settles three steps exactly once. Cancellation through the real API immediately after checkpoint one stops the next group, publishes no candidate and settles one step. Tests separately exercise budget revocation, invalid results and an actual sleeping child killed at its wall timeout. No timed-out or malformed verifier result becomes a successful reward.

## Independent quality measurements

A separate isolated stdlib process loads the actual Safetensors and computes greedy one-token inference, importing neither ModelAnvil nor Django. Base and candidate both score 1/2 on held-out probes and 2/2 on regression probes. Held-out accuracy improvement is **zero**; regression delta is **zero**. The executor's separately seeded sampled held-out completions score 0/2. Both protocols and raw responses are retained; sampled and greedy results are not interchangeable.

Numeric reward-hacking probes (`NaN`, infinity, multiple answers, verification banners and overflow) all score zero in the actual isolated verifier and independent checker. This tiny sample provides correctness evidence only. The candidate stays **draft**, with production qualification false and no promotion or general quality claim.

## Verifier limits

Fixed exact/numeric data rules only: no arbitrary verifier code, application imports, file operations or network operations. Two-second parent wall timeout, one-second POSIX CPU limit, zero file-output limit, 16 KiB input/output, eight records and 32 characters per answer. Accepted measured peak RSS must be at most 64 MiB. Linux additionally enforces 256 MiB address space. Darwin rejects lowering its address-space limit: this Mac receipt explicitly records **no OS address-space cap**, using fixed input bounds and measured peak RSS instead. This is not a general-purpose hostile-code sandbox.

## Reproduction and validation

`python scripts/qualify_grpo.py --output /absolute/new/directory` creates an isolated database and artifacts, exercises execution/failure/recovery/accounting and invokes `scripts/qualify_grpo_consumer.py`. Keep the generated browser API key private. See [actual receipt](actual-report.json) and [browser receipt](browser-report.json). Browser verification uses the real local API at 1440 and 390 pixels: imported group IDs, created and executed a GRPO plan, and took over a real process-death checkpoint. Screenshots were visually inspected.

Backend: 1,070 tests passed, 42 optional environment skips; focused alignment/OpenAPI: 45 tests passed. Frontend: 228 tests passed and production build passed. Migration generation check passed. Required remote CI must pass on the exact PR head before merge.

Algorithm and limits are documented in [CPU character alignment](../../cpu-character-alignment.md), with the primary DeepSeekMath reference and explicit differences.
