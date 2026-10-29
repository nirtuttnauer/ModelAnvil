# ANVIL-021 CPU character evaluation envelope

Label: `local`.

The policy and reference were committed in `f02a21a12d421a34b28359acadedb24b7de61ebc` before these runs. That commit contains the spread rule and the pinned protocol. It contains no measured completion, score, weight hash, spread, or tolerance. The checker landed in `05d0f967b3ffb83d4b9630e55bc8a12754568c40`. These four records were taken at that SHA from an empty `git status --porcelain`, after rebasing onto `16a9be95921f0d99566cd24c1e4e491123f0d0a1`.

Machine: `cursor`, Linux-6.12.94+-x86_64-with-glibc2.39, Python 3.12.3, Node v22.23.4. Records use `docs/engineering/schemas/local-evidence.v1.json`.

## Repeat runs

| File | Recorded at | Command | Exit |
| --- | --- | --- | --- |
| `repeat-1.json` | 2026-10-29T05:35:57+00:00 | `/workspace/.venv/bin/python scripts/cpu_character_eval_repeat.py` | 0 |
| `repeat-2.json` | 2026-10-29T05:36:04+00:00 | same command | 0 |
| `repeat-3.json` | 2026-10-29T05:36:11+00:00 | same command | 0 |
| `spread.json` | 2026-10-29T05:36:25+00:00 | spread command over the three stdout reports | 0 |

Each run is `modelanvil.runners.eval_worker.evaluation_worker_executor` at evidence level `integrated_execution`, seed 42, two SGD steps, greedy CPU decoding, exact match, two generated tokens. The three stdout reports agree on every exact field. `measured_spread` reports no exact disagreements. Every numeric tolerance is `0.0`. Checking each run against the three repeats returns `checks_ok: [true, true, true]`.

Measured values from the first run, identical on the other two except wall time:

- Candidate completion: `ab`
- Baseline completion: empty string
- Case score: `0.0`. Passed: `false`. Baseline score: `0.0`
- Accuracy value, both the `all` and `held-out` slices, candidate and baseline: `0.0` on 1 case
- Wilson upper: `0.7935`. Wilson lower: `0`
- Candidate weights SHA-256: `fe523dc37d67948ff1dd54eecf6ae05aa58d550c1501dca1456115a6d19af434`
- Baseline weights SHA-256: `904541009852d589e759e2e3538fe22948be35bb4604ef51cb79e79500c66e34`
- Wall seconds, recorded and not compared: `0.04171950099998867`, `0.030515171000388364`, `0.03109438899991801`

The held-out expected text is `not-the-model-output`. The run does not produce it. That is the reproduced result. It is not a quality pass, and it is not production or hardware qualification.

The tolerance is the measured spread under policy `cpu-character-eval-reproduction-v1`. The policy file was not edited after these runs and still stores no tolerance value.

## Gate G-rag

This change does not add a RAG number. The accuracy figures above are the character-evaluation reproduction, not a retrieval measurement.
